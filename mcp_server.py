import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import ailab
import app
from ensp_kit import port_index

PROTO = "2024-11-05"
SERVER = {"name": "ensp-lab", "version": "1.0.0"}

TOOLS = []


def tool(name, desc, props=None, required=None):
    def deco(fn):
        TOOLS.append({
            "name": name,
            "description": desc,
            "inputSchema": {"type": "object", "properties": props or {}, "required": required or []},
            "fn": fn,
        })
        return fn
    return deco


def ok(obj):
    return {"content": [{"type": "text", "text": json.dumps(obj, ensure_ascii=False, indent=2)}]}


def err(msg):
    return {"content": [{"type": "text", "text": str(msg)}], "isError": True}


@tool("ensp_status", "看当前环境：eNSP 装没装、实验搭没搭、哪些设备的 console 口活着。开工前先调它。")
def t_status(_):
    st = app.read_json(os.path.join(app.WORK_DIR, "state.json"), None)
    labs = app.list_labs()
    out = {"labs": [{"id": l["id"], "title": l["title"], "steps": l["steps"], "source": l["source"]}
                    for l in labs]}
    cur = None
    for l in labs:
        s = app.status(l["id"])
        if s.get("built"):
            cur = {"lab": l["id"], **{k: s[k] for k in ("built", "up", "total", "topo")},
                   "devices": s["devices"]}
    out["current"] = cur
    out["deepseek"] = app.ai.ready()
    return ok(out)


@tool("ensp_list_labs", "列出所有实验（经典的 + AI 生成的），带 id、步数、是否试跑过。")
def t_labs(_):
    return ok([{"id": l["id"], "title": l["title"], "subtitle": l["subtitle"],
                "level": l["level"], "steps": l["steps"], "source": l["source"],
                "verified": l["verified"]} for l in app.list_labs()])


@tool("ensp_get_lab", "读一个实验的完整内容：设备、链路、每一步的目标和检查点。",
      {"lab_id": {"type": "string"}}, ["lab_id"])
def t_get(args):
    lab = app.get_lab(args["lab_id"])
    if not lab:
        return err("没有这个实验：" + args["lab_id"])
    return ok(app.public_lab(lab))


@tool("ensp_build_lab", "生成这个实验的 .topo 并打开 eNSP。控制台端口从 2000 起按顺序分配。",
      {"lab_id": {"type": "string"}}, ["lab_id"])
def t_build(args):
    lab = app.get_lab(args["lab_id"])
    if not lab:
        return err("没有这个实验")
    st, opened = app.build(lab)
    return ok({"topo": st["topo"], "opened": opened,
               "devices": [{"name": d["name"], "model": d["model"], "port": d["port"]} for d in st["devices"]],
               "next": "让用户在 eNSP 里点「启动」，或者调 ensp_start_devices"})


@tool("ensp_start_devices",
      "点 eNSP 工具栏的启动按钮，把所有设备启动起来，然后轮询控制台端口直到全部就绪。需要 eNSP 已经打开了拓扑。",
      {"wait": {"type": "boolean", "description": "是否等到所有端口都开（默认 true）"}})
def t_start(args):
    r = app.start_all_devices(wait=args.get("wait", True))
    return ok(r) if r.get("ok") else err(r.get("error"))


@tool("ensp_push_config", "给一台设备逐条下发配置，返回每条的报错行。",
      {"lab_id": {"type": "string"}, "device": {"type": "string"},
       "commands": {"type": "array", "items": {"type": "string"}}},
      ["lab_id", "device", "commands"])
def t_push(args):
    st = app.read_json(app.state_path(args["lab_id"]), None)
    if not st:
        return err("环境还没搭，先调 ensp_build_lab")
    port = st["ports"].get(args["device"])
    if not port:
        return err(f"{args['device']} 没有 console 口（PC 这类只能在界面里配）")
    step = {"apply": {args["device"]: args["commands"]}}
    r = app.apply_step({"id": args["lab_id"]}, step)
    return ok(r)


@tool("ensp_exec", "在某台设备上跑只读命令（display/ping/tracert），把回显原样返回。",
      {"lab_id": {"type": "string"}, "device": {"type": "string"}, "command": {"type": "string"}},
      ["lab_id", "device", "command"])
def t_exec(args):
    st = app.read_json(app.state_path(args["lab_id"]), None)
    if not st:
        return err("环境还没搭")
    port = st["ports"].get(args["device"])
    if not port:
        return err(f"{args['device']} 没有 console 口")
    try:
        _, out = app.console(port, [args["command"]])[0]
        return ok({"device": args["device"], "command": args["command"], "output": out.strip()})
    except Exception as e:
        return err(f"连不上 {args['device']}：{e}")


@tool("ensp_check_step", "跑一个步骤的检查点，返回每条断言过没过和原始回显。设备必须已经起来。",
      {"lab_id": {"type": "string"}, "step_id": {"type": "string"}}, ["lab_id", "step_id"])
def t_check(args):
    lab = app.get_lab(args["lab_id"])
    if not lab:
        return err("没有这个实验")
    step = next((s for s in lab["steps"] if s["id"] == args["step_id"]), None)
    if not step:
        return err("没有这一步：" + args["step_id"])
    return ok(app.run_checks(lab, step))


@tool("ensp_grade", "交卷判分。把整份实验的检查点重跑一遍，按提示/看答案/代做的扣分率算总分。",
      {"lab_id": {"type": "string"}}, ["lab_id"])
def t_grade(args):
    lab = app.get_lab(args["lab_id"])
    if not lab:
        return err("没有这个实验")
    return ok(app.grade(lab))


@tool("ensp_generate_lab",
      "用一句话描述要练的网络场景，让 DeepSeek 生成一个新实验包（拓扑 + 分步 + 检查点）。会做结构校验，不过自动重试三次。",
      {"brief": {"type": "string", "description": "例如：两台交换机做链路聚合，验证带宽叠加"}}, ["brief"])
def t_gen(args):
    r = ailab.generate(args["brief"])
    if not r.get("ok"):
        return err(r.get("error"))
    lab = r["lab"]
    app.write_json(os.path.join(app.GEN_DIR, lab["id"] + ".json"), lab)
    return ok({"id": lab["id"], "title": lab["title"], "devices": len(lab["devices"]),
               "steps": [s["title"] for s in lab["steps"]],
               "note": "还没试跑。建议先 ensp_build_lab + ensp_start_devices，再调 ensp_autoplay 验一遍"})


@tool("ensp_autoplay", "把实验从头到尾自己跑一遍：搭拓扑、启动设备、逐步下发并检查，全过才标成已试跑。",
      {"lab_id": {"type": "string"}}, ["lab_id"])
def t_auto(args):
    job = app.start_autoplay(args["lab_id"])
    return ok({"started": True, "hint": "用 ensp_autoplay_status 看进度", **job})


@tool("ensp_autoplay_status", "查试跑进度：阶段、日志、每步结果。",
      {"lab_id": {"type": "string"}}, ["lab_id"])
def t_auto_status(args):
    return ok(app.JOBS.get(args["lab_id"]) or {"state": "idle"})


@tool("ensp_topology", "读实验的拓扑结构（设备、型号、链路、接口）。纯文件操作，不用开 eNSP。",
      {"lab_id": {"type": "string"}}, ["lab_id"])
def t_topo(args):
    lab = app.get_lab(args["lab_id"])
    if not lab:
        return err("没有这个实验")
    return ok({"devices": [{"name": d["name"], "model": d["model"]} for d in lab["devices"]],
               "links": lab.get("links", []),
               "mermaid": app.mermaid(lab)})


@tool("ensp_validate", "校验一段实验 JSON 能不能用：型号、接口名、设备名、检查点、单行命令。返回错误清单。",
      {"lab": {"type": "object", "description": "实验包 JSON"}}, ["lab"])
def t_validate(args):
    lab, errs = ailab.validate(args["lab"])
    if errs:
        return ok({"ok": False, "errors": errs})
    return ok({"ok": True, "summary": {"devices": len(lab["devices"]), "steps": len(lab["steps"])}})


@tool("ensp_discover", "扫本机 2000-2100 的 console 口，连上去读 sysname，把端口和设备名重新对齐。",
      {"lab_id": {"type": "string"}}, ["lab_id"])
def t_discover(args):
    lab = app.get_lab(args["lab_id"])
    if not lab:
        return err("没有这个实验")
    return ok(app.discover_ports(lab))


def handle(req):
    method = req.get("method")
    rid = req.get("id")
    if method == "initialize":
        v = (req.get("params") or {}).get("protocolVersion") or PROTO
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": v,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER,
            "instructions": ("这是华为 eNSP 实验平台的操控接口。顺序：ensp_status 看环境 → ensp_list_labs 选实验 → "
                             "ensp_build_lab 生成拓扑 → 让用户点启动或调 ensp_start_devices → "
                             "检查用 ensp_check_step / ensp_exec，不靠猜。"
                             "PC 类设备没有 console，只能从路由器或交换机侧验证。"
                             "配置命令不要凭记忆写，先用 ensp_exec 看现有配置。")}}
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "tools": [{"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"]}
                      for t in TOOLS]}}
    if method == "tools/call":
        p = req.get("params") or {}
        t = next((x for x in TOOLS if x["name"] == p.get("name")), None)
        if not t:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "no such tool"}}
        try:
            return {"jsonrpc": "2.0", "id": rid, "result": t["fn"](p.get("arguments") or {})}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": rid, "result": err(f"{type(e).__name__}: {e}")}
    if rid is None:
        return None
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "unknown method " + str(method)}}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        resp = handle(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
