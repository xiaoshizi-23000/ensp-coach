import json
import os
import socket
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(BASE, "config.json")

ENSP_HINTS = [
    r"C:\Program Files\Huawei\eNSP",
    r"C:\Program Files (x86)\Huawei\eNSP",
    r"D:\Program Files\Huawei\eNSP",
    r"D:\Huawei\eNSP",
    r"E:\Huawei\eNSP",
]
VBOX_HINTS = [
    r"C:\Program Files\Oracle\VirtualBox\VBoxManage.exe",
    r"C:\Program Files (x86)\Oracle\VirtualBox\VBoxManage.exe",
    r"D:\Program Files\Oracle\VirtualBox\VBoxManage.exe",
]


def _run(cmd, timeout=8):
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return ((p.stdout or b"") + (p.stderr or b"")).decode("gbk", "replace").strip()
    except Exception as e:
        return f"<{e}>"


def _cfg():
    try:
        return json.load(open(CONFIG, encoding="utf-8"))
    except Exception:
        return {}


def find_ensp():
    p = _cfg().get("ensp_path")
    if p and os.path.exists(os.path.join(p, "eNSP_Client.exe")):
        return p
    for p in ENSP_HINTS:
        if os.path.exists(os.path.join(p, "eNSP_Client.exe")):
            return p
    return ""


def find_vbox():
    p = _cfg().get("vbox_path")
    if p and os.path.exists(p):
        return p
    for p in VBOX_HINTS:
        if os.path.exists(p):
            return p
    return ""


def ports_busy(lo=2000, hi=2010):
    busy = []
    for p in range(lo, hi + 1):
        s = socket.socket()
        s.settimeout(0.12)
        try:
            s.connect(("127.0.0.1", p))
            busy.append(p)
        except OSError:
            pass
        finally:
            s.close()
    return busy


def check_all():
    items = []

    ensp = find_ensp()
    items.append({"name": "eNSP", "ok": bool(ensp), "value": ensp or "没找到",
                  "fix": "先装华为 eNSP。装在别的盘就把路径写进 config.json 的 ensp_path"})

    vbox = find_vbox()
    ver = _run([vbox, "--version"]) if vbox else ""
    if vbox and ver and not ver.startswith("5.2"):
        note = f"{ver}（eNSP 配套的是 5.2.x，6 以上 AR/USG 常起不来）"
    else:
        note = ver or ("没找到" if not vbox else "版本读不到")
    items.append({"name": "VirtualBox", "ok": bool(vbox) and ver.startswith("5.2"), "value": note,
                  "fix": "装 VirtualBox 5.2.44，或把 VBoxManage.exe 路径写进 config.json 的 vbox_path"})

    if vbox and ver.startswith("5.2"):
        drv = _run(["sc.exe", "query", "VBoxDrv"])
        sup = _run(["sc.exe", "query", "VBoxSup"])
        has_drv = "RUNNING" in drv
        has_sup = "RUNNING" in sup
        driver_ok = has_drv and not has_sup
        if driver_ok:
            driver_note = "VBoxDrv 5.2 驱动运行正常"
        elif has_sup:
            driver_note = "检测到 VBoxSup 驱动但 VBoxDrv 未运行（VirtualBox 5/7 驱动混装）"
        else:
            driver_note = "VBoxDrv 未运行"
        items.append({
            "name": "VBox 驱动",
            "ok": driver_ok,
            "value": driver_note,
            "fix": "备份 .topo 后卸载现有的 VirtualBox 5/7 驱动残留，重启，再安装 VirtualBox 5.2.44；"
                   "不要在现代 VirtualBox 上直接叠加安装旧版",
        })

    hyper = _run(["bcdedit", "/enum", "{current}"])
    on = "hypervisorlaunchtype" in hyper.lower() and "auto" in hyper.lower().split("hypervisorlaunchtype")[-1][:20]
    items.append({"name": "Hyper-V", "ok": not on, "value": "开着" if on else "关着",
                  "fix": "关掉 Hyper-V 和内核隔离，否则和 VirtualBox 抢 VT-x，AR 会报 raw-mode"})

    busy = ports_busy()
    items.append({"name": "console 端口", "ok": not busy, "value": f"被占用 {busy}" if busy else "2000-2010 空闲",
                  "fix": "关掉上次没退干净的 eNSP 设备，或重启"})

    return items


def main():
    items = check_all()
    print("=" * 56)
    print(" eNSP 实验环境自检")
    print("=" * 56)
    for it in items:
        print(f"[{'OK ' if it['ok'] else '!! '}] {it['name']:<12}{it['value']}")
        if not it["ok"]:
            print(f"      -> {it['fix']}")
    ok = all(i["ok"] for i in items)
    print("-" * 56)
    print("结论：" + ("环境可用，可以开始搭实验" if ok else "先处理上面标 !! 的项，否则设备起不来"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
