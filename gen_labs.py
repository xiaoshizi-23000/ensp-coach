import json
import os
import re
import sys
import time

import ailab

BASE = os.path.dirname(os.path.abspath(__file__))
LABS = os.path.join(BASE, "labs")

TASKS = [
    ("vlanif-route", "三层交换机用 Vlanif 做 VLAN 间路由，两台接入交换机各划 VLAN 10 和 VLAN 20，PC 分属两个 VLAN，最后互 ping 通"),
    ("rstp", "三台交换机连成三角环网跑 RSTP，把 SW2 设成根桥，然后看端口角色是不是 ROOT 和 ALTERNATE"),
    ("link-agg", "两台交换机之间拉两条链路做 Eth-Trunk 手工模式，加成员口，验证成员口是 Selected、带宽叠加到 2G"),
    ("static-float", "两台路由器之间走主备两条路径，主用静态路由默认优先级，备用那条改 preference 80，主链路断开后备份自动生效"),
    ("ospf-multiarea", "三台路由器跑 OSPF，AR1 和 AR2 在 area 0，AR3 挂 area 1，看 AR3 能不能学到 area 0 的路由"),
    ("ospf-auth", "两台路由器 OSPF area 0 开启 MD5 认证，配完邻居能到 Full，故意写错密码邻居起不来"),
    ("acl-adv", "用高级 ACL 只允许 192.168.10.0/24 访问服务器 192.168.20.100 的 80 端口，其余拒绝，绑在接口入方向"),
    ("nat-easyip", "企业出口路由器用 Easy-IP 做源 NAT，让内网 192.168.10.0/24 能访问外网 202.100.1.2，验证地址被转换"),
    ("vrrp-gateway", "两台三层交换机做 VRRP，虚拟网关 192.168.10.254，SW1 主 SW2 备，验证主备切换和虚拟 MAC"),
    ("dhcp-relay", "AR1 做 DHCP 服务器给 192.168.10.0/24 分地址，AR2 做 DHCP 中继，PC 能拿到地址"),
    ("bgp-ebgp", "两台路由器建立 eBGP 邻居，AS 65001 和 AS 65002，互相通告自己的网段，验证 BGP 路由表和邻居状态 Established"),
    ("port-security", "交换机接 PC 的接口开端口安全，最大 MAC 数设 1，违规动作 err-down，验证换成别的 PC 后接口被关掉"),
    ("static-route", "两台路由器直连，配接口地址和静态路由，验证路由表和跨网段互通"),
    ("ospf-single", "三台路由器串成一条线跑单区域 OSPF，验证邻居 Full 和路由学习"),
    ("vlan-cross", "两台交换机跨交换机 VLAN 互通，接 PC，划 VLAN 10，Trunk 放行，验证跨交换机同 VLAN 能通"),
    ("mpls-ldp", "两台路由器直连开启 MPLS 和 LDP，验证 LDP 会话建立、LSP 标签转发表生成"),
    ("ipv6-dual", "两台路由器跑双栈，IPv4 用 OSPF、IPv6 用 OSPFv3，验证两个协议族都互通"),
    ("bgp-rr", "三台路由器跑 IBGP，先全互联再改成 R2 做路由反射器，验证客户端路由被反射"),
]


def main():
    only = sys.argv[1:] or None
    done = []
    for slug, brief in TASKS:
        if only and slug not in only:
            continue
        if os.path.exists(os.path.join(LABS, slug + ".json")):
            print(f"{slug}: 已存在，跳过")
            continue
        t = time.time()
        r = ailab.generate(brief)
        if not r.get("ok"):
            print(f"{slug}: 失败 {r.get('error')[:120]}")
            continue
        lab = r["lab"]
        lab["id"] = slug
        lab["source"] = "builtin"
        lab["brief"] = brief
        with open(os.path.join(LABS, slug + ".json"), "w", encoding="utf-8") as f:
            json.dump(lab, f, ensure_ascii=False, indent=2)
        devs = "、".join(f"{d['name']}({d['model']})" for d in lab["devices"])
        print(f"{slug}: OK {round(time.time()-t,1)}s | {lab['title']} | {devs} | {len(lab['steps'])}步")
        done.append(slug)
    print(f"\n完成 {len(done)} 个：{done}")


if __name__ == "__main__":
    main()
