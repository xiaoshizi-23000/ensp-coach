import json
import os
import re
import socket
import sys
import threading
import time
import webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import ai
import ailab
import doctor as doctor_mod
from ensp_kit import Vrp, build_topo

LABS_DIR = os.path.join(BASE, "labs")
KB_DIR = os.path.join(BASE, "kb")
GEN_DIR = os.path.join(BASE, "workspace", "generated")
WORK_DIR = os.path.join(BASE, "workspace")
WEB_DIR = os.path.join(BASE, "web")
os.makedirs(WORK_DIR, exist_ok=True)
os.makedirs(GEN_DIR, exist_ok=True)

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


def list_labs():
    out = []
    for folder, source in ((LABS_DIR, "classic"), (GEN_DIR, "ai")):
        if not os.path.isdir(folder):
            continue
        files = [f for f in os.listdir(folder) if f.endswith(".json")]
        files.sort(key=lambda f: -os.path.getmtime(os.path.join(folder, f)) if source == "ai" else f)
        for fn in files:
            try:
                lab = json.load(open(os.path.join(folder, fn), encoding="utf-8"))
            except Exception:
                continue
            if "id" not in lab or "steps" not in lab:
                continue
            out.append({
                "id": lab["id"],
                "title": lab["title"],
                "subtitle": lab.get("subtitle", ""),
                "level": lab.get("level", "入门"),
                "minutes": lab.get("minutes", 20),
                "tags": lab.get("tags", []),
                "steps": len(lab["steps"]),
                "source": lab.get("source", source),
                "verified": bool(lab.get("verified", {}).get("ok")),
                "syllabus": lab.get("syllabus", []),
            })
    return out


def get_lab(lab_id):
    for folder in (LABS_DIR, GEN_DIR):
        p = os.path.join(folder, lab_id + ".json")
        if os.path.exists(p):
            return json.load(open(p, encoding="utf-8"))
    return None


def public_lab(lab):
    d = dict(lab)
    d["steps"] = [
        {k: v for k, v in s.items() if k not in ("apply", "hints", "check")}
        | {"checks": len(s.get("check", []))}
        for s in lab["steps"]
    ]
    return d


def state_path(lab_id):
    return os.path.join(WORK_DIR, lab_id + ".state.json")


def progress_path(lab_id):
    return os.path.join(WORK_DIR, lab_id + ".progress.json")


GRADES = os.path.join(WORK_DIR, "grades.json")
EXAM = os.path.join(WORK_DIR, "exam.json")
PENALTY = {1: 0.05, 2: 0.12, 3: 0.22}


def bump(lab_id, sid, kind, level=0):
    p = read_json(progress_path(lab_id), {"done": [], "spent": {}})
    p.setdefault("spent", {}).setdefault(sid, {})
    s = p["spent"][sid]
    if kind == "hint":
        s["hint"] = max(s.get("hint", 0), level)
    else:
        s[kind] = True
    write_json(progress_path(lab_id), p)


def penalty_of(s):
    if s.get("apply"):
        return 1.0
    if s.get("answer"):
        return 0.45
    return PENALTY.get(s.get("hint", 0), 0)


def grade(lab):
    st = read_json(state_path(lab["id"]), None)
    if not st:
        return {"ok": False, "error": "还没搭环境，交不了卷"}
    if not any(probe(d["port"], 0.3) for d in st["devices"] if d["port"]):
        return {"ok": False, "error": "一台设备都没起来，先在 eNSP 里启动设备再交卷"}
    prog = read_json(progress_path(lab["id"]), {"done": [], "spent": {}})
    steps = lab["steps"]
    per = 100.0 / len(steps)
    rows = []
    total = 0.0
    for s in steps:
        r = run_checks(lab, s, record=False, source="grade")
        pen = penalty_of(prog.get("spent", {}).get(s["id"], {}))
        sc = round(per * (1 - pen), 1) if r["ok"] else 0.0
        total += sc
        rows.append({
            "id": s["id"], "title": s["title"], "full": round(per, 1), "score": sc,
            "pass": r["ok"], "penalty": round(pen * 100),
            "fails": [f"{x['dev']} {x['cmd']}" for x in r["results"] if not x["pass"]],
        })
    total = round(total, 1)
    res = {"ok": True, "score": total, "full": 100, "rows": rows, "at": time.time(),
           "grade": "A" if total >= 90 else "B" if total >= 75 else "C" if total >= 60 else "D",
           "passed": total >= 60}
    g = read_json(GRADES, {})
    g[lab["id"]] = {"score": total, "grade": res["grade"], "at": res["at"], "title": lab["title"]}
    write_json(GRADES, g)
    record_hist(lab["id"], [{"ts": res["at"], "type": "grade", "score": total, "title": lab["title"]}])
    return res


def exam_view():
    ex = read_json(EXAM, {"labs": []})
    grades = read_json(GRADES, {})
    items = []
    for lid in ex.get("labs", []):
        lab = get_lab(lid)
        if not lab:
            continue
        g = grades.get(lid)
        items.append({"id": lid, "title": lab["title"], "level": lab.get("level", ""),
                      "score": g["score"] if g else None, "grade": g["grade"] if g else None})
    got = [i for i in items if i["score"] is not None]
    return {"ok": True, "items": items, "count": len(items), "done": len(got),
            "score": round(sum(i["score"] for i in got), 1), "full": len(items) * 100}


def read_json(p, default):
    if not os.path.exists(p):
        return default
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


def write_json(p, obj):
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def _is_ensp_hwnd(hwnd):
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    k = ctypes.windll.kernel32
    k.OpenProcess.restype = wintypes.HANDLE
    k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                             wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    pid = wintypes.DWORD()
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = k.OpenProcess(0x1000, False, pid.value)
    if not h:
        return False
    try:
        n = wintypes.DWORD(512)
        b = ctypes.create_unicode_buffer(512)
        return bool(k.QueryFullProcessImageNameW(h, 0, b, ctypes.byref(n))) and \
            b.value.lower().endswith("ensp_client.exe")
    finally:
        k.CloseHandle(h)


def _root_at(pt):
    import ctypes
    u = ctypes.windll.user32
    h = u.WindowFromPoint(pt)
    if not h:
        return 0
    root = u.GetAncestor(h, 2)
    return root or h


def _visible_ensp_window():
    import ctypes
    u = ctypes.windll.user32
    w = _ensp_hwnd()
    if w and u.IsWindowVisible(w[0]) and not u.IsIconic(w[0]):
        return w
    return None


def _ensure_maximized(timeout=20):
    import ctypes
    u = ctypes.windll.user32
    scr_w = u.GetSystemMetrics(0)
    end = time.time() + timeout
    while time.time() < end:
        w = _ensp_hwnd()
        if w:
            hwnd, left, top, ww, hh = w
            if ww < scr_w - 200:
                u.ShowWindow(hwnd, 3)
                time.sleep(0.6)
                w2 = _ensp_hwnd()
                return w2 or w
            return w
        time.sleep(0.5)
    return None


def _ensp_running():
    return _ensp_hwnd() is not None


def _kill_ensp():
    import subprocess
    try:
        subprocess.run(["taskkill", "/IM", "eNSP_Client.exe", "/F"],
                       capture_output=True, timeout=10,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        time.sleep(2.5)
        return True
    except Exception:
        return False


def _push_cmds(port, cmds):
    c = Vrp("127.0.0.1", port, timeout=25)
    c.open()
    c.cmd("return", 6)
    c.cmd("screen-length 0 temporary", 6)
    for line in cmds:
        c.cmd(str(line).strip(), 20)
    c.close()


def inject_lab(lab):
    st = read_json(state_path(lab["id"]), None)
    if not st:
        return {"ok": False, "error": "还没搭环境"}
    base = lab.get("base") or {}
    inject = lab.get("inject") or {}
    if not base and not inject:
        return {"ok": True, "skipped": True}
    if st.get("injected"):
        return {"ok": True, "already": True}
    rep = []
    if base and not st.get("based"):
        for dev, cmds in base.items():
            port = st["ports"].get(dev)
            if not port or not probe(port, 0.3):
                rep.append({"dev": dev, "ok": False, "error": "设备没起来"})
                continue
            try:
                _push_cmds(port, cmds)
                rep.append({"dev": dev, "ok": True, "phase": "base"})
            except Exception as e:
                rep.append({"dev": dev, "ok": False, "error": str(e)})
        if not all(r["ok"] for r in rep):
            return {"ok": False, "report": rep}
        st["based"] = True
        write_json(state_path(lab["id"]), st)
        time.sleep(1)
    for dev, cmds in inject.items():
        port = st["ports"].get(dev)
        if not port or not probe(port, 0.3):
            rep.append({"dev": dev, "ok": False, "error": "设备没起来"})
            continue
        try:
            _push_cmds(port, cmds)
            rep.append({"dev": dev, "ok": True, "phase": "inject"})
        except Exception as e:
            rep.append({"dev": dev, "ok": False, "error": str(e)})
    if all(r["ok"] for r in rep):
        st["injected"] = True
        write_json(state_path(lab["id"]), st)
    return {"ok": all(r["ok"] for r in rep), "report": rep}


def build(lab):
    xml, devices = build_topo(lab)
    path = os.path.join(WORK_DIR, lab["id"] + ".topo")
    with open(path, "w", encoding="gb18030", newline="\r\n") as f:
        f.write(xml)
    ports = {d["name"]: d["com_port"] for d in devices}
    st = {
        "lab": lab["id"],
        "topo": path,
        "built_at": time.time(),
        "devices": [{"name": d["name"], "model": d["model"], "port": d["com_port"]} for d in devices],
        "ports": ports,
    }
    write_json(state_path(lab["id"]), st)
    opened = False
    if not os.environ.get("ENSP_LAB_NO_OPEN"):
        busy = [p for p in range(2000, 2011) if probe(p, 0.08)]
        if _ensp_running() and not busy:
            _kill_ensp()
        try:
            os.startfile(path)
            opened = True
        except Exception:
            pass
    return st, opened


def probe(port, timeout=0.5):
    if not port:
        return False
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def status(lab_id):
    st = read_json(state_path(lab_id), None)
    if not st:
        return {"built": False, "devices": []}
    devs = []
    for d in st["devices"]:
        devs.append(dict(d, up=probe(d["port"])))
    up = sum(1 for d in devs if d["up"])
    return {"built": True, "topo": st["topo"], "devices": devs, "up": up,
            "total": sum(1 for d in devs if d["port"])}


def console(port, cmds, ready_timeout=25):
    c = Vrp("127.0.0.1", port, timeout=ready_timeout)
    c.open()
    c.cmd("screen-length 0 temporary", 6)
    outs = []
    for cmd in cmds:
        outs.append((cmd, c.cmd(cmd, 30)))
    c.close()
    return outs


def hist_path(lab_id):
    return os.path.join(WORK_DIR, "hist", lab_id + ".json")


def record_hist(lab_id, entries):
    try:
        d = read_json(hist_path(lab_id), [])
        d.extend(entries)
        write_json(hist_path(lab_id), d[-400:])
    except Exception:
        pass


def run_checks(lab, step, record=True, source="check"):
    st = read_json(state_path(lab["id"]), None)
    if not st:
        return {"ok": False, "error": "环境还没搭，先点「一键搭建」"}
    if lab.get("mode") == "troubleshoot" and lab.get("inject") and not st.get("injected"):
        inject_lab(lab)
        st = read_json(state_path(lab["id"]), st) or st
    results = []
    cks = list(step.get("check", [])) + [dict(x, keep=True) for x in step.get("keep", [])]
    for ck in cks:
        port = st["ports"].get(ck["dev"])
        item = {"dev": ck["dev"], "cmd": ck["cmd"], "pass": False, "output": "",
                "keep": bool(ck.get("keep"))}
        if not port:
            item["message"] = f"{ck['dev']} 没有命令行口，只能在 eNSP 界面里操作"
            results.append(item)
            continue
        if not probe(port):
            item["message"] = f"{ck['dev']} 还没启动或 console 没起来"
            results.append(item)
            continue
        try:
            _, out = console(port, [ck["cmd"]], ck.get("timeout", 25))[0]
        except Exception as e:
            item["message"] = f"连接 {ck['dev']} 失败：{e}"
            results.append(item)
            continue
        item["output"] = out.strip()
        if "expect_any" in ck:
            item["pass"] = any(x in out for x in ck["expect_any"])
            item["message"] = "期望出现其中之一：" + " / ".join(ck["expect_any"])
        else:
            exp = ck["expect"] if isinstance(ck["expect"], list) else [ck["expect"]]
            missing = [x for x in exp if x not in out]
            item["pass"] = not missing
            item["message"] = "期望包含：" + " / ".join(exp) if missing else ""
        results.append(item)
    ok = all(r["pass"] for r in results)
    for r in results:
        if r.get("keep") and not r["pass"]:
            r["message"] = "原有业务被破坏了：" + (r.get("message") or r["cmd"])
    if source in ("check", "grade", "quiz"):
        ent = []
        ts = time.time()
        for r in results:
            if not r["pass"]:
                ent.append({"ts": ts, "type": "check", "step": step.get("id", ""),
                            "title": step.get("title", ""), "dev": r["dev"], "cmd": r["cmd"],
                            "out": (r.get("output") or r.get("message") or "")[-260:], "src": source})
        if ent:
            record_hist(lab["id"], ent)
    if ok and record:
        prog = read_json(progress_path(lab["id"]), {"done": []})
        if step["id"] not in prog["done"]:
            prog["done"].append(step["id"])
        write_json(progress_path(lab["id"]), prog)
    return {"ok": ok, "results": results}


def apply_step(lab, step):
    st = read_json(state_path(lab["id"]), None)
    if not st:
        return {"ok": False, "error": "环境还没搭"}
    plan = step.get("apply", {})
    report = []
    for dev, cmds in plan.items():
        port = st["ports"].get(dev)
        if not port or not probe(port):
            report.append({"dev": dev, "ok": False, "message": "设备没起来"})
            continue
        try:
            c = Vrp("127.0.0.1", port, timeout=25)
            c.open()
            c.cmd("return", 6)
            c.cmd("screen-length 0 temporary", 6)
            bad = []
            for line in cmds:
                out = c.cmd(line, 30)
                for ln in out.splitlines():
                    if re.search(r"Error:|Unrecognized command|Incomplete command|Wrong parameter", ln):
                        bad.append(f"{line} → {ln.strip()}")
            c.close()
            report.append({"dev": dev, "ok": not bad, "message": "" if not bad else "；".join(bad)})
        except Exception as e:
            report.append({"dev": dev, "ok": False, "message": str(e)})
    return {"ok": all(r["ok"] for r in report), "report": report}


def ai_apply(lab, step):
    st = read_json(state_path(lab["id"]), None)
    if not st:
        return {"ok": False, "error": "环境还没搭"}
    plan = step.get("apply", {})
    if not plan:
        return {"ok": False, "error": "这一步没有可执行的配置"}
    if not ai.ready():
        r = apply_step(lab, step)
        r["ai"] = False
        return r

    diff = diff_step(lab, step)
    snap = {}
    for dev in plan:
        port = st["ports"].get(dev)
        if port and probe(port, 0.3):
            try:
                _, text = console(port, ["display current-configuration"], 20)[0]
                snap[dev] = text[:3500]
            except Exception:
                pass

    prompt = f"""你是华为 VRP 设备的配置执行器。目标：让每台设备达到这一步要求的状态。

【这一步的标准配置】
{json.dumps(plan, ensure_ascii=False, indent=1)}

【程序比对出的差异（可信）】
{json.dumps([{k: v for k, v in r.items() if k in ("dev", "missing", "extra")} for r in diff.get("reports", []) if r.get("ok")], ensure_ascii=False, indent=1)}

【设备当前真实配置】
""" + "\n\n".join(f"--- {k} ---\n{v}" for k, v in snap.items()) + """

请输出 JSON：{"设备名": ["命令1", "命令2", ...]}
要求：
- 是把设备从当前状态推进到目标的最小命令序列，包含 system-view / quit 这类视图切换。
- 设备已经满足的配置不要再发一遍。
- 只允许配置类命令，禁止擦除配置、重启设备。
- 只输出 JSON，不要解释。"""

    r = ai.chat([{"role": "user", "content": prompt}],
                system="你是华为 VRP 配置执行器，只输出 JSON。", json_mode=True,
                temperature=0.2, timeout=180, max_tokens=4096)
    ai_plan = None
    if r.get("ok") and (r.get("content") or "").strip():
        try:
            txt = r["content"].strip()
            i, j = txt.find("{"), txt.rfind("}")
            cand = json.loads(txt[i:j + 1], strict=False)
            if isinstance(cand, dict) and cand:
                ai_plan = {d: [str(x) for x in v] for d, v in cand.items()
                           if isinstance(v, list) and d in plan and len(v) < 80}
        except Exception:
            ai_plan = None
    if not ai_plan:
        r2 = apply_step(lab, step)
        r2["ai"] = False
        r2["note"] = "AI 没给出可用方案，已按标准配置执行"
        return r2

    report = []
    for dev, cmds in ai_plan.items():
        port = st["ports"].get(dev)
        if not port or not probe(port, 0.3):
            report.append({"dev": dev, "ok": False, "message": "设备没起来", "cmds": cmds})
            continue
        try:
            c = Vrp("127.0.0.1", port, timeout=25)
            c.open()
            c.cmd("return", 6)
            c.cmd("screen-length 0 temporary", 6)
            bad = []
            for line in cmds:
                out = c.cmd(str(line).strip(), 30)
                for ln in out.splitlines():
                    if re.search(r"Error:|Unrecognized command|Incomplete command|Wrong parameter", ln):
                        bad.append(f"{line} → {ln.strip()}")
            c.close()
            report.append({"dev": dev, "ok": not bad, "message": "" if not bad else "；".join(bad),
                           "cmds": cmds})
        except Exception as e:
            report.append({"dev": dev, "ok": False, "message": str(e), "cmds": cmds})

    time.sleep(1)
    d2 = diff_step(lab, step)
    return {"ok": all(r["ok"] for r in report), "ai": True, "report": report, "diff": d2,
            "plan": ai_plan}


JOBS = {}


def prompt_ready(port, timeout=90):
    from ensp_kit import PROMPT
    end = time.time() + timeout
    while time.time() < end:
        if probe(port):
            try:
                c = Vrp("127.0.0.1", port, timeout=8)
                text = c.open()
                c.close()
                if PROMPT.search((text or "").strip()[-120:]):
                    return True
            except Exception:
                pass
        time.sleep(3)
    return False


def autoplay(lab_id):
    job = JOBS[lab_id]
    lab = get_lab(lab_id)
    try:
        st, opened = build(lab)
        ports = [d for d in st["devices"] if d["port"]]
        job["stage"] = "wait"
        job["total"] = len(ports)
        job["log"].append("拓扑已生成" + ("，eNSP 已打开，去点「启动」" if opened else f"，手动打开 {st['topo']}"))

        end = time.time() + 240
        while time.time() < end:
            job["ready"] = sum(1 for d in ports if probe(d["port"]))
            if job["ready"] == job["total"]:
                break
            time.sleep(3)
        if job["ready"] < job["total"]:
            job["state"] = "failed"
            job["error"] = f"等了 4 分钟，只有 {job['ready']}/{job['total']} 台设备起来"
            return

        job["log"].append("设备都起来了，等命令行就绪")
        for d in ports:
            if not prompt_ready(d["port"], 90):
                job["state"] = "failed"
                job["error"] = f"{d['name']} 的 console 一直没出提示符"
                return

        job["stage"] = "run"
        for i, step in enumerate(lab["steps"]):
            job["log"].append(f"第 {i+1} 步 · {step['title']}")
            ap = apply_step(lab, step)
            bad = [r for r in ap.get("report", []) if not r["ok"]]
            if bad:
                job["log"].append("  配置下发报错：" + "；".join(b["dev"] + " " + b["message"] for b in bad))
            time.sleep(1.5)
            r = run_checks(lab, step, record=False, source="autoplay")
            fails = [x for x in r["results"] if not x["pass"]]
            job["results"].append({"step": step["id"], "title": step["title"], "ok": r["ok"],
                                   "detail": [{"cmd": x["cmd"], "dev": x["dev"], "message": x["message"]} for x in fails]})
            if r["ok"]:
                job["log"].append("  通过")
            else:
                job["log"].append("  没过：" + "；".join(f"{x['dev']} {x['cmd']}" for x in fails))
                job["state"] = "failed"
                job["error"] = f"第 {i+1} 步「{step['title']}」的检查点没过"
                return

        lab["verified"] = {"at": time.time(), "ok": True}
        for folder in (LABS_DIR, GEN_DIR):
            p = os.path.join(folder, lab["id"] + ".json")
            if os.path.exists(p):
                write_json(p, lab)
                break
        job["state"] = "done"
        job["log"].append("全部通过，这个实验可以发给别人做了")
    except Exception as e:
        job["state"] = "failed"
        job["error"] = f"试跑中断：{e}"


def start_autoplay(lab_id):
    if JOBS.get(lab_id, {}).get("state") in ("running", "wait"):
        return JOBS[lab_id]
    JOBS[lab_id] = {"state": "running", "stage": "build", "log": [], "results": [],
                    "ready": 0, "total": 0, "error": ""}
    threading.Thread(target=autoplay, args=(lab_id,), daemon=True).start()
    return JOBS[lab_id]


def discover_ports(lab):
    st = read_json(state_path(lab["id"]), None)
    if not st:
        return {"ok": False, "error": "还没搭环境"}
    found = []
    for port in list(range(2000, 2100)):
        if not probe(port, 0.08):
            continue
        name = ""
        try:
            c = Vrp("127.0.0.1", port, timeout=5)
            c.open()
            c.cmd("screen-length 0 temporary", 4)
            out = c.cmd("display current-configuration | include sysname", 8)
            c.close()
            m = re.search(r"sysname\s+(\S+)", out)
            if m:
                name = m.group(1).strip()
        except Exception:
            pass
        found.append({"port": port, "name": name})

    console_names = [d["name"] for d in st["devices"] if d["port"]]
    changed = []
    for item in found:
        if item["name"] in console_names:
            old = st["ports"].get(item["name"])
            if old != item["port"]:
                st["ports"][item["name"]] = item["port"]
                changed.append(f"{item['name']} {old}→{item['port']}")
            else:
                changed.append(f"{item['name']} 没变({item['port']})")
    if changed:
        for d in st["devices"]:
            d["port"] = st["ports"].get(d["name"], d["port"])
        write_json(state_path(lab["id"]), st)
    return {"ok": True, "found": found, "changed": changed, "ports": st["ports"]}


def save_all(lab):
    st = read_json(state_path(lab["id"]), None)
    if not st:
        return {"ok": False, "error": "还没搭环境"}
    report = []
    for name, port in st["ports"].items():
        if not port or not probe(port):
            report.append({"dev": name, "ok": False, "message": "设备没起来"})
            continue
        try:
            c = Vrp("127.0.0.1", port, timeout=20)
            c.open()
            c.cmd("return", 6)
            out = c.cmd("save", 15)
            if re.search(r"\(y/n\)|\[Y/N\]", out):
                out += c.cmd("y", 25)
            if re.search(r"file name|文件名|\[vrpcfg", out, re.I):
                out += c.cmd("", 25)
            c.close()
            good = bool(re.search(r"successfully|成功|had been saved", out, re.I))
            report.append({"dev": name, "ok": good, "message": "" if good else out.strip()[-120:]})
        except Exception as e:
            report.append({"dev": name, "ok": False, "message": str(e)})
    return {"ok": all(r["ok"] for r in report), "report": report}


def mermaid(lab):
    ids = {}
    lines = ["flowchart LR"]
    for i, d in enumerate(lab["devices"]):
        key = "n%d" % i
        ids[d["name"]] = key
        lines.append(f'  {key}["{d["name"]}<br/><small>{d["model"]}</small>"]')
    for l in lab.get("links", []):
        a, b = ids.get(l["a"]), ids.get(l["b"])
        if a and b:
            lines.append(f'  {a} ---|{l.get("aPort", "")}| {b}')
    return "\n".join(lines)


def _ensp_hwnd(restore=False):
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    k = ctypes.windll.kernel32
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenProcess.restype = wintypes.HANDLE
    k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                             wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    k.QueryFullProcessImageNameW.restype = wintypes.BOOL
    k.CloseHandle.argtypes = [wintypes.HANDLE]

    cands = []

    def cb(hwnd, lp):
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        h = k.OpenProcess(0x1000, False, pid.value)
        if not h:
            return True
        try:
            size = wintypes.DWORD(512)
            buf = ctypes.create_unicode_buffer(512)
            if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                if buf.value.lower().endswith("ensp_client.exe"):
                    r = wintypes.RECT()
                    u.GetWindowRect(hwnd, ctypes.byref(r))
                    w, hh = r.right - r.left, r.bottom - r.top
                    vis = 2 if (u.IsWindowVisible(hwnd) and not u.IsIconic(hwnd)) else 0
                    cands.append((vis, w * hh, hwnd, r.left, r.top, w, hh))
        finally:
            k.CloseHandle(h)
        return True

    u.EnumWindows(ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(cb), 0)
    if not cands:
        return None
    vis_cands = [c for c in cands if c[0] > 0 and c[1] > 40000]
    pool = vis_cands or cands
    pool.sort(key=lambda c: (c[0], c[1]), reverse=True)
    _, _, hwnd, left, top, w, h = pool[0]

    if restore and (left <= -30000 or not u.IsWindowVisible(hwnd)):
        u.ShowWindow(hwnd, 9)
        u.ShowWindow(hwnd, 5)
        time.sleep(0.8)
        r = wintypes.RECT()
        u.GetWindowRect(hwnd, ctypes.byref(r))
        left, top, w, h = r.left, r.top, r.right - r.left, r.bottom - r.top
    return (hwnd, left, top, w, h)


def _cfg_path():
    return os.path.join(BASE, "config.json")


def _load_cfg():
    return read_json(_cfg_path(), {})


def calibrate_capture(wait=3):
    import ctypes
    from ctypes import wintypes
    time.sleep(max(0, wait))
    win = _ensp_hwnd(restore=True)
    if not win:
        return {"ok": False, "error": "没找到 eNSP 主窗口，先把它打开、不要最小化"}
    hwnd, left, top, w, h = win
    if left <= -30000:
        return {"ok": False, "error": "eNSP 还在最小化，先点任务栏把它还原再校准"}
    pt = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    dx, dy = pt.x - left, pt.y - top
    if not (0 <= dx <= w and 0 <= dy <= h):
        return {"ok": False, "error": f"鼠标不在 eNSP 窗口里（落在 {dx},{dy}），把指针放到启动按钮上再试",
                "window": [left, top, w, h]}
    cfg = _load_cfg()
    cfg["start_offset"] = [dx, dy]
    cfg["start_offset_at"] = time.time()
    write_json(_cfg_path(), cfg)
    return {"ok": True, "offset": [dx, dy], "window": [left, top, w, h]}


def _force_foreground(hwnd):
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    k = ctypes.windll.kernel32
    u.GetWindowThreadProcessId.restype = wintypes.DWORD
    u.GetForegroundWindow.restype = wintypes.HWND

    u.ShowWindow(hwnd, 9)
    time.sleep(0.2)

    tid_self = k.GetCurrentThreadId()
    fg = u.GetForegroundWindow()
    tid_fg = u.GetWindowThreadProcessId(fg, None) if fg else 0
    tid_target = u.GetWindowThreadProcessId(hwnd, None)

    attached = []
    for t in (tid_fg, tid_target):
        if t and t != tid_self and t not in attached:
            if u.AttachThreadInput(tid_self, t, True):
                attached.append(t)
    try:
        u.BringWindowToTop(hwnd)
        u.SetForegroundWindow(hwnd)
        u.SetActiveWindow(hwnd)
        u.SetFocus(hwnd)
    finally:
        for t in attached:
            u.AttachThreadInput(tid_self, t, False)

    if u.GetForegroundWindow() == hwnd:
        return True

    u.keybd_event(0x12, 0, 0, 0)
    u.keybd_event(0x12, 0, 2, 0)
    time.sleep(0.05)
    u.SetForegroundWindow(hwnd)
    return u.GetForegroundWindow() == hwnd


def _activate(hwnd):
    return _force_foreground(hwnd)


CALIB = {"state": "idle", "msg": "", "offset": None, "ready": 0, "total": 0}


def _calib_worker(timeout=90):
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    u.GetAsyncKeyState.restype = ctypes.c_short

    win = _ensp_hwnd()
    if not win:
        exe = os.path.join(doctor_mod.find_ensp() or "", "eNSP_Client.exe")
        if exe and os.path.exists(exe):
            try:
                os.startfile(exe)
                CALIB["msg"] = "eNSP 正在启动…"
                time.sleep(15)
            except Exception:
                pass
            win = _ensp_hwnd()
    if not win:
        CALIB.update(state="failed", msg="没找到 eNSP，先手动打开它，再点一次校准")
        return

    CALIB.update(state="armed", msg="点任务栏把 eNSP 切出来，然后在里面点一下启动按钮")

    end = time.time() + timeout
    pt = wintypes.POINT()
    prev = False
    while time.time() < end:
        down = bool(u.GetAsyncKeyState(0x01) & 0x8000)
        if down and not prev:
            u.GetCursorPos(ctypes.byref(pt))
            root = _root_at(pt)
            if not root or not _is_ensp_hwnd(root):
                CALIB["msg"] = "这一下点在 eNSP 外面了，再点一次里面的启动按钮"
                prev = down
                time.sleep(0.12)
                continue
            r = wintypes.RECT()
            u.GetWindowRect(root, ctypes.byref(r))
            left, top, w, h = r.left, r.top, r.right - r.left, r.bottom - r.top
            dx, dy = pt.x - left, pt.y - top
            if dy > 150:
                CALIB["msg"] = "这一下点在窗口下部，不像工具栏。再点一下顶部那排图标里的绿色三角"
                prev = down
                time.sleep(0.12)
                continue
            CALIB.update(state="testing", offset=[dx, dy],
                         msg=f"点到了 ({dx},{dy})，正在看设备起没起")
            break
        prev = down
        time.sleep(0.02)
    else:
        CALIB.update(state="failed", msg=f"{timeout} 秒内没点到 eNSP 里，重来一次")
        return

    st = current_state()
    ports = [d for d in st["devices"] if d["port"]] if st else []
    CALIB["total"] = len(ports)
    end = time.time() + 70
    while time.time() < end and ports:
        up = sum(1 for d in ports if probe(d["port"]))
        CALIB["ready"] = up
        if up == len(ports):
            break
        time.sleep(2)

    if ports and CALIB["ready"] == len(ports):
        cfg = _load_cfg()
        cfg["start_offset"] = CALIB["offset"]
        cfg["start_offset_rect"] = [w, h]
        cfg["start_offset_at"] = time.time()
        write_json(_cfg_path(), cfg)
        CALIB.update(state="done", msg=f"记下了，{len(ports)} 台设备已经起来")
    else:
        CALIB.update(state="failed",
                     msg=f"位置记下了但设备没起来（{CALIB['ready']}/{len(ports)}），可能是画布或别的按钮，再点一次真的启动按钮")


def arm_calibrate():
    if CALIB.get("state") in ("armed", "starting"):
        return CALIB
    CALIB.update({"state": "starting", "msg": "正在切到 eNSP", "offset": None,
                  "ready": 0, "total": 0})
    threading.Thread(target=_calib_worker, daemon=True).start()
    return CALIB


def _click_start(offset=None):
    import ctypes
    u = ctypes.windll.user32
    win = _visible_ensp_window() or _ensp_hwnd(restore=True)
    if not win:
        return {"ok": False, "error": "没找到 eNSP 主窗口"}
    hwnd, left, top, w, h = win
    if left <= -30000:
        return {"ok": False, "error": "eNSP 最小化了，先还原窗口再点启动"}
    if not offset:
        cfg = _load_cfg()
        offset = tuple(cfg.get("start_offset") or (659, 56))
        rect = cfg.get("start_offset_rect")
        if rect and (abs(rect[0] - w) > 24 or abs(rect[1] - h) > 24):
            return {"ok": False,
                    "error": f"eNSP 窗口大小变了（校准那次 {rect[0]}×{rect[1]}，现在 {w}×{h}），"
                             f"重新点一次「校准启动按钮」"}
    if not (0 <= int(offset[0]) <= w and 0 <= int(offset[1]) <= 150):
        return {"ok": False,
                "error": f"记下的位置 ({offset[0]},{offset[1]}) 不在当前窗口的工具栏上，"
                         f"重新点一次「校准启动按钮」"}
    dx, dy = int(offset[0]), int(offset[1])
    ok_fg = _activate(hwnd)
    time.sleep(0.3)
    x, y = left + dx, top + dy
    u.SetCursorPos(x, y)
    time.sleep(0.15)
    u.mouse_event(0x0002, 0, 0, 0, 0)
    u.mouse_event(0x0004, 0, 0, 0, 0)
    return {"ok": True, "clicked": [x, y], "offset": [dx, dy],
            "window": [left, top, w, h], "foreground": ok_fg}


def current_state():
    files = [f for f in os.listdir(WORK_DIR) if f.endswith(".state.json")]
    if not files:
        return None
    newest = max(files, key=lambda f: os.path.getmtime(os.path.join(WORK_DIR, f)))
    return read_json(os.path.join(WORK_DIR, newest), None)


def start_all_devices(lab_id=None, wait=True, click=False, timeout=150, offset=None):
    st = read_json(state_path(lab_id), None) if lab_id else current_state()
    if not st:
        return {"ok": False, "error": "环境还没搭，先建拓扑"}
    ports = [d for d in st["devices"] if d["port"]]
    out = {"clicked": None, "ready": 0, "total": len(ports)}
    if click:
        r = _click_start(offset)
        out["clicked"] = r
        if not r.get("ok"):
            return {"ok": False, "error": r.get("error"), **out}
    if not wait:
        out["ok"] = True
        out["note"] = "设备启动要几十秒，建议 wait=true 等到全部就绪"
        return out
    end = time.time() + timeout
    clicked_at = time.time()
    retried = False
    while time.time() < end:
        out["ready"] = sum(1 for d in ports if probe(d["port"]))
        if out["ready"] == out["total"]:
            out["ok"] = True
            lob = get_lab(lab_id) if lab_id else None
            if lob and lob.get("inject"):
                out["inject"] = inject_lab(lob)
            return out
        if click and not retried and out["ready"] == 0 and time.time() - clicked_at > 22:
            r2 = _click_start(offset)
            out["retry"] = r2
            retried = True
            clicked_at = time.time()
        time.sleep(2)
    out["ok"] = False
    out["error"] = f"{timeout} 秒内只有 {out['ready']}/{out['total']} 台起来，需要在 eNSP 里手动点「启动」"
    return out


def _find_browser():
    cands = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    return next((p for p in cands if os.path.exists(p)), "")


MINI_TITLE = "eNSP 陪练"
PORT = 7317


def _find_mini_hwnd():
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    found = []

    def cb(hwnd, lp):
        n = u.GetWindowTextLengthW(hwnd)
        b = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(hwnd, b, n + 1)
        if b.value == MINI_TITLE:
            r = wintypes.RECT()
            u.GetWindowRect(hwnd, ctypes.byref(r))
            found.append((hwnd, r.left, r.top, r.right - r.left, r.bottom - r.top))
        return True

    u.EnumWindows(ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(cb), 0)
    return found[-1] if found else None


def open_mini_window(port=7317):
    import ctypes
    from ctypes import wintypes
    exe = _find_browser()
    if not exe:
        return {"ok": False, "error": "没找到 Edge 或 Chrome，直接用浏览器开 /mini 也行"}

    win = _find_mini_hwnd()
    if win:
        u = ctypes.windll.user32
        u.ShowWindow(win[0], 9)
        u.SetWindowPos(win[0], -1, win[1], win[2], 430, 780, 0x0040)
        return {"ok": True, "reused": True}

    import subprocess
    import tempfile
    scr_w = ctypes.windll.user32.GetSystemMetrics(0)
    scr_h = ctypes.windll.user32.GetSystemMetrics(1)
    x = max(0, scr_w - 460)
    y = max(0, int(scr_h * 0.08))
    subprocess.Popen([exe, f"--app=http://127.0.0.1:{port}/mini",
                      "--window-size=430,780", f"--window-position={x},{y}",
                      "--user-data-dir=" + os.path.join(tempfile.gettempdir(), "ensp-mini-profile")])

    w = None
    for _ in range(30):
        time.sleep(0.4)
        w = _find_mini_hwnd()
        if w:
            break
    if not w:
        return {"ok": True, "reused": False, "note": "窗口已拉起，但没抓到手柄，没能钉在最前"}

    hwnd = w[0]
    ensp = _ensp_hwnd()
    if ensp and ensp[1] > -30000 and ensp[3] > 400:
        x = min(max(0, ensp[1] + ensp[3] - 440), max(0, scr_w - 440))
        y = max(0, ensp[2] + 40)

    u = ctypes.windll.user32
    u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                               ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    u.SetWindowPos.restype = wintypes.BOOL
    SWP = 0x0040 | 0x0010
    for _ in range(6):
        u.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(-1), x, y, 430, 780, SWP)
        time.sleep(0.35)
        if u.GetWindowLongW(hwnd, -20) & 0x8:
            break
    top = bool(u.GetWindowLongW(hwnd, -20) & 0x8)
    return {"ok": True, "reused": False, "topmost": top, "at": [x, y], "hwnd": hwnd}


def collect_snapshot(lab, limit=2200):
    st = read_json(state_path(lab["id"]), None)
    if not st:
        return {}
    out = {}
    for name, port in st["ports"].items():
        if not port or not probe(port, 0.3):
            continue
        try:
            _, cfg = console(port, ["display current-configuration"], 20)[0]
            out[name] = cfg.strip()[:limit]
        except Exception as e:
            out[name] = f"<读不到配置：{e}>"
    return out


def build_diag_prompt(lab, step, snap, diff=None):
    lines = [f"【实验】{lab['title']}：{lab['subtitle']}"]
    if step:
        idx = lab["steps"].index(step) + 1
        lines.append(f"【他正在做第 {idx}/{len(lab['steps'])} 步】{step['title']}")
        lines.append(f"【这一步的目标】{step['brief']}")
    if diff and diff.get("ok"):
        rows = []
        for rep in diff.get("reports", []):
            if not rep.get("ok"):
                continue
            if rep.get("missing"):
                rows.append(f"{rep['dev']} 缺：" + "；".join(rep["missing"][:6]))
            if rep.get("extra"):
                rows.append(f"{rep['dev']} 多出：" + "；".join(rep["extra"][:4]))
        if rows:
            lines.append("【程序比对出的配置差异（可信，直接参考）】\n" + "\n".join(rows))
    lines.append("【他所有设备当前的真实配置】")
    for name, cfg in snap.items():
        lines.append(f"--- {name} ---\n{cfg}")
    lines.append("请判断：他这一步做到哪了、还差什么、下一句该敲什么命令。"
                 "只说结论和下一步，不要复述他的配置，不要给整段答案。三到五句话。")
    return "\n\n".join(lines)


def diagnose(lab, step):
    if not ai.ready():
        return {"ok": False, "error": "还没配 DeepSeek 的 Key"}
    snap = collect_snapshot(lab)
    if not snap:
        return {"ok": False, "error": "设备都还没起来，先把 eNSP 里的设备启动起来"}
    d = None
    if step:
        try:
            d = diff_step(lab, step)
        except Exception:
            d = None
    r = ai.chat([{"role": "user", "content": build_diag_prompt(lab, step, snap, d)}],
                temperature=0.3, timeout=90)
    if not r.get("ok"):
        return r
    return {"ok": True, "content": r["content"], "read": list(snap.keys())}


def kb_all():
    out = []
    if not os.path.isdir(KB_DIR):
        return out
    for fn in os.listdir(KB_DIR):
        if not fn.endswith(".json"):
            continue
        try:
            out.append(json.load(open(os.path.join(KB_DIR, fn), encoding="utf-8")))
        except Exception:
            continue
    return out


def kb_list(q="", cat=""):
    items = []
    raw = (q or "").strip().lower()
    words = [w for w in raw.split() if w]
    for d in kb_all():
        if cat and d.get("cat") != cat:
            continue
        score = 0
        if words:
            title = str(d.get("title", "")).lower()
            keys = " ".join(d.get("keys", [])).lower()
            one = str(d.get("one", "")).lower()
            body = str(d.get("body", "")).lower()[:3000]
            hay = " ".join([title, one, d.get("id", ""), keys, body])
            if not all(w in hay for w in words):
                continue
            if raw in title:
                score += 100
            elif all(w in title for w in words):
                score += 70
            if all(w in keys for w in words):
                score += 50
            if all(w in one for w in words):
                score += 30
            score += 5
        items.append((score, {k: d.get(k, "" if k != "keys" else []) for k in
                              ("id", "title", "level", "cat", "one", "keys")}))
    order = {"HCIA": 0, "HCIP": 1, "HCIE": 2}
    items.sort(key=lambda x: (-x[0], order.get(x[1].get("level"), 9), x[1].get("title", "")))
    return [x[1] for x in items]


def kb_get(kid):
    return read_json(os.path.join(KB_DIR, kid + ".json"), None)


def kb_add(title, level="HCIA", cat="交换"):
    import hashlib
    import gen_kb
    title = (title or "").strip()
    if len(title) < 2:
        return {"ok": False, "error": "名字太短了"}
    for d in kb_all():
        if d.get("title") == title:
            return {"ok": False, "error": "库里已经有这条了", "id": d.get("id")}
    kid = "kb-" + hashlib.md5(title.encode("utf-8")).hexdigest()[:6]
    if os.path.exists(os.path.join(KB_DIR, kid + ".json")):
        return {"ok": False, "error": "已经存在同名的条目"}
    d, err = gen_kb.gen_one(kid, title, level, cat)
    if not d:
        return {"ok": False, "error": err or "生成失败"}
    write_json(os.path.join(KB_DIR, kid + ".json"), d)
    return {"ok": True, "id": kid, "title": d.get("title")}


NOISE = ("#", "!", "return", "quit", "undo shutdown", "screen-length", "user-interface",
         "authentication-mode", "idle-timeout", "protocol inbound")


def _mask_to_prefix(m):
    try:
        parts = [int(x) for x in m.split(".")]
        return sum(bin(p).count("1") for p in parts)
    except Exception:
        return None


def norm_line(line):
    s = " ".join(str(line).strip().split())
    low = s.lower()
    if low.startswith("ip address ") and " " in s[11:]:
        parts = s.split()
        if len(parts) >= 4:
            p = parts[3]
            if "." in p:
                pre = _mask_to_prefix(p)
                if pre is not None:
                    parts[3] = str(pre)
                    s = " ".join(parts)
    return s


def expected_from_apply(cmds):
    out = {"system": []}
    ctx = "system"
    for raw in cmds:
        c = str(raw).strip()
        if not c:
            continue
        low = c.lower()
        if low.startswith("system-view"):
            ctx = "system"
            continue
        if low.startswith("interface "):
            ctx = "if:" + c.split(None, 1)[1].strip()
            out.setdefault(ctx, [])
            continue
        if low in ("quit", "return"):
            if low == "return":
                ctx = "system"
            else:
                ctx = "system"
            continue
        if low.startswith("undo "):
            continue
        out.setdefault(ctx, []).append(norm_line(c))
    return {k: v for k, v in out.items() if v}


def parse_device_config(text):
    out = {"system": []}
    ctx = "system"
    for line in str(text).splitlines():
        s = line.rstrip()
        st = s.strip()
        if not st:
            continue
        if st == "#":
            ctx = "system"
            continue
        if st.lower().startswith("interface "):
            ctx = "if:" + st.split(None, 1)[1].strip()
            out.setdefault(ctx, [])
            continue
        if any(st.lower().startswith(n) for n in NOISE):
            continue
        out.setdefault(ctx, []).append(norm_line(st))
    return out


def diff_step(lab, step):
    st = read_json(state_path(lab["id"]), None)
    if not st:
        return {"ok": False, "error": "还没搭环境"}
    plan = step.get("apply") or {}
    if not plan:
        return {"ok": False, "error": "这一步没有标准配置可比"}
    reports = []
    for dev, cmds in plan.items():
        port = st["ports"].get(dev)
        if not port or not probe(port, 0.3):
            reports.append({"dev": dev, "ok": False, "error": "设备没起来"})
            continue
        try:
            _, text = console(port, ["display current-configuration"], 20)[0]
        except Exception as e:
            reports.append({"dev": dev, "ok": False, "error": str(e)})
            continue
        want = expected_from_apply(cmds)
        have = parse_device_config(text)
        have_all = {ln for v in have.values() for ln in v}
        batch_vlans = set()
        for ln in have_all:
            m2 = re.fullmatch(r"vlan batch (.+)", ln)
            if m2:
                batch_vlans.update(m2.group(1).split())
        missing, extra, hit = [], [], 0
        for ctx, lines in want.items():
            for ln in lines:
                mv = re.fullmatch(r"vlan (\d+)", ln)
                if mv and mv.group(1) in batch_vlans:
                    hit += 1
                    continue
                if ln in have_all:
                    hit += 1
                else:
                    where = "" if ctx == "system" else ctx.replace("if:", "") + " → "
                    missing.append(where + ln)
        touched = [c for c in want if c.startswith("if:")]
        for ctx in touched:
            allow = set(want.get(ctx, []))
            for ln in have.get(ctx, []):
                if ln in allow:
                    continue
                if any(ln.lower().startswith(n) for n in NOISE):
                    continue
                extra.append(ctx.replace("if:", "") + " → " + ln)
        reports.append({"dev": dev, "ok": True, "hit": hit, "total": sum(len(v) for v in want.values()),
                        "missing": missing, "extra": extra})
    return {"ok": True, "reports": reports}


QUIZ_DIR = os.path.join(BASE, "quiz")


def review_data():
    from collections import Counter
    hdir = os.path.join(WORK_DIR, "hist")
    lab_title = {l["id"]: l["title"] for l in list_labs()}
    checks, grades, quiz = [], [], []
    if os.path.isdir(hdir):
        for fn in os.listdir(hdir):
            if not fn.endswith(".json"):
                continue
            lid = fn[:-5]
            for e in read_json(os.path.join(hdir, fn), []):
                e = dict(e, lab=lid, labTitle=lab_title.get(lid, "排错速练" if lid == "quiz" else lid))
                if e.get("type") == "grade":
                    grades.append(e)
                elif e.get("type") == "quiz":
                    quiz.append(e)
                else:
                    checks.append(e)
    checks.sort(key=lambda x: -x.get("ts", 0))
    grades.sort(key=lambda x: -x.get("ts", 0))
    by_cmd = Counter(f"{e.get('dev','')} {e.get('cmd','')}" for e in checks)
    by_cat = Counter((lab_title.get(e.get("lab"), "") or e.get("lab", "")) for e in checks)
    scores = [g.get("score", 0) for g in grades]
    return {
        "ok": True,
        "attempts": len(grades),
        "avg": round(sum(scores) / len(scores), 1) if scores else None,
        "best": max(scores) if scores else None,
        "byCmd": [{"label": k, "n": v} for k, v in by_cmd.most_common(8)],
        "byCat": [{"label": k, "n": v} for k, v in by_cat.most_common(8)],
        "quiz": {"done": len(quiz), "wrong": sum(1 for q in quiz if q.get("out") != "对")},
        "recent": checks[:25],
    }


def quiz_all():
    out = []
    if not os.path.isdir(QUIZ_DIR):
        return out
    for fn in sorted(os.listdir(QUIZ_DIR)):
        if not fn.endswith(".json"):
            continue
        try:
            out.append(json.load(open(os.path.join(QUIZ_DIR, fn), encoding="utf-8")))
        except Exception:
            continue
    return out


def quiz_list(q="", cat="", level=""):
    words = [w for w in (q or "").lower().split() if w]
    items = []
    for d in quiz_all():
        if cat and d.get("cat") != cat:
            continue
        if level and d.get("level") != level:
            continue
        if words:
            hay = " ".join([str(d.get("title", "")), str(d.get("symptom", "")),
                            d.get("id", ""), " ".join(d.get("keys", []))]).lower()
            if not all(w in hay for w in words):
                continue
        items.append({k: d.get(k, "") for k in ("id", "title", "level", "cat", "symptom")})
    return items


def quiz_get(qid):
    p = os.path.join(QUIZ_DIR, qid + ".json")
    return read_json(p, None)


def quiz_answer(qid, choice):
    d = quiz_get(qid)
    if not d:
        return {"ok": False, "error": "没有这道题"}
    picked, correct = "", False
    for i, o in enumerate(d.get("options", [])):
        if str(i) == str(choice) or o.get("label") == choice:
            picked = o.get("label", "")
            correct = bool(o.get("ok"))
    record_hist("quiz", [{"ts": time.time(), "type": "quiz", "quiz": qid,
                          "title": d.get("title", ""), "dev": "quiz", "cmd": picked,
                          "out": "对" if correct else "错", "src": "quiz"}])
    return {"ok": True, "correct": correct, "explain": d.get("explain", "")}


def course_data(track=None):
    p = os.path.join(BASE, "course.json")
    if not os.path.exists(p):
        return {"ok": False, "error": "没有路线文件"}
    c = read_json(p, None)
    if not c:
        return {"ok": False, "error": "路线文件坏了"}
    courses = c.get("courses") if isinstance(c.get("courses"), list) else [c]
    cur = next((x for x in courses if track and x.get("id") == track), courses[0] if courses else None)
    if not cur:
        return {"ok": False, "error": "路线是空的"}
    grades = read_json(GRADES, {})
    hdir = os.path.join(WORK_DIR, "hist")
    quiz_hist = read_json(os.path.join(hdir, "quiz.json"), [])
    q_ok = {e.get("quiz") for e in quiz_hist if e.get("out") == "对"}
    stages = []
    for s in cur.get("stages", []):
        labs = []
        for lid in s.get("labs", []):
            lab = get_lab(lid)
            g = grades.get(lid)
            labs.append({
                "id": lid, "title": (lab or {}).get("title", lid),
                "score": g["score"] if g else None,
                "done": bool(g and g.get("score", 0) >= 60),
            })
        qids = s.get("quiz", [])
        q_done = sum(1 for qid in qids if qid in q_ok)
        stages.append({"name": s.get("name", ""), "syllabus": s.get("syllabus", ""),
                       "labs": labs, "quizTotal": len(qids),
                       "quizDone": q_done,
                       "done": all(l["done"] for l in labs) if labs else False})
    for i, s in enumerate(stages):
        s["unlocked"] = i == 0 or stages[i - 1]["done"]
    return {"ok": True, "title": cur.get("title", ""), "stages": stages,
            "tracks": [{"id": x.get("id"), "title": x.get("title")} for x in courses]}


class Handler(BaseHTTPRequestHandler):
    server_version = "ensp-lab/1.0"

    def log_message(self, fmt, *args):
        pass

    def send_json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self):
        path = urlparse(self.path).path
        m = re.fullmatch(r"/api/lab/([^/]+)", path)
        if m:
            lab = get_lab(m.group(1))
            if not lab:
                return self.send_json({"ok": False, "error": "没有这个实验"}, 404)
            return self.send_json({"ok": True, "lab": public_lab(lab),
                                   "progress": read_json(progress_path(lab["id"]), {"done": []})})
        if path == "/api/labs":
            return self.send_json({"ok": True, "labs": list_labs(),
                                   "ai": ai.ready(),
                                   "calibrated": bool(_load_cfg().get("start_offset"))})
        if path == "/api/exam":
            return self.send_json(exam_view())
        if path == "/manual.md":
            p = os.path.join(BASE, "使用手册.md")
            if not os.path.exists(p):
                return self.send_json({"ok": False, "error": "手册文件不在"}, 404)
            b = open(p, "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b)
            return

        if path.startswith("/api/kb"):
            u = urlparse(self.path)
            qs = parse_qs(u.query)
            m = re.fullmatch(r"/api/kb/([^/]+)", u.path)
            if m:
                d = kb_get(m.group(1))
                return self.send_json(d) if d else self.send_json({"ok": False, "error": "没有这条"}, 404)
            cats = sorted({d.get("cat", "") for d in kb_all() if d.get("cat")})
            return self.send_json({"ok": True, "cats": cats,
                                   "items": kb_list(qs.get("q", [""])[0], qs.get("cat", [""])[0])})

        if path == "/api/review":
            return self.send_json(review_data())

        if path == "/api/course":
            qs = parse_qs(urlparse(self.path).query)
            return self.send_json(course_data((qs.get("track") or [None])[0]))

        if path.startswith("/api/quiz"):
            u = urlparse(self.path)
            qs = parse_qs(u.query)
            m = re.fullmatch(r"/api/quiz/([^/]+)/answer", u.path)
            if m:
                return self.send_json(quiz_answer(m.group(1), (qs.get("choice") or [""])[0]))
            m = re.fullmatch(r"/api/quiz/([^/]+)", u.path)
            if m:
                d = quiz_get(m.group(1))
                return self.send_json(d) if d else self.send_json({"ok": False, "error": "没有这道题"}, 404)
            cats = sorted({d.get("cat", "") for d in quiz_all() if d.get("cat")})
            levels = sorted({d.get("level", "") for d in quiz_all() if d.get("level")})
            return self.send_json({"ok": True, "cats": cats, "levels": levels,
                                   "items": quiz_list(qs.get("q", [""])[0], qs.get("cat", [""])[0],
                                                      qs.get("level", [""])[0])})

        m = re.fullmatch(r"/api/lab/([^/]+)/status", path)
        if m:
            return self.send_json({"ok": True, **status(m.group(1))})
        m = re.fullmatch(r"/api/lab/([^/]+)/mermaid", path)
        if m:
            lab = get_lab(m.group(1))
            if not lab:
                return self.send_json({"ok": False, "error": "没有这个实验"}, 404)
            b = mermaid(lab).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
            return
        if path.startswith("/api/"):
            return self.send_json({"ok": False, "error": "no route"}, 404)
        return self.static(path)

    def do_POST(self):
        path = urlparse(self.path).path
        data = self.body()
        parts = path.strip("/").split("/")

        if path == "/api/chat":
            return self.handle_chat(data)

        if path == "/api/config":
            key = str(data.get("api_key") or "").strip()
            if not key:
                return self.send_json({"ok": False, "error": "Key 是空的"})
            cfg_path = os.path.join(BASE, "config.json")
            cfg = read_json(cfg_path, {})
            cfg["api_key"] = key
            write_json(cfg_path, cfg)
            return self.send_json({"ok": True, "ai": ai.ready()})

        if path == "/api/doctor":
            items = doctor_mod.check_all()
            return self.send_json({"ok": all(i["ok"] for i in items), "items": items})

        if path == "/api/calibrate/arm":
            return self.send_json({"ok": True, **arm_calibrate()})

        if path == "/api/calibrate/status":
            return self.send_json({"ok": True, **CALIB})

        if path == "/api/calibrate":
            return self.send_json(calibrate_capture(float(data.get("wait", 3))))

        if path == "/api/float":
            return self.send_json({"ok": True, **open_mini_window(PORT)})

        if path == "/api/kb/add":
            return self.send_json(kb_add(str(data.get("title") or ""),
                                         str(data.get("level") or "HCIA"),
                                         str(data.get("cat") or "交换")))

        m = re.fullmatch(r"/api/quiz/([^/]+)/answer", path)
        if m:
            qs = parse_qs(urlparse(self.path).query)
            choice = (qs.get("choice") or [str(data.get("choice", ""))])[0]
            return self.send_json(quiz_answer(m.group(1), choice))

        if path == "/api/exam":
            ids = [i for i in (data.get("lab_ids") or []) if get_lab(i)]
            write_json(EXAM, {"labs": ids, "at": time.time()})
            return self.send_json(exam_view())

        if path == "/api/lab/generate":
            brief = str(data.get("brief") or "").strip()
            if len(brief) < 4:
                return self.send_json({"ok": False, "error": "多说两句，比如「练链路聚合和 VLAN 互通」"})
            r = ailab.generate(brief)
            if not r.get("ok"):
                return self.send_json(r)
            lab = r["lab"]
            write_json(os.path.join(GEN_DIR, lab["id"] + ".json"), lab)
            return self.send_json({"ok": True, "id": lab["id"], "lab": public_lab(lab)})

        if len(parts) >= 3 and parts[0] == "api" and parts[1] == "lab":
            lab = get_lab(parts[2])
            if not lab:
                return self.send_json({"ok": False, "error": "没有这个实验"}, 404)
            action = parts[3] if len(parts) > 3 else ""
            if action == "build":
                st, opened = build(lab)
                return self.send_json({"ok": True, "opened": opened, **st})
            if action == "reset":
                try:
                    os.remove(state_path(lab["id"]))
                except FileNotFoundError:
                    pass
                if data.get("progress"):
                    try:
                        os.remove(progress_path(lab["id"]))
                    except FileNotFoundError:
                        pass
                return self.send_json({"ok": True})
            if action == "inject":
                return self.send_json(inject_lab(lab))
            if action == "start":
                return self.send_json({"ok": True, **start_all_devices(
                    lab_id=lab["id"], wait=data.get("wait", True),
                    click=data.get("click", False), timeout=int(data.get("timeout", 150)))})
            if action == "grade":
                return self.send_json(grade(lab))
            if action == "autoplay":
                if len(parts) > 4 and parts[4] == "status":
                    return self.send_json({"ok": True, **(JOBS.get(lab["id"]) or {"state": "idle"})})
                return self.send_json({"ok": True, **start_autoplay(lab["id"])})
            if action == "discover":
                return self.send_json(discover_ports(lab))
            if action == "save":
                return self.send_json(save_all(lab))
            if action == "delete":
                if lab.get("source") != "ai":
                    return self.send_json({"ok": False, "error": "经典实验不能删"})
                for p in (os.path.join(GEN_DIR, lab["id"] + ".json"), state_path(lab["id"]),
                          progress_path(lab["id"]), os.path.join(WORK_DIR, lab["id"] + ".topo")):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
                return self.send_json({"ok": True})
            if action == "step" and len(parts) >= 6:
                step = next((s for s in lab["steps"] if s["id"] == parts[4]), None)
                if not step:
                    return self.send_json({"ok": False, "error": "没有这一步"}, 404)
                if parts[5] == "diagnose":
                    return self.send_json(diagnose(lab, step))
                if parts[5] == "diff":
                    return self.send_json(diff_step(lab, step))
                if parts[5] == "check":
                    return self.send_json(run_checks(lab, step))
                if parts[5] == "hint":
                    level = max(1, min(3, int(data.get("level", 1))))
                    bump(lab["id"], step["id"], "hint", level)
                    hints = step.get("hints", [])
                    return self.send_json({"ok": True, "level": level,
                                           "hint": hints[level - 1] if len(hints) >= level else "",
                                           "total": len(hints)})
                if parts[5] == "answer":
                    bump(lab["id"], step["id"], "answer")
                    return self.send_json({"ok": True, "answer": step.get("apply", {})})
                if parts[5] == "apply":
                    bump(lab["id"], step["id"], "apply")
                    if (data.get("mode") or "") == "ai":
                        return self.send_json(ai_apply(lab, step))
                    r = apply_step(lab, step)
                    r["ai"] = False
                    return self.send_json(r)
        return self.send_json({"ok": False, "error": "no route"}, 404)

    def handle_chat(self, data):
        lab = get_lab(data.get("lab_id", ""))
        ctx = []
        if lab:
            step = next((s for s in lab["steps"] if s["id"] == data.get("step_id")), None)
            ctx.append(f"实验：{lab['title']}（{lab['subtitle']}）")
            ctx.append("设备：" + "、".join(f"{d['name']}({d['model']})" for d in lab["devices"]))
            if step:
                ctx.append(f"当前步骤 {step['id']}：{step['title']}")
                ctx.append(f"这一步要做的：{step['brief']}")
                if step.get("why"):
                    ctx.append("为什么这么做：" + step["why"])
                if step.get("apply"):
                    ctx.append("这一步的标准配置（做完后应该达成的命令）：\n" +
                               json.dumps(step["apply"], ensure_ascii=False))
                h3 = (step.get("hints") or [None, None, None])[2]
                if h3:
                    ctx.append("第三级提示里的完整命令：\n" + str(h3)[:800])
            st = read_json(state_path(lab["id"]), None)
            if st and st.get("devices"):
                snap = []
                for d in st["devices"]:
                    if not d.get("port") or not probe(d["port"], 0.3):
                        continue
                    try:
                        _, text = console(d["port"], ["display current-configuration"], 15)[0]
                        snap.append(f"--- {d['name']} 当前配置 ---\n" + text[:2200])
                    except Exception:
                        pass
                if snap:
                    ctx.append("他设备的当前真实配置：\n" + "\n".join(snap))
        if data.get("last_output"):
            ctx.append("他刚才跑检查命令拿到的回显：\n" + str(data["last_output"])[:1500])
        msgs = [{"role": "user", "content": "【当前进度】\n" + "\n".join(ctx)}]
        for h in (data.get("history") or [])[-6:]:
            if h.get("role") in ("user", "assistant") and h.get("content"):
                msgs.append({"role": h["role"], "content": str(h["content"])[:2000]})
        q = str(data.get("question") or "").strip()
        msgs.append({"role": "user", "content": q or "我卡在这一步了，帮我看看从哪下手。"})
        return self.send_json(ai.chat(msgs, timeout=120))

    def static(self, path):
        if path in ("/", ""):
            path = "/index.html"
        if path == "/mini":
            path = "/mini.html"
        if path == "/kb":
            path = "/kb.html"
        if path == "/quiz":
            path = "/quiz.html"
        if path == "/course":
            path = "/course.html"
        if path == "/help":
            path = "/help.html"
        fp = os.path.normpath(os.path.join(WEB_DIR, path.lstrip("/")))
        if not fp.startswith(WEB_DIR) or not os.path.exists(fp):
            self.send_error(404)
            return
        ext = os.path.splitext(fp)[1]
        with open(fp, "rb") as f:
            b = f.read()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(b)))
        if ext in (".html", ".js", ".css"):
            self.send_header("Cache-Control", "no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(b)


def main():
    global PORT
    base = int(os.environ.get("ENSP_LAB_PORT", "7317"))
    srv = None
    for p in range(base, base + 12):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", p), Handler)
            PORT = p
            break
        except OSError:
            continue
    if not srv:
        print(f"端口 {base}-{base+11} 都被占用了，换个端口再试")
        return
    print(f"网络实验陪练已启动： http://127.0.0.1:{PORT}")
    print("DeepSeek：" + ("已配置" if ai.ready() else "未配置（config.json 里填 api_key）"))
    try:
        with open(os.path.join(BASE, "app.pid"), "w") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass
    if not os.environ.get("ENSP_LAB_NO_OPEN"):
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
