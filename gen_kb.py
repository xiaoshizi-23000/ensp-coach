import json
import os
import sys
import time

import ai

BASE = os.path.dirname(os.path.abspath(__file__))
KB = os.path.join(BASE, "kb")

SYSTEM = "你是华为认证讲师，写技术文档。只输出 JSON 对象，不要解释，不要代码围栏。"

SCHEMA = """{
  "id": "英文短横线 id",
  "title": "知识点中文名",
  "level": "HCIA 或 HCIP 或 HCIE",
  "cat": "路由 / 交换 / 广域 / 安全 / 高可用 / IPv6 / 自动化，选一个",
  "keys": ["关键字", "别名", "英文名"],
  "one": "一句话说清它是什么，30 字以内",
  "analogy": "形象总结。用一个生活里的东西打比方，让人一眼明白它是干什么的、为什么这么设计。2 到 4 句，口语化，不要术语堆砌。",
  "body": "原理详解，Markdown，不设字数上限。要把机制讲透：为什么需要它、怎么工作（报文格式/字段/状态机/计算过程，该具体就具体）、和相邻技术怎么分工、设计上做了哪些取舍。通常 1500 到 4000 字，机制复杂就继续写，不要为了控制长度省略。宁可写长讲透，也不要三言两语带过。可以有小标题、列表、表格，标题不超过三级。",
  "cmds": ["查看或验证用的 VRP 命令，2 到 5 条"],
  "pits": ["现场容易踩的坑或排错要点，3 到 5 条，每条 30 字以内"],
  "qa": [{"q": "面试或考试常问的问题", "a": "要点式回答，100 字以内"}],
  "syllabus": "对应华为认证考纲的条目，例如 HCIA-Datacom 3.2 或 HCIP-Datacom 可靠性技术，不确定就写级别"
}"""

TOPICS = [
    ("osi-model", "网络分层模型与数据封装", "HCIA", "交换"),
    ("tcp-handshake", "TCP 三次握手与四次挥手", "HCIA", "广域"),
    ("arp", "ARP 工作过程与免费 ARP", "HCIA", "交换"),
    ("dhcp", "DHCP 报文交互与中继原理", "HCIA", "路由"),
    ("vlan-principle", "VLAN 隔离原理与端口类型", "HCIA", "交换"),
    ("trunk", "Trunk 与 802.1Q 标签处理", "HCIA", "交换"),
    ("stp", "STP 生成树选举与收敛过程", "HCIA", "交换"),
    ("rstp", "RSTP 端口角色与快速收敛", "HCIP", "交换"),
    ("link-agg", "链路聚合原理与 LACP 模式", "HCIA", "交换"),
    ("static-route", "静态路由、递归查询与浮动路由", "HCIA", "路由"),
    ("ospf-basic", "OSPF 基础与邻居建立条件", "HCIA", "路由"),
    ("ospf-state", "OSPF 邻居状态机八个状态", "HCIP", "路由"),
    ("ospf-lsa", "OSPF LSA 类型与作用范围", "HCIP", "路由"),
    ("ospf-area", "OSPF 区域类型与特殊区域", "HCIP", "路由"),
    ("ospf-spf", "SPF 计算过程与路由优选", "HCIP", "路由"),
    ("acl", "ACL 匹配原理与通配符掩码", "HCIA", "安全"),
    ("nat", "NAT 类型与地址转换过程", "HCIA", "安全"),
    ("vrrp", "VRRP 主备选举与切换机制", "HCIA", "高可用"),
    ("bgp-basic", "BGP 邻居关系与状态机", "HCIP", "路由"),
    ("bgp-path", "BGP 选路原则十三条", "HCIP", "路由"),
    ("bgp-attr", "BGP 公认与可选属性详解", "HCIE", "路由"),
    ("route-policy", "路由策略与策略路由的区别", "HCIP", "路由"),
    ("isis", "IS-IS 分层结构与邻居建立", "HCIP", "路由"),
    ("ipv6-basic", "IPv6 地址结构与邻居发现", "HCIA", "IPv6"),
    ("ospfv3", "OSPFv3 与 OSPFv2 的差异", "HCIP", "IPv6"),
    ("qos", "QoS 服务模型与队列调度", "HCIP", "广域"),
    ("mpls", "MPLS 标签转发原理", "HCIP", "广域"),
    ("mpls-vpn", "MPLS VPN 架构与 RD/RT", "HCIE", "广域"),
    ("vxlan", "VXLAN 与 EVPN 原理", "HCIE", "交换"),
    ("stack", "堆叠与集群技术", "HCIP", "高可用"),
    ("mirror", "端口镜像与流量观测", "HCIA", "交换"),
    ("wlan", "WLAN 组网与 CAPWAP 隧道", "HCIA", "广域"),
    ("dhcp-snooping", "DHCP Snooping 与 IPSG", "HCIP", "安全"),
    ("port-security", "端口安全与 MAC 地址管理", "HCIA", "安全"),
    ("stp-protect", "BPDU 保护、根保护与环路保护", "HCIP", "交换"),
    ("super-vlan", "Super VLAN 与 MUX VLAN", "HCIP", "交换"),
    ("storm-control", "流量抑制与风暴控制", "HCIA", "交换"),
    ("route-table", "路由表结构与最长匹配", "HCIA", "路由"),
    ("troubleshoot", "网络故障排查方法论", "HCIE", "路由"),
    ("srv6", "SRv6 分段路由原理", "HCIE", "自动化"),
    ("vrp-basics", "VRP 命令行基础与配置管理", "HCIA", "交换"),
    ("data-forwarding", "数据转发流程与三层设备转发原理", "HCIA", "路由"),
    ("ethernet-switch", "以太网技术与交换机工作原理", "HCIA", "交换"),
    ("ipv4-subnet", "IPv4 地址分类与子网划分", "HCIA", "路由"),
    ("aaa", "AAA 认证授权计费原理", "HCIA", "安全"),
    ("telnet-ftp", "Telnet、FTP、TFTP 远程登录与文件传输", "HCIA", "安全"),
    ("ntp-dns-http", "NTP、DNS、HTTP 服务原理", "HCIA", "广域"),
    ("ppp", "PPP 与 PPPoE 原理及认证", "HCIA", "广域"),
    ("snmp", "SNMP 网络管理协议", "HCIA", "自动化"),
    ("mstp", "MSTP 多生成树与实例映射", "HCIP", "交换"),
    ("multicast-basic", "IP 组播基础与组播地址", "HCIP", "路由"),
    ("igmp", "IGMP 工作原理与版本差异", "HCIP", "路由"),
    ("pim", "PIM-DM 与 PIM-SM 组播路由", "HCIP", "路由"),
    ("bfd", "BFD 链路快速检测", "HCIP", "高可用"),
    ("vrf", "VRF 虚拟路由转发实例", "HCIP", "安全"),
    ("mqc", "MQC 与策略路由", "HCIP", "路由"),
    ("firewall", "华为防火墙与安全策略", "HCIP", "安全"),
]


def gen_one(tid, title, level, cat, thinking=True):
    prompt = f"""写一个华为认证知识库条目。

【知识点】{title}
【认证级别】{level}
【分类】{cat}
【id 必须是】{tid}

【输出结构】
{SCHEMA}

要求：
- 读者是已经在做这行的人，不要从"什么是网络"讲起，直接讲机制。
- 讲清"为什么这么设计"，而不只是"是什么"。涉及字段、报文、状态机的地方要具体到名字。
- analogy 是给基础不好的人看的，必须能让他"哦原来是这么回事"，用生活里的东西打比方。
- 不要为了控制长度省略内容。该长就长，讲不透就是没写完。
- 中文，术语保留英文原文。

只输出 JSON。"""
    r = ai.chat([{"role": "user", "content": prompt}], system=SYSTEM, json_mode=True,
                temperature=0.3, timeout=240, max_tokens=16384, thinking=thinking)
    if not (r.get("content") or "").strip():
        r = ai.chat([{"role": "user", "content": prompt + "\n\n上次输出为空。请直接输出 JSON 本体。"}],
                    system=SYSTEM, json_mode=False, temperature=0.3, timeout=240,
                    max_tokens=16384, thinking=False)
    if not r.get("ok"):
        return None, r.get("error", "")
    import re
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
    d["title"] = d.get("title") or title
    d["level"] = level
    d["cat"] = cat
    d.setdefault("keys", [])
    d.setdefault("cmds", [])
    d.setdefault("pits", [])
    d.setdefault("qa", [])
    d.setdefault("syllabus", f"{level}-Datacom")
    return d, ""


def run_one(tid, title, level, cat):
    p = os.path.join(KB, tid + ".json")
    if os.path.exists(p):
        return f"{tid}: 已存在"
    t = time.time()
    d, err = None, ""
    for i in range(4):
        d, err = gen_one(tid, title, level, cat)
        if d:
            break
        time.sleep(15 + i * 10)
    if not d:
        return f"{tid}: 失败 {err[:80]}"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    return f"{tid}: OK {round(time.time()-t,1)}s | {d['title']} | {len(d['body'])}字"


def main():
    os.makedirs(KB, exist_ok=True)
    only = set(sys.argv[1:]) or None
    from concurrent.futures import ThreadPoolExecutor, as_completed
    tasks = [(tid, title, level, cat) for tid, title, level, cat in TOPICS
             if not only or tid in only]
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(run_one, tid, title, level, cat) for tid, title, level, cat in tasks]
        for fut in as_completed(futs):
            print(fut.result(), flush=True)
    n = len([f for f in os.listdir(KB) if f.endswith(".json")])
    print(f"\n库内共 {n} 条")


if __name__ == "__main__":
    main()
