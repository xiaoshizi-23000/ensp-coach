import argparse
import json
import os
import re
import socket
import time
import uuid
import xml.sax.saxutils as sx

MODELS = {
    "AR1220": {
        "slots": [("slot17", 1, [("Ethernet", "GE", 2), ("Ethernet", "Ethernet", 8)])],
        "extra": "",
        "console": True,
    },
    "AR2220": {
        "slots": [("slot17", 1, [("Ethernet", "GE", 1), ("Ethernet", "GE", 2), ("Serial", "Serial", 2)])],
        "extra": '<slot isMainBoard="0" id="3" type="521" />',
        "console": True,
    },
    "S5700": {
        "slots": [("slot17", 1, [("Ethernet", "GE", 24)])],
        "extra": "",
        "console": True,
    },
    "S3700": {
        "slots": [("slot17", 1, [("Ethernet", "Ethernet", 22), ("Ethernet", "GE", 2)])],
        "extra": "",
        "console": True,
    },
    "PC": {
        "slots": [("slot17", 1, [("Ethernet", "GE", 1)])],
        "extra": "",
        "console": False,
    },
}


def port_index(model, name):
    n = name.strip().upper().replace("GIGABITETHERNET", "GE").replace("ETHERNET", "ETH")
    if model == "AR1220":
        if n in ("GE0/0", "GE0/0/0"):
            return 0
        if n in ("GE0/1", "GE0/0/1"):
            return 1
        m = re.fullmatch(r"ETH0/0/(\d+)", n)
        if m and int(m.group(1)) < 8:
            return 2 + int(m.group(1))
        m = re.fullmatch(r"SERIAL0/0/(\d+)", n)
        if m and int(m.group(1)) < 2:
            return 10 + int(m.group(1))
        raise ValueError(f"AR1220 没有接口 {name}")
    if model == "AR2220":
        if n in ("GE0/0", "GE0/0/0"):
            return 0
        if n in ("GE0/1", "GE0/0/1"):
            return 1
        if n in ("GE0/2", "GE0/0/2"):
            return 2
        m = re.fullmatch(r"SERIAL0/0/(\d+)", n)
        if m and int(m.group(1)) < 2:
            return 10 + int(m.group(1))
        raise ValueError(f"AR2220 没有接口 {name}")
    if model == "S5700":
        m = re.fullmatch(r"GE0/0/(\d+)", n)
        if m and 1 <= int(m.group(1)) <= 24:
            return int(m.group(1)) - 1
        raise ValueError(f"S5700 没有接口 {name}")
    if model == "S3700":
        m = re.fullmatch(r"ETH0/0/(\d+)", n)
        if m and 1 <= int(m.group(1)) <= 22:
            return int(m.group(1)) - 1
        m = re.fullmatch(r"GE0/0/(\d+)", n)
        if m and 1 <= int(m.group(1)) <= 2:
            return 22 + int(m.group(1)) - 1
        raise ValueError(f"S3700 没有接口 {name}")
    if model == "PC":
        return 0
    raise ValueError(f"暂不支持的型号 {model}")


def dev_xml(d, com_port):
    model = d["model"]
    spec = MODELS[model]
    name = d["name"]
    if model == "PC":
        h = sum(ord(c) for c in name * 7)
        mac = "54-89-98-{:02X}-{:02X}-{:02X}".format(h % 256, (h // 7) % 256, (h // 13) % 256)
        settings = (
            f" -simpc_ip {d.get('ip', '0.0.0.0')}  -simpc_mask {d.get('mask', '0.0.0.0')}"
            f"  -simpc_gateway {d.get('gateway', '0.0.0.0')}  -simpc_mac {d.get('mac', mac)}"
            "  -simpc_mc_dstip 0.0.0.0  -simpc_mc_dstmac 00-00-00-00-00-00"
            "  -simpc_dns1 0.0.0.0  -simpc_dns2 0.0.0.0  -simpc_ipv6 ::  -simpc_prefix 128"
            "  -simpc_gatewayv6 ::  -simpc_dhcp_state 0  -simpc_dhcpv6_state 0  -simpc_dns_auto_state 0 "
        )
    else:
        settings = ""
    cx, cy = d.get("x", 100), d.get("y", 100)
    body = []
    for slot_name, is_main, ifaces in spec["slots"]:
        parts = [f'<slot number="{slot_name}" isMainBoard="{is_main}">']
        for sztype, ifname, count in ifaces:
            parts.append(f'<interface sztype="{sztype}" interfacename="{ifname}" count="{count}" />')
        parts.append("</slot>")
        body.append("      " + "".join(parts) if len(parts) < 40 else "\n".join("      " + p for p in parts))
    if spec["extra"]:
        body.append("      " + spec["extra"])
    inner = "\n".join(body)
    return (
        f'    <dev id="{d["id"]}" name="{name}" model="{model}" settings="{sx.escape(settings, {chr(34): "&quot;"})}" '
        f'system_mac="" com_port="{com_port}" bootmode="0" cx="{cx}" cy="{cy}" '
        f'edit_left="{cx + 27}" edit_top="{cy + 54}">\n{inner}\n    </dev>'
    )


def layout(devices):
    cols = 4
    for i, d in enumerate(devices):
        d.setdefault("x", 160 + (i % cols) * 220)
        d.setdefault("y", 140 + (i // cols) * 180)


def build_topo(lab, base_port=2000):
    devices = []
    for d in lab["devices"]:
        devices.append(dict(d, id=str(uuid.uuid4()).upper()))
    layout(devices)
    by_name = {d["name"]: d for d in devices}
    for d in devices:
        d["com_port"] = 0
    port = base_port
    for d in devices:
        if MODELS[d["model"]]["console"]:
            d["com_port"] = port
            port += 1

    dev_block = "\n".join(dev_xml(d, d["com_port"]) for d in devices)

    lines = []
    grouped = {}
    for link in lab.get("links", []):
        a, b = by_name[link["a"]], by_name[link["b"]]
        si = link["aPort"] if isinstance(link["aPort"], int) else port_index(a["model"], link["aPort"])
        ti = link["bPort"] if isinstance(link["bPort"], int) else port_index(b["model"], link["bPort"])
        grouped.setdefault((a["id"], b["id"]), []).append((si, ti))
    for (aid, bid), pairs in grouped.items():
        a, b = next(d for d in devices if d["id"] == aid), next(d for d in devices if d["id"] == bid)
        body = "\n".join(
            f'      <interfacePair lineName="Copper" srcIndex="{si}" '
            f'srcBoundRectIsMoved="0" srcBoundRect_X="{a["x"] + 70}" srcBoundRect_Y="{a["y"]}" '
            f'srcOffset_X="0.000000" srcOffset_Y="0.000000" tarIndex="{ti}" '
            f'tarBoundRectIsMoved="1" tarBoundRect_X="{b["x"] - 70}" tarBoundRect_Y="{b["y"]}" '
            f'tarOffset_X="-25.000000" tarOffset_Y="0.000000" />'
            for si, ti in pairs
        )
        lines.append(f'    <line srcDeviceID="{aid}" destDeviceID="{bid}">\n{body}\n    </line>')
    line_block = "\n".join(lines)

    txt = []
    for i, tip in enumerate(lab.get("txttips", [])):
        x, y = tip.get("x", 100), tip.get("y", 60 + i * 20)
        txt.append(
            f'    <txttip left="{x}" top="{y}" right="{x + tip.get("w", 220)}" bottom="{y + 20}" '
            f'content="{sx.escape(tip["text"])}" fontname="Consolas" fontstyle="0" editsize="100" '
            f'txtcolor="-16777216" txtbkcolor="-1" charset="134" />'
        )
    txt_block = "\n".join(txt)

    xml = (
        '<?xml version="1.0" encoding="UNICODE" ?>\n'
        '<topo version="1.3.00.100">\n'
        "  <devices>\n"
        f"{dev_block}\n"
        "  </devices>\n"
        "  <lines>\n"
        f"{line_block}\n"
        "  </lines>\n"
        "  <shapes>\n"
        "  </shapes>\n"
        "  <txttips>\n"
        f"{txt_block}\n"
        "  </txttips>\n"
        "</topo>\n"
    )
    return xml, devices


PROMPT = re.compile(r"[<\[][^<>\r\n\[\]]{1,60}[>\]]\s*$")


def clean(raw):
    out, i = bytearray(), 0
    while i < len(raw):
        if raw[i] == 255 and i + 2 < len(raw):
            cmd = raw[i + 1]
            if cmd == 250:
                j = raw.find(b"\xff\xf0", i)
                i = (j + 2) if j != -1 else len(raw)
                continue
            if cmd >= 251:
                i += 3
                continue
        out.append(raw[i])
        i += 1
    return out.decode("gb18030", "replace")


class Vrp:
    def __init__(self, host="127.0.0.1", port=2000, timeout=180):
        self.host, self.port, self.timeout = host, port, timeout
        self.s = None
        self.buf = ""

    def open(self):
        self.s = socket.create_connection((self.host, self.port), timeout=5)
        self.s.sendall(b"\r")
        return self.read(self.timeout)

    def _drain(self):
        self.s.settimeout(0.15)
        try:
            while self.s.recv(4096):
                pass
        except (socket.timeout, OSError):
            pass
        self.buf = ""

    def read(self, timeout):
        end = time.time() + timeout
        idle = time.time()
        while time.time() < end:
            self.s.settimeout(min(0.25, max(0.05, end - time.time())))
            try:
                chunk = self.s.recv(4096)
            except socket.timeout:
                chunk = b""
            except OSError:
                break
            if chunk:
                self.buf += clean(chunk)
                idle = time.time()
                if "---- More ----" in self.buf:
                    self.s.sendall(b" ")
                    self.buf = self.buf.replace("---- More ----", "")
                continue
            tail = self.buf.rstrip()
            if tail and PROMPT.search(tail[-120:]):
                break
            if tail and time.time() - idle > 1.2:
                break
        text, self.buf = self.buf, ""
        return text

    def cmd(self, line, timeout=60):
        self._drain()
        self.s.sendall(line.encode("gb18030", "replace") + b"\r")
        return self.read(timeout)

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass


BAD = re.compile(r"(Error:|Unrecognized command|Incomplete command|Wrong parameter|Too many parameters|% )")


def push_device(dev, lines, host="127.0.0.1", wait=240):
    c = Vrp(host, dev["com_port"], timeout=wait)
    c.open()
    c.cmd("screen-length 0 temporary", 8)
    log, errs = [], []
    for line in lines:
        out = c.cmd(line, 30)
        log.append(out)
        for ln in out.splitlines():
            if BAD.search(ln):
                errs.append(f"{line} -> {ln.strip()}")
    c.close()
    return errs, "".join(log)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lab")
    ap.add_argument("action", choices=["gen", "push", "check", "all"])
    ap.add_argument("--out", default=".")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--encoding", default="gb18030")
    ap.add_argument("--port", type=int, default=2000)
    a = ap.parse_args()

    lab = json.load(open(a.lab, encoding="utf-8"))
    xml, devices = build_topo(lab, a.port)
    topo_path = os.path.join(a.out, lab["name"] + ".topo")

    if a.action in ("gen", "all"):
        with open(topo_path, "w", encoding=a.encoding, newline="\r\n") as f:
            f.write(xml)
        print(f"topo -> {topo_path}")
        for d in devices:
            print(f"  {d['name']:<8}{d['model']:<8}console={d['com_port'] or '-'}")

    if a.action == "gen":
        return

    if a.action == "all":
        input("在 eNSP 里打开上面的 .topo，等设备全部启动到命令行提示符后按回车...")

    report = {"lab": lab["name"], "devices": {}, "checks": []}
    for d in devices:
        cmds = lab.get("configs", {}).get(d["name"])
        if not cmds:
            continue
        print(f"[push] {d['name']} :{d['com_port']}")
        errs, _ = push_device(d, cmds, a.host)
        report["devices"][d["name"]] = errs
        print("   " + ("OK" if not errs else f"{len(errs)} errors"))
        for e in errs:
            print("   ! " + e)

    if a.action in ("check", "all"):
        for ck in lab.get("checks", []):
            d = next(x for x in devices if x["name"] == ck["dev"])
            c = Vrp(a.host, d["com_port"])
            c.open()
            c.cmd("screen-length 0 temporary", 8)
            out = c.cmd(ck["cmd"], ck.get("timeout", 60))
            c.close()
            ok = ck["expect"] in out
            report["checks"].append({"dev": ck["dev"], "cmd": ck["cmd"], "ok": ok, "expect": ck["expect"]})
            print(f"[{'PASS' if ok else 'FAIL'}] {ck['dev']} {ck['cmd']}")
            if not ok:
                print("   " + "\n   ".join(out.strip().splitlines()[-8:]))

    rp = os.path.join(a.out, lab["name"] + ".report.json")
    json.dump(report, open(rp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"report -> {rp}")


if __name__ == "__main__":
    main()
