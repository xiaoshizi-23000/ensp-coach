import json
import os
import re
import sys
import time

import ai

BASE = os.path.dirname(os.path.abspath(__file__))
QUIZ = os.path.join(BASE, "quiz")

SYSTEM = "你是华为认证的排错考官。只输出 JSON 对象，不要解释，不要代码围栏。"

SCHEMA = """{
  "title": "题目名，12 字内",
  "level": "HCIA 或 HCIP",
  "cat": "路由 / 交换 / 安全 / 高可用 / 广域，选一个",
  "symptom": "故障现象，站在操作者角度，两句话以内，不要透露原因",
  "topology": "Mermaid flowchart 代码，画设备和关键链路，6 行以内",
  "shows": [
    {"dev": "R1", "cmd": "display ospf peer", "output": "这条命令的回显，要和故障自洽，10 行以内"}
  ],
  "options": [
    {"label": "R1 的 OSPF 区域 ID 和 R2 不一致", "ok": true},
    {"label": "R1 的接口地址掩码写错了", "ok": false},
    {"label": "R2 没有开启 OSPF", "ok": false},
    {"label": "两台设备的接口没有 up", "ok": false}
  ],
  "explain": "为什么是这个答案，以及怎么验证。100 字以内"
}"""

TASKS = [
    ("qz-ospf-area", "OSPF 邻居起不来", "HCIP", "路由",
     "两台路由器直连，接口地址正常，OSPF 邻居始终空白", "故障藏在 OSPF 区域配置上"),
    ("qz-trunk", "跨交换机同 VLAN 不通", "HCIA", "交换",
     "两台交换机互联，各自接一台 PC，同 VLAN 的 PC 互相 ping 不通，本交换机内通", "故障在互联口的 Trunk 放行列表"),
    ("qz-static-nh", "静态路由下一跳错", "HCIA", "路由",
     "三台路由器串联，PC1 ping 不通最右侧网段，中间网段都通", "故障在静态路由的下一跳地址"),
    ("qz-acl-dir", "ACL 挂反了方向", "HCIA", "安全",
     "在出口路由器上配了 ACL 想拦外网访问内网，结果内网全被拦，外网访问没拦住", "故障在 ACL 应用方向"),
    ("qz-nat-miss", "NAT 不生效", "HCIA", "安全",
     "内网 PC 配了 NAT 出网，但外网侧看不到转换记录，PC 出不去", "故障在 NAT 的地址池或匹配规则"),
    ("qz-vrrp-pri", "VRRP 主备都在备", "HCIP", "高可用",
     "两台交换机做 VRRP，PC 的网关是虚拟 IP，但主设备上的 vrrp 状态是 backup", "故障在 VRRP 优先级"),
    ("qz-dhcp-relay", "DHCP 拿不到地址", "HCIP", "路由",
     "DHCP 服务器在核心，接入侧中继配了，PC 一直拿不到地址", "故障在中继指向的服务器地址"),
    ("qz-stp-root", "根桥不在核心", "HCIP", "交换",
     "三层架构，根桥应该选核心交换机，但现在实际根桥在接入层", "故障在 STP 优先级设置"),
    ("qz-port-sec", "端口安全误伤", "HCIA", "安全",
     "接 PC 的口开了端口安全后，PC 刚开机就被接口 err-down", "故障在端口安全的违规动作配置"),
    ("qz-bgp-as", "eBGP 邻居 Idle", "HCIP", "路由",
     "两台路由器 eBGP 邻居停在 Idle，直连地址能 ping 通", "故障在 BGP 的 AS 号配置"),
    ("qz-trunk-vlan", "Trunk 没放行 VLAN", "HCIA", "交换",
     "新增 VLAN 30 后跨交换机不通，VLAN 10 还正常", "故障在 Trunk 允许列表"),
    ("qz-ospf-silent", "OSPF 被静默", "HCIP", "路由",
     "OSPF 邻居起不来，接口 UP、直连通，其他协议正常", "故障在接口被配置成了静默接口"),
    ("qz-route-filter", "路由被过滤", "HCIP", "路由",
     "BGP 学到了路由但没进路由表，邻居 Established", "故障在路由过滤策略"),
    ("qz-dhcp-snoop", "DHCP Snooping 拦了合法请求", "HCIP", "安全",
     "开了 DHCP Snooping 后，部分楼层拿不到地址", "故障在信任口设置"),
]


def gen_one(tid, title, level, cat, scene, hint):
    prompt = f"""出一道华为认证的排错选择题。

【题目】{title}
【级别】{level}
【分类】{cat}
【场景】{scene}
【考点提示】{hint}

【输出结构】
{SCHEMA}

【硬规则】
1. 恰好 4 个选项，有且只有 1 个 ok=true。错误选项要像真的——都是这个场景下常见但不对的猜测。
2. shows 给 2 到 3 条关键回显，回显必须和正确答案自洽：懂行的人看完这几条回显能推出正确选项。回显格式要像真设备，带缩进。
3. symptom 只描述现象，绝不透题。
4. topology 用 mermaid flowchart，节点写设备名和型号。
5. explain 讲清为什么是它，以及用哪条命令能一锤定音。

只输出 JSON。"""

    r = ai.chat([{"role": "user", "content": prompt}], system=SYSTEM, json_mode=True,
                temperature=0.4, timeout=180, max_tokens=8192)
    if not (r.get("content") or "").strip():
        r = ai.chat([{"role": "user", "content": prompt + "\n\n上次输出为空。请直接输出 JSON 本体。"}],
                    system=SYSTEM, json_mode=False, temperature=0.4, timeout=180, max_tokens=8192)
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
    d["title"] = title
    d["level"] = level
    d["cat"] = cat
    d.setdefault("shows", [])
    d.setdefault("options", [])
    d.setdefault("explain", "")
    return d, ""


def main():
    os.makedirs(QUIZ, exist_ok=True)
    only = set(sys.argv[1:]) or None
    ok = 0
    for tid, title, level, cat, scene, hint in TASKS:
        if only and tid not in only:
            continue
        p = os.path.join(QUIZ, tid + ".json")
        if os.path.exists(p):
            print(tid, "已存在")
            continue
        t = time.time()
        d, err = None, ""
        for _ in range(3):
            d, err = gen_one(tid, title, level, cat, scene, hint)
            if d:
                break
            time.sleep(1)
        if not d:
            print(tid, "失败", err[:90])
            continue
        opts = d.get("options", [])
        if (not isinstance(opts, list) or len(opts) != 4
                or sum(1 for o in opts if isinstance(o, dict) and o.get("ok")) != 1):
            print(tid, "选项校验不过，跳过")
            continue
        json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"{tid}: OK {round(time.time()-t,1)}s | {title} | {len(d.get('shows',[]))}条回显")
        ok += 1
    print(f"\n完成 {ok} 道")


if __name__ == "__main__":
    main()
