import json
import re
import uuid

import ai
from ensp_kit import MODELS, port_index

SYSTEM = "你是华为 eNSP 实验设计师。你只输出一个 JSON 对象，不要解释，不要 markdown 代码围栏。"

PORTS = {
    "AR1220": "GE0/0/0、GE0/0/1、Ethernet0/0/0 ~ Ethernet0/0/7",
    "AR2220": "GE0/0/0 ~ GE0/0/2、Serial0/0/0 ~ Serial0/0/1",
    "S5700": "GE0/0/1 ~ GE0/0/24（注意从 1 开始，没有 GE0/0/0）",
    "S3700": "Ethernet0/0/1 ~ Ethernet0/0/22、GE0/0/1 ~ GE0/0/2",
    "PC": "GE0/0/0",
}

SCHEMA = """{
  "title": "实验名，12 字以内",
  "subtitle": "一句话说清练什么",
  "level": "入门 或 进阶",
  "minutes": 25,
  "tags": ["VLAN", "Trunk"],
  "intro": "两句话，说清这个实验最终要他做到什么",
  "devices": [
    {"name": "SW1", "model": "S5700", "x": 300, "y": 300},
    {"name": "PC1", "model": "PC", "x": 100, "y": 300, "ip": "192.168.10.10", "mask": "255.255.255.0", "gateway": "192.168.10.1"}
  ],
  "links": [{"a": "PC1", "aPort": "GE0/0/0", "b": "SW1", "bPort": "GE0/0/1"}],
  "steps": [
    {
      "id": "s1",
      "title": "这一步做什么",
      "brief": "一两句，说清操作目标",
      "why": "一到两句，说清为什么必须这么做",
      "hints": [
        "第一层：只指方向，不给命令",
        "第二层：给思路和命令骨架",
        "第三层：完整命令，用 \\n 分行"
      ],
      "check": [
        {"dev": "SW1", "cmd": "display current-configuration | include sysname", "expect": "sysname SW1"}
      ],
      "apply": {"SW1": ["system-view", "sysname SW1", "return"]}
    }
  ]
}"""

EXAMPLE = """{
  "title": "静态路由入门",
  "subtitle": "两台路由器用一条静态路由互通",
  "level": "入门",
  "minutes": 15,
  "tags": ["静态路由"],
  "intro": "两台 AR1220 直连，各配接口地址后补一条静态路由，最后 ping 通对端。",
  "devices": [
    {"name": "AR1", "model": "AR1220", "x": 200, "y": 220},
    {"name": "AR2", "model": "AR1220", "x": 520, "y": 220}
  ],
  "links": [{"a": "AR1", "aPort": "GE0/0/0", "b": "AR2", "bPort": "GE0/0/0"}],
  "steps": [
    {
      "id": "s1",
      "title": "配两个互联接口地址",
      "brief": "AR1 的 GE0/0/0 配 10.0.12.1/24，AR2 的 GE0/0/0 配 10.0.12.2/24。",
      "why": "两台设备必须在同一网段才能直接通信，掩码 24 位在 VRP 里可以直接写 24。",
      "hints": [
        "先 system-view 进系统视图，再进接口视图配地址。",
        "interface GigabitEthernet0/0/0 进接口，ip address 10.0.12.1 24 配地址。",
        "AR1：\\nsystem-view\\ninterface GigabitEthernet0/0/0\\nip address 10.0.12.1 24\\nquit\\n\\nAR2 换成 10.0.12.2。"
      ],
      "check": [
        {"dev": "AR1", "cmd": "display ip interface brief", "expect": "10.0.12.1"},
        {"dev": "AR2", "cmd": "display ip interface brief", "expect": "10.0.12.2"}
      ],
      "apply": {
        "AR1": ["system-view", "interface GigabitEthernet0/0/0", "ip address 10.0.12.1 24", "quit", "return"],
        "AR2": ["system-view", "interface GigabitEthernet0/0/0", "ip address 10.0.12.2 24", "quit", "return"]
      }
    },
    {
      "id": "s2",
      "title": "验证互通",
      "brief": "从 AR1 ping 10.0.12.2，四包全通。",
      "why": "直连不需要路由，配好地址就应该通，不通说明接口地址配错了。",
      "hints": [
        "直接 ping 对端地址。-c 表示次数，VRP 的 -t 单位是毫秒，别乱加。",
        "ping -c 4 10.0.12.2",
        "ping -c 4 10.0.12.2"
      ],
      "check": [{"dev": "AR1", "cmd": "ping -c 4 10.0.12.2", "expect": "0.00% packet loss", "timeout": 40}],
      "apply": {"AR1": ["ping -c 4 10.0.12.2"]}
    }
  ]
}"""


def build_prompt(brief):
    ports = "\n".join(f"- {m}：{p}" for m, p in PORTS.items())
    return f"""按下面这句话设计一个华为 eNSP 实验，产出实验包 JSON。

【学员的原话】
{brief}

【输出结构】
{SCHEMA}

【可用型号和接口】
{ports}
只有这五种，不要编别的型号。

【学员是谁】
不是学生，是在岗的网络工程师，或者在备考华为认证（HCIA/HCIP-Datacom）的人。
所以：命令要符合工程习惯，接口要写 description，设备名按机房命名规范（如 SW-CORE-01 太长了就用 SW1/AR1）；
原理一句带过，重点讲"现场为什么这么做"；不要用教科书腔。

【硬规则】
1. 设备 2 到 6 台，步骤 6 到 10 步。每一步只做一件事，小步走：改主机名、配一个接口地址、划一个 VLAN 这种基础动作各自单独一步，不要一步塞进三件事。
   目标是给基础一般的人做，他每做完一步都应该能看到明确的结果。
2. 步骤必须递进：配置基础 → 单项功能 → 联调 → 验证。前面的步骤是后面步骤的前提。
3. check.expect 必须是设备回显里能原样出现的字符串。ping 成功写 "0.00% packet loss"，OSPF 邻居起来写 "Full"，改名写 "sysname AR1" 这种。不要写解释性文字。
4. apply 里每条都是单行命令，按顺序敲就能生效，最后一条用 return 回用户视图。
5. 主机名、接口名要和 devices 里的名字完全一致。交换机接口从 GE0/0/1 起，路由器从 GE0/0/0 起。
6. PC 不带命令行，所以 check 不要落在 PC 上，验证要从路由器或交换机发起 ping。
7. hints 必须三层：第一层只指方向，第二层给思路和骨架，第三层才是完整命令。第一层要说到点上，比如"你现在在用户视图，配置命令会被拒绝"。
8. 设备坐标 x 从 100 开始，横向间隔 250 左右，不要重叠。

【格式示例】
{EXAMPLE}

现在只输出这个实验的 JSON 本体。"""


def strip_fence(s):
    s = s.strip()
    m = re.search(r"```(?:json)?\s*(.+?)\s*```", s, re.S)
    if m:
        s = m.group(1)
    i, j = s.find("{"), s.rfind("}")
    if i > 0 or j < len(s) - 1:
        if i >= 0 and j > i:
            s = s[i:j + 1]
    return s


def validate(lab):
    e = []
    if not isinstance(lab, dict):
        return None, ["顶层不是 JSON 对象"]
    for k in ("title", "subtitle", "level", "minutes", "devices", "links", "steps"):
        if k not in lab:
            e.append(f"缺少字段 {k}")
    if e:
        return None, e

    devs = lab["devices"]
    if not isinstance(devs, list) or not (2 <= len(devs) <= 8):
        return None, ["devices 必须是 2 到 8 台设备的数组"]
    names = set()
    for d in devs:
        if not isinstance(d, dict) or "name" not in d or "model" not in d:
            e.append("有设备缺 name 或 model")
            continue
        if d["model"] not in MODELS:
            e.append(f"不支持的型号 {d['model']}")
        if d["name"] in names:
            e.append(f"设备名重复：{d['name']}")
        names.add(d["name"])
        if d["model"] == "PC":
            for k in ("ip", "mask", "gateway"):
                if not d.get(k):
                    e.append(f"PC {d['name']} 缺 {k}")

    links = lab.get("links") or []
    if not isinstance(links, list) or not links:
        e.append("至少要有一条链路")
        links = []
    for l in links:
        if not isinstance(l, dict):
            e.append(f"链路 {l!r} 不是对象，要写成 a/aPort/b/bPort")
            continue
        for side in ("a", "b"):
            if l.get(side) not in names:
                e.append(f"链路引用了不存在的设备 {l.get(side)}")
        for side, port in (("a", "aPort"), ("b", "bPort")):
            dev = next((d for d in devs if d.get("name") == l.get(side)), None)
            if not dev:
                continue
            try:
                port_index(dev["model"], l.get(port, ""))
            except Exception as ex:
                e.append(f"{dev['name']} 的接口 {l.get(port)} 不可用：{ex}")

    steps = lab.get("steps")
    lo, hi = (1, 6) if lab.get("mode") == "troubleshoot" else (4, 12)
    if not isinstance(steps, list) or not (lo <= len(steps) <= hi):
        e.append(f"steps 必须是 {lo} 到 {hi} 步的数组")
        steps = steps if isinstance(steps, list) else []
    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            e.append(f"第 {i+1} 步不是对象")
            continue
        s.setdefault("id", f"s{i+1}")
        for k in ("title", "brief"):
            if not s.get(k):
                e.append(f"第 {i+1} 步缺 {k}")
        h = s.get("hints")
        if not isinstance(h, list) or len(h) < 2:
            e.append(f"第 {i+1} 步 hints 至少要 2 条")
        ck = s.get("check")
        if not isinstance(ck, list) or not ck:
            e.append(f"第 {i+1} 步缺 check")
        else:
            for c in ck:
                if c.get("dev") not in names:
                    e.append(f"第 {i+1} 步 check 的设备 {c.get('dev')} 不存在")
                if not c.get("cmd"):
                    e.append(f"第 {i+1} 步 check 缺 cmd")
                if "expect" not in c and "expect_any" not in c:
                    e.append(f"第 {i+1} 步 check 缺 expect")
        ap = s.get("apply")
        if ap is not None:
            if not isinstance(ap, dict):
                e.append(f"第 {i+1} 步 apply 要是对象")
            else:
                for k2, v in ap.items():
                    if k2 not in names:
                        e.append(f"第 {i+1} 步 apply 的设备 {k2} 不存在")
                    if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v):
                        e.append(f"第 {i+1} 步 apply.{k2} 要是命令字符串数组")
    return lab, e[:10]


def finalize(lab):
    lab = dict(lab)
    lab["id"] = "ai-" + uuid.uuid4().hex[:6]
    lab["source"] = "ai"
    lab["intro"] = lab.get("intro", "")
    lab["tags"] = lab.get("tags", [])
    lab["txttips"] = lab.get("txttips", [])
    for i, d in enumerate(lab["devices"]):
        d.setdefault("x", 120 + i * 250)
        d.setdefault("y", 300)
    for i, s in enumerate(lab["steps"]):
        s["id"] = f"s{i+1}"
        s.setdefault("hints", [])
        s.setdefault("apply", {})
    return lab


def generate(brief):
    if not ai.ready():
        return {"ok": False, "error": "还没配 DeepSeek 的 API Key，配好再试。"}
    if not ai.cloud_allowed():
        return {"ok": False, "error": "当前是本地规则模式，生成实验需要先在助教设置中开启云端 AI。"}
    if ai.load_config().get("privacy") == "strict":
        return {"ok": False, "error": "严格脱敏会替换生成实验中的 IP 地址，请切换到标准脱敏后再生成。"}
    msgs = [{"role": "user", "content": build_prompt(brief)}]
    errors = []
    for _ in range(3):
        r = ai.chat(msgs, system=SYSTEM, json_mode=True, temperature=0.35, timeout=240, max_tokens=16384)
        if not r["ok"]:
            return r
        if not (r.get("content") or "").strip():
            r = ai.chat(msgs + [{"role": "user", "content": "上次输出为空。请直接输出 JSON 本体，不要思考过程。"}],
                        system=SYSTEM, json_mode=False, temperature=0.3, timeout=240, max_tokens=16384)
            if not r["ok"]:
                return r
        content = r.get("content") or ""
        if not content.strip():
            errors = ["模型两次都返回空内容"]
            continue
        if r.get("finish") == "length":
            msgs += [{"role": "assistant", "content": content},
                     {"role": "user", "content": "你上次的输出因为太长被截断了。把 hints 和 brief 精简一些，"
                      "重新输出完整 JSON。"}]
            errors = ["输出超长被截断"]
            continue
        raw = strip_fence(content)
        try:
            lab = json.loads(raw)
        except Exception as ex:
            msgs += [{"role": "assistant", "content": content},
                     {"role": "user", "content": f"这不是合法 JSON：{ex}。重新输出完整 JSON，不要别的文字。"}]
            errors = ["输出的不是合法 JSON"]
            continue
        lab, errs = validate(lab)
        if not errs:
            return {"ok": True, "lab": finalize(lab)}
        errors = errs
        msgs += [{"role": "assistant", "content": content},
                 {"role": "user", "content": "这个实验包有这些问题：\n- " + "\n- ".join(errs) + "\n修好后只输出完整 JSON。"}]
    return {"ok": False, "error": "生成了三次都没过校验：" + "；".join(errors[:5])}
