import base64
import io
import ipaddress
import json
import math
import os
import re
import time
import uuid
import zipfile

from ensp_kit import MODELS, port_index
from vrp_security import clean_command, clean_plan, resource_path, safe_id

SCHEMA_VERSION = 1
MAX_DEVICES = 12
MAX_LINKS = 64
MAX_SNAPSHOTS = 30
MAX_SNAPSHOT_BYTES = 1024 * 1024
MAX_IMPORT_BYTES = 4 * 1024 * 1024
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,15}$")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _ports_for(model):
    if model == "AR1220":
        return [f"GE0/0/{i}" for i in range(2)] + [f"Ethernet0/0/{i}" for i in range(8)] + \
            [f"Serial0/0/{i}" for i in range(2)]
    if model == "AR2220":
        return [f"GE0/0/{i}" for i in range(3)] + [f"Serial0/0/{i}" for i in range(2)]
    if model == "S5700":
        return [f"GE0/0/{i}" for i in range(1, 25)]
    if model == "S3700":
        return [f"Ethernet0/0/{i}" for i in range(1, 23)] + [f"GE0/0/{i}" for i in range(1, 3)]
    if model == "PC":
        return ["GE0/0/0"]
    return []


def capabilities():
    labels = {"AR1220": "AR1220 路由器", "AR2220": "AR2220 路由器",
              "S5700": "S5700 交换机", "S3700": "S3700 交换机", "PC": "PC 终端"}
    return [{"model": model, "label": labels.get(model, model),
             "console": bool(spec.get("console")), "ports": _ports_for(model),
             "pc": model == "PC"} for model, spec in MODELS.items()]


def _coord(value, default):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(value):
        return default
    return int(max(0, min(value, 3000)))


def validate_topology(devices, links):
    errors = []
    if not isinstance(devices, list) or not (1 <= len(devices) <= MAX_DEVICES):
        return None, None, [f"设备数量必须是 1 到 {MAX_DEVICES} 台"]
    if not isinstance(links, list):
        return None, None, ["链路必须是数组"]
    if len(links) > MAX_LINKS:
        return None, None, [f"链路不能超过 {MAX_LINKS} 条"]

    cleaned_devices = []
    names = set()
    by_name = {}
    used_ports = {}
    for index, item in enumerate(devices):
        if not isinstance(item, dict):
            errors.append(f"第 {index + 1} 台设备不是对象")
            continue
        name = str(item.get("name") or "").strip()
        model = str(item.get("model") or "")
        if not NAME_RE.fullmatch(name):
            errors.append(f"设备名「{name}」无效，只能使用字母开头的 1-16 位字母、数字、_、-")
            continue
        if name in names:
            errors.append(f"设备名重复：{name}")
            continue
        if model not in MODELS:
            errors.append(f"{name} 的型号 {model or '空'} 不支持")
            continue
        device = {"name": name, "model": model,
                  "x": _coord(item.get("x"), 120 + (index % 4) * 210),
                  "y": _coord(item.get("y"), 120 + (index // 4) * 150)}
        if model == "PC":
            ip = str(item.get("ip") or "").strip()
            mask = str(item.get("mask") or "").strip()
            gateway = str(item.get("gateway") or "").strip()
            try:
                ipaddress.IPv4Address(ip)
                ipaddress.IPv4Network("0.0.0.0/" + mask)
                ipaddress.IPv4Address(gateway)
            except (ipaddress.AddressValueError, ipaddress.NetmaskValueError, ValueError):
                errors.append(f"PC {name} 的 IP、掩码或网关无效")
            device.update({"ip": ip, "mask": mask, "gateway": gateway})
            if item.get("mac"):
                device["mac"] = str(item["mac"])[:32]
        names.add(name)
        by_name[name] = device
        cleaned_devices.append(device)

    cleaned_links = []
    seen_pairs = set()
    for index, item in enumerate(links):
        if not isinstance(item, dict):
            errors.append(f"第 {index + 1} 条链路不是对象")
            continue
        a, b = str(item.get("a") or ""), str(item.get("b") or "")
        if a not in by_name or b not in by_name:
            errors.append(f"第 {index + 1} 条链路引用了不存在的设备")
            continue
        if a == b:
            errors.append(f"第 {index + 1} 条链路不能连接设备自身")
            continue
        pair = tuple(sorted((a, b)))
        if pair in seen_pairs:
            errors.append(f"{a} 和 {b} 之间重复连线")
            continue
        seen_pairs.add(pair)
        link = {"a": a, "b": b}
        for side, port_key in (("a", "aPort"), ("b", "bPort")):
            dev_name = link[side]
            model = by_name[dev_name]["model"]
            requested = str(item.get(port_key) or "").strip()
            try:
                port_index_value = port_index(model, requested) if requested else None
            except ValueError:
                errors.append(f"{dev_name} 没有接口 {requested}")
                continue
            used = used_ports.setdefault(dev_name, set())
            if port_index_value is not None and port_index_value in used:
                errors.append(f"{dev_name} 的接口 {requested} 已被占用")
                continue
            if port_index_value is None:
                for candidate in _ports_for(model):
                    candidate_index = port_index(model, candidate)
                    if candidate_index not in used:
                        requested = candidate
                        port_index_value = candidate_index
                        break
                if port_index_value is None:
                    errors.append(f"{dev_name} 没有空闲接口")
                    continue
            used.add(port_index_value)
            link[port_key] = requested
        if "aPort" in link and "bPort" in link:
            cleaned_links.append(link)

    if not errors and len(cleaned_devices) != len(devices):
        errors.append("有设备未能完成校验")
    return cleaned_devices, cleaned_links, errors[:20]


def _text(value, limit):
    return str(value or "").strip()[:limit]


def build_sandbox_lab(payload, existing=None):
    if not isinstance(payload, dict):
        raise ValueError("实验数据必须是对象")
    title = _text(payload.get("title"), 40)
    if len(title) < 2:
        raise ValueError("实验名至少 2 个字")
    devices, links, errors = validate_topology(payload.get("devices"), payload.get("links"))
    if errors:
        raise ValueError("；".join(errors))
    sandbox_step = {
        "id": "s1",
        "title": "自由拓扑实验",
        "brief": "这是一张自定义沙箱拓扑，不计分。用 Web 终端或 eNSP 配置设备。",
        "why": "先把拓扑和设备状态跑通，再把它扩展成检查点实验。",
        "hints": [],
        "check": [],
        "apply": {},
    }
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    can_update = bool(existing and existing.get("sandbox") and existing.get("source") in ("user", "ai"))
    lab_id = existing.get("id") if can_update else "user-" + uuid.uuid4().hex[:8]
    lab = {
        "id": safe_id(lab_id),
        "title": title,
        "subtitle": _text(payload.get("subtitle") or "自定义拓扑沙箱", 120),
        "level": _text(payload.get("level") or "入门", 12),
        "minutes": max(1, min(int(payload.get("minutes") or 20), 600)),
        "tags": ["自定义", "沙箱"],
        "intro": "浏览器创建的自定义拓扑。设备启动后可用 Web 终端配置，也可使用快照保存状态。",
        "devices": devices,
        "links": links,
        "steps": [sandbox_step],
        "sandbox": True,
        "source": "user",
        "mode": "sandbox",
        "createdAt": (existing or {}).get("createdAt") or now,
        "updatedAt": now,
        "txttips": [],
    }
    return lab


def _sanitize_checks(items, names):
    if items is None:
        return []
    if not isinstance(items, list) or len(items) > 30:
        raise ValueError("检查点格式无效或数量过多")
    out = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("检查点必须是对象")
        dev = str(item.get("dev") or "")
        if dev not in names:
            raise ValueError(f"检查点引用了不存在的设备 {dev}")
        cmd = clean_command(item.get("cmd"), read_only=True)
        clean = {"dev": dev, "cmd": cmd}
        if "expect" in item:
            exp = item["expect"]
            if isinstance(exp, list):
                clean["expect"] = [_text(x, 500) for x in exp if str(x)]
            else:
                clean["expect"] = _text(exp, 1000)
        elif "expect_any" in item:
            if not isinstance(item["expect_any"], list):
                raise ValueError("expect_any 必须是数组")
            clean["expect_any"] = [_text(x, 500) for x in item["expect_any"] if str(x)]
        else:
            raise ValueError("检查点缺 expect")
        if not clean.get("expect") and not clean.get("expect_any"):
            raise ValueError("检查点期望值为空")
        for key in ("timeout", "attempts", "retry_wait"):
            if key in item:
                try:
                    clean[key] = float(item[key]) if key == "retry_wait" else int(item[key])
                except (TypeError, ValueError):
                    pass
        out.append(clean)
    return out


def _sanitize_steps(steps, names):
    if not isinstance(steps, list) or not (1 <= len(steps) <= 20):
        raise ValueError("步骤数量必须是 1 到 20")
    out = []
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError("步骤必须是对象")
        clean = {
            "id": f"s{index + 1}",
            "title": _text(step.get("title") or f"第 {index + 1} 步", 120),
            "brief": _text(step.get("brief"), 2000),
            "why": _text(step.get("why"), 3000),
            "hints": [_text(x, 5000) for x in (step.get("hints") or []) if str(x)][:10],
            "check": _sanitize_checks(step.get("check"), names),
            "keep": _sanitize_checks(step.get("keep"), names),
            "apply": clean_plan(step.get("apply") or {}),
        }
        out.append(clean)
    return out


def sanitize_import_lab(data):
    if not isinstance(data, dict):
        raise ValueError("lab.json 必须是对象")
    devices, links, errors = validate_topology(data.get("devices"), data.get("links"))
    if errors:
        raise ValueError("；".join(errors))
    names = {d["name"] for d in devices}
    steps = _sanitize_steps(data.get("steps"), names)
    lab = {
        "id": "import-" + uuid.uuid4().hex[:8],
        "title": _text(data.get("title") or "导入实验", 40) or "导入实验",
        "subtitle": _text(data.get("subtitle"), 120),
        "level": _text(data.get("level") or "入门", 12),
        "minutes": max(1, min(int(data.get("minutes") or 20), 600)),
        "tags": [_text(x, 30) for x in (data.get("tags") or []) if str(x)][:8],
        "intro": _text(data.get("intro"), 4000),
        "symptom": _text(data.get("symptom"), 2000),
        "devices": devices,
        "links": links,
        "steps": steps,
        "mode": "troubleshoot" if data.get("mode") == "troubleshoot" else "sandbox",
        "sandbox": bool(data.get("sandbox")),
        "source": "user",
        "txttips": [],
        "importedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if lab["mode"] == "troubleshoot":
        try:
            lab["base"] = clean_plan(data.get("base") or {})
            lab["inject"] = clean_plan(data.get("inject") or {})
        except ValueError as exc:
            raise ValueError("故障注入命令不安全：" + str(exc))
    return lab


def validate_snapshot(obj, lab):
    if not isinstance(obj, dict):
        raise ValueError("快照格式无效")
    devices = {d["name"]: d for d in lab.get("devices", [])}
    configs = obj.get("devices")
    if not isinstance(configs, dict) or not configs:
        raise ValueError("快照没有设备配置")
    clean = {}
    for name, value in configs.items():
        if name not in devices or not devices[name].get("model"):
            continue
        if isinstance(value, dict):
            text = value.get("config", "")
        else:
            text = value
        text = str(text)
        if len(text.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
            raise ValueError(f"{name} 的配置超过 1MB")
        clean[name] = {"model": devices[name]["model"], "config": text}
    if not clean:
        raise ValueError("快照中没有可恢复的设备")
    return clean


def zip_bytes(lab, snapshots):
    buf = io.BytesIO()
    manifest = {
        "format": "ensp-coach-sandbox",
        "schemaVersion": SCHEMA_VERSION,
        "exportedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "labId": lab.get("id"),
        "title": lab.get("title"),
        "snapshotCount": len(snapshots),
    }
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        zf.writestr("lab.json", json.dumps(lab, ensure_ascii=False, indent=2))
        zf.writestr("README.txt",
                    "网络实验陪练沙箱包\n\n"
                    "导入后设备需要重新启动。快照和配置可能包含口令等敏感信息，请勿公开分享。\n")
        for item in snapshots[:MAX_SNAPSHOTS]:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                continue
            try:
                snapshot_id = safe_id(item["id"])
            except ValueError:
                continue
            zf.writestr("snapshots/" + snapshot_id + ".json",
                        json.dumps(item, ensure_ascii=False, indent=2))
    return buf.getvalue()


def read_import_package(data):
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ValueError("沙箱文件为空")
    if len(data) > MAX_IMPORT_BYTES:
        raise ValueError("沙箱文件超过 4MB")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return _read_import_zip(zf)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise ValueError("不是有效或未加密的 ZIP 沙箱包") from exc


def _read_import_zip(zf):
    names = zf.namelist()
    if len(names) > 64:
        raise ValueError("沙箱文件条目过多")
    total = 0
    for info in zf.infolist():
        normalized = info.filename.replace("\\", "/")
        if normalized.startswith("/") or ".." in normalized.split("/") or info.is_dir():
            raise ValueError("沙箱包含非法路径")
        total += info.file_size
        if info.file_size > MAX_IMPORT_BYTES or total > MAX_IMPORT_BYTES * 2:
            raise ValueError("沙箱解压后过大")
    try:
        lab_data = json.loads(zf.read("lab.json").decode("utf-8"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("沙箱缺少有效的 lab.json") from exc
    lab = sanitize_import_lab(lab_data)
    snapshots = []
    for name in names:
        if not re.fullmatch(r"snapshots/[A-Za-z0-9_-]{1,128}\.json", name):
            continue
        try:
            item = json.loads(zf.read(name).decode("utf-8"))
            clean = validate_snapshot(item, lab)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        snapshots.append({
            "schemaVersion": SCHEMA_VERSION,
            "id": safe_id(item.get("id") or os.path.splitext(os.path.basename(name))[0]),
            "label": _text(item.get("label") or "导入快照", 80),
            "at": float(item.get("at") or time.time()),
            "variant": _text(item.get("variant"), 80),
            "devices": clean,
        })
    return lab, snapshots[:MAX_SNAPSHOTS]


def encode_base64(data):
    return base64.b64encode(data).decode("ascii")


def decode_base64(text):
    try:
        return base64.b64decode(text, validate=True)
    except Exception as exc:
        raise ValueError("沙箱文件编码无效") from exc


def snapshots_dir(work_dir, lab_id):
    return os.path.join(work_dir, "snapshots", safe_id(lab_id))


def snapshot_path(work_dir, lab_id, snapshot_id):
    return resource_path(snapshots_dir(work_dir, lab_id), snapshot_id)


def save_snapshot(work_dir, lab, configs, label="", variant=""):
    clean = validate_snapshot({"devices": configs}, lab)
    snapshot_id = "snap-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    item = {
        "schemaVersion": SCHEMA_VERSION,
        "id": snapshot_id,
        "label": _text(label or "手动快照", 80),
        "at": time.time(),
        "variant": _text(variant, 80),
        "devices": clean,
    }
    folder = snapshots_dir(work_dir, lab["id"])
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, snapshot_id + ".json"), "w", encoding="utf-8") as f:
        json.dump(item, f, ensure_ascii=False, indent=2)
    _prune_snapshots(folder)
    return item


def _prune_snapshots(folder):
    files = [os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".json")]
    if len(files) <= MAX_SNAPSHOTS:
        return
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    for path in files[MAX_SNAPSHOTS:]:
        try:
            os.remove(path)
        except OSError:
            pass


def load_snapshot(work_dir, lab_id, snapshot_id):
    path = snapshot_path(work_dir, lab_id, snapshot_id)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def list_snapshots(work_dir, lab_id):
    folder = snapshots_dir(work_dir, lab_id)
    if not os.path.isdir(folder):
        return []
    out = []
    for name in os.listdir(folder):
        if not name.endswith(".json"):
            continue
        try:
            item = load_snapshot(work_dir, lab_id, name[:-5])
        except ValueError:
            continue
        if not item:
            continue
        out.append({
            "id": item.get("id", ""),
            "label": item.get("label", ""),
            "at": item.get("at", 0),
            "variant": item.get("variant", ""),
            "devices": len(item.get("devices") or {}),
        })
    out.sort(key=lambda x: x.get("at", 0), reverse=True)
    return out


def delete_snapshot(work_dir, lab_id, snapshot_id):
    path = snapshot_path(work_dir, lab_id, snapshot_id)
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return False


def strip_terminal(text):
    text = ANSI_RE.sub("", str(text or ""))
    text = CONTROL_RE.sub("", text.replace("\r", ""))
    return text.replace("\b", "")


VIEW_HEADER_RE = re.compile(
    r"^(?:interface\s+\S+|ospf\s+\d+(?:\s+router-id\s+\S+)?|bgp\s+\d+|isis(?:\s+\d+)?|"
    r"rip(?:\s+\d+)?|acl\s+\S+|vlan\s+\d+|area\s+\S+|ipv4-family(?:\s+\S+)?|"
    r"ip\s+vpn-instance\s+\S+|ip\s+pool\s+\S+|aaa|route-policy\s+\S+|user-interface\s+\S+|"
    r"nat\s+address-group\s+\S+|key-chain\s+\S+|"
    r"firewall\s+zone\s+\S+|wlan\s+ac|"
    r"traffic\s+(?:classifier|behavior|policy)\s+\S+|qos\s+policy\s+\S+)(?:\s|$)",
    re.I,
)
EXACT_VIEW_HEADERS = {"mpls", "segment-routing"}
RESTORE_SKIP_RE = re.compile(
    r"^(?:\[[A-Z0-9]{6,}\]|board\s+add\b|portal\s+local-server\s+load\b|"
    r"drop\s+illegal-mac\b|set\s+cpu-usage\b)", re.I)
OPTIONAL_RESTORE_RE = re.compile(
    r"^(?:snmp-agent$|clock\s+timezone\b|wlan\s+ac$|firewall\s+zone\b|priority\s+\d+\b)",
    re.I)
BENIGN_RESTORE_RE = re.compile(r"already exists|The configuration has been", re.I)


def restore_issue_is_warning(command, issue):
    return bool(OPTIONAL_RESTORE_RE.match(command) or BENIGN_RESTORE_RE.search(issue))


def _config_lines(text):
    text = strip_terminal(text)
    lines = text.splitlines()
    if lines and "display current-configuration" in lines[0]:
        lines = lines[1:]
    if lines and re.fullmatch(r"[<\[].{0,60}[>\]]", lines[-1].strip()):
        lines = lines[:-1]
    out = []
    for line in lines:
        value = line.strip()
        if not value or value == "!":
            continue
        if re.match(r"^(?:Info|Warning|Error):", value, re.I):
            continue
        if value.startswith("screen-length") or re.fullmatch(r"\[[A-Z0-9]{6,}\]", value):
            continue
        out.append(line)
    return out


def clean_config_output(text, device=""):
    return "\n".join(line.strip() for line in _config_lines(text)
                     if line.strip() != "#" and line.strip().lower() != "return")


def config_commands(config_text):
    entries = []
    skip_block = False
    for raw in _config_lines(config_text):
        indentation = len(raw) - len(raw.lstrip(" \t"))
        indentation += raw[:indentation].count("\t") * 3
        value = raw.strip()
        if not value:
            continue
        if value == "#":
            entries.append(("break", None, None))
            skip_block = False
            continue
        if skip_block:
            continue
        if value.lower().startswith("user-interface "):
            skip_block = True
            continue
        if value.lower() in ("return", "quit", "system-view"):
            continue
        if RESTORE_SKIP_RE.match(value):
            continue
        try:
            value = clean_command(value)
        except ValueError:
            continue
        entries.append(("command", indentation, value))

    command_indents = [indent for kind, indent, _ in entries if kind == "command"]
    base_indent = min(command_indents) if command_indents else 0
    commands = []
    levels = []

    def close_levels():
        while levels:
            commands.append("quit")
            levels.pop()

    for index, (kind, indentation, value) in enumerate(entries):
        if kind == "break":
            close_levels()
            if commands and commands[-1] not in ("return", "system-view"):
                commands.extend(["return", "system-view"])
            continue
        indentation -= base_indent
        next_indent = None
        for next_index in range(index + 1, len(entries)):
            next_kind, next_value, _ = entries[next_index]
            if next_kind == "break":
                break
            next_indent = next_value - base_indent
            break
        is_view = value.lower() in EXACT_VIEW_HEADERS or bool(VIEW_HEADER_RE.match(value)) or (
            next_indent is not None and next_indent > indentation)
        if indentation == 0:
            close_levels()
        else:
            while levels and indentation <= levels[-1]:
                commands.append("quit")
                levels.pop()
        commands.append(value)
        if is_view:
            levels.append(indentation)
    return commands


def prepare_snapshot_config(configs):
    for values in configs.values():
        config = values.get("config") if isinstance(values, dict) else values
        commands = config_commands(config or "")
        if commands:
            values["commands"] = ["system-view"] + commands + ["return"]
    return configs
