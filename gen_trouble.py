import json
import os
import re
import sys
import time

import ailab
import ai

BASE = os.path.dirname(os.path.abspath(__file__))
LABS = os.path.join(BASE, "labs")

SYSTEM = "你是华为认证实验设计师，专门出故障排查题。只输出 JSON 对象，不要解释，不要代码围栏。"

SCHEMA = """{
  "title": "排错：故障名，12 字内",
  "subtitle": "一句话说清这道题考什么",
  "level": "进阶",
  "minutes": 20,
  "tags": ["排错", "OSPF"],
  "mode": "troubleshoot",
  "symptom": "故障现象，站在使用者角度描述，比如 PC1 能 ping 通网关但 ping 不通 PC2。不要透露原因。",
  "intro": "两句话说明背景：这套网络本来应该是通的，现在出问题了。",
  "devices": [
    {"name": "SW1", "model": "S5700"},
    {"name": "PC1", "model": "PC", "ip": "192.168.10.10", "mask": "255.255.255.0", "gateway": "192.168.10.1"}
  ],
  "links": [
    {"a": "PC1", "aPort": "GE0/0/0", "b": "SW1", "bPort": "GE0/0/1"}
  ],
  "base": {"设备名": ["把网络配成完全正常的命令"]},
  "inject": {"设备名": ["制造故障的命令"]},
  "steps": [
    {
      "id": "s1",
      "title": "定位并修复",
      "brief": "先看现象、缩小范围、查配置和协议状态，把故障点找出来改回去。",
      "why": "排错不是猜，是按层次缩小范围。",
      "hints": ["第一层只给排查方向", "第二层给具体该看什么", "第三层给出修复命令"],
      "check": [{"dev": "SW1", "cmd": "display current-configuration interface GigabitEthernet0/0/1", "expect": "port default vlan 10"}],
      "keep": [{"dev": "SW1", "cmd": "ping -c 2 192.168.10.20", "expect": "0.00% packet loss"}],
      "apply": {"设备名": ["修复用的命令"]}
    }
  ]
}"""

TASKS = [
    ("tr-vlan", "故障排查：PC 划错 VLAN",
     "两台交换机接两台 PC，同网段。PC1 能 ping 通自己的网关以外的同网段 PC2 却不通，故障在接入层某个口的 VLAN 划分上。"),
    ("tr-route", "故障排查：静态路由下一跳写错",
     "两台路由器串一台 PC 和另一台 PC（PC2 当服务器）。PC1 能 ping 通本地网关但 ping 不通 PC2 的网段，故障在静态路由的下一跳。"),
    ("tr-ospf", "故障排查：OSPF 邻居起不来",
     "两台路由器直连跑 OSPF，接口地址都没问题，但邻居一直起不来，故障在 OSPF 的区域 ID 或网络类型上。"),
]


def gen_one(tid, title, brief):
    prompt = f"""设计一道华为 eNSP 排错题。

【题目】{title}
【场景】{brief}

【输出结构】
{SCHEMA}

【硬规则】
1. mode 必须是 troubleshoot。设备 2 到 4 台。
1.5 devices 必须带 model 字段（PC 的 model 就是 PC）；links 必须用 a/aPort/b/bPort 四个字段，不要写成 from/to/port。
2. base 是"完全正常"的完整配置，逐步下发就能让全网互通；inject 是只在其中一台设备上改一处，制造单一故障。
3. inject 只能改一处，不要叠加多个故障。
4. symptom 写现象，不写原因。比如"PC1 ping 不通 192.168.20.10"，不要写"因为 VLAN 划错了"。
5. steps 只要 1 步，就是"定位并修复"。
6. check 是修复后应该成立的断言（回读配置或 ping 通）；keep 是修复后不能被破坏的原有业务，至少 1 条。
7. hints 三层：第一层给排查方向（先看什么），第二层给定位方法（看哪台设备哪条命令），第三层才是修复命令。
8. apply 是修复用的命令，和 inject 正好相反。
9. 交换机接口从 GE0/0/1 起，路由器从 GE0/0/0 起。PC 要有 ip/mask/gateway。

只输出 JSON。"""

    r = ai.chat([{"role": "user", "content": prompt}], system=SYSTEM, json_mode=True,
                temperature=0.35, timeout=180, max_tokens=8192)
    if not (r.get("content") or "").strip():
        r = ai.chat([{"role": "user", "content": prompt + "\n\n上次输出为空。请直接输出 JSON 本体。"}],
                    system=SYSTEM, json_mode=False, temperature=0.35, timeout=180, max_tokens=8192)
    if not r.get("ok"):
        return None, r.get("error", "")
    txt = r["content"].strip()
    m = re.search(r"```(?:json)?\s*(.+?)\s*```", txt, re.S)
    if m:
        txt = m.group(1)
    i, j = txt.find("{"), txt.rfind("}")
    if i >= 0 and j > i:
        txt = txt[i:j + 1]
    try:
        d = json.loads(txt, strict=False)
    except Exception as e:
        return None, f"JSON 解析失败 {e}"
    d["id"] = tid
    d["source"] = "builtin"
    d["mode"] = "troubleshoot"
    d.setdefault("txttips", [])
    for s in d.get("steps", []):
        s.setdefault("hints", [])
        s.setdefault("apply", {})
    return d, ""


def main():
    only = set(sys.argv[1:]) or None
    for tid, title, brief in TASKS:
        if only and tid not in only:
            continue
        p = os.path.join(LABS, tid + ".json")
        if os.path.exists(p):
            print(tid, "已存在")
            continue
        t = time.time()
        d, err = gen_one(tid, title, brief)
        if not d:
            print(tid, "失败", err[:100])
            continue
        lab, errs = ailab.validate(d)
        if errs:
            print(tid, "校验不过:", errs[:3])
            continue
        json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"{tid}: OK {round(time.time()-t,1)}s | {d['title']} | 现象：{d.get('symptom','')[:40]}")


if __name__ == "__main__":
    main()
