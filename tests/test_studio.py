import io
import json
import os
import tempfile
import unittest
import zipfile

import studio


BASE_DEVICES = [
    {"name": "R1", "model": "AR2220", "x": 100, "y": 100},
    {"name": "R2", "model": "AR2220", "x": 300, "y": 100},
    {"name": "PC1", "model": "PC", "x": 500, "y": 100,
     "ip": "192.168.10.10", "mask": "255.255.255.0", "gateway": "192.168.10.1"},
]


class TopologyTests(unittest.TestCase):
    def test_auto_assigns_ports(self):
        devices, links, errors = studio.validate_topology(
            BASE_DEVICES, [{"a": "R1", "b": "R2"}, {"a": "R2", "b": "PC1"}])
        self.assertEqual(errors, [])
        self.assertEqual(links[0]["aPort"], "GE0/0/0")
        self.assertEqual(links[0]["bPort"], "GE0/0/0")
        self.assertEqual(links[1]["aPort"], "GE0/0/1")
        self.assertEqual(links[1]["bPort"], "GE0/0/0")

    def test_rejects_duplicate_names_and_bad_pc(self):
        devices = BASE_DEVICES + [{"name": "R1", "model": "AR2220"}]
        devices[-2] = dict(devices[-2], ip="999.1.1.1")
        _, _, errors = studio.validate_topology(devices, [])
        self.assertTrue(any("重复" in item for item in errors))
        self.assertTrue(any("PC1" in item and "无效" in item for item in errors))

    def test_rejects_duplicate_link_and_self_link(self):
        _, _, errors = studio.validate_topology(
            BASE_DEVICES, [{"a": "R1", "b": "R2"}, {"a": "R2", "b": "R1"},
                           {"a": "R1", "b": "R1"}])
        self.assertTrue(any("重复" in item for item in errors))
        self.assertTrue(any("自身" in item for item in errors))


class SnapshotCommandTests(unittest.TestCase):
    CONFIG = """display current-configuration
#
sysname R1
#
interface GigabitEthernet0/0/0
 ip address 10.0.0.1 255.255.255.0
#
interface GigabitEthernet0/0/1
 shutdown
#
ospf 1 router-id 1.1.1.1
 area 0.0.0.0
  network 10.0.0.0 0.0.0.255
 area 1
  network 10.0.1.0 0.0.0.255
#
bgp 100
 ipv4-family unicast
  network 192.0.2.0 255.255.255.0
#
return
<R1>"""

    def test_rebuilds_view_stack_with_quit(self):
        commands = studio.config_commands(self.CONFIG)
        self.assertEqual(commands[0], "sysname R1")
        self.assertIn("interface GigabitEthernet0/0/0", commands)
        self.assertIn("quit", commands)
        self.assertEqual(commands[commands.index("ospf 1 router-id 1.1.1.1") + 1], "area 0.0.0.0")
        self.assertLess(commands.index("ip address 10.0.0.1 255.255.255.0"),
                        commands.index("quit"))
        self.assertIn("ipv4-family unicast", commands)
        self.assertNotIn("display current-configuration", commands)
        self.assertNotIn("<R1>", commands)
        self.assertIn("system-view", commands)
        self.assertLess(commands.index("sysname R1"), commands.index("return"))

    def test_handles_console_common_indent_and_unknown_view(self):
        config = """display current-configuration
#
 sysname Studio-R1
#
 firewall zone Local
  priority 15
#
 interface GigabitEthernet0/0/0
  ip address 10.0.12.1 255.255.255.0
#
 wlan ac
#
return
<Studio-R1>"""
        commands = studio.config_commands(config)
        self.assertEqual(commands[0], "sysname Studio-R1")
        zone = commands.index("firewall zone Local")
        self.assertEqual(commands[zone + 1], "priority 15")
        self.assertEqual(commands[zone + 2], "quit")
        self.assertIn("interface GigabitEthernet0/0/0", commands)
        self.assertIn("quit", commands)
        self.assertLess(commands.index("ip address 10.0.12.1 255.255.255.0"),
                        commands.index("wlan ac"))

    def test_filters_destructive_commands(self):
        commands = studio.config_commands(
            "#\nsysname R1\nreboot\nundo shutdown\nreset saved-configuration\n")
        self.assertIn("sysname R1", commands)
        self.assertIn("undo shutdown", commands)
        self.assertNotIn("reboot", commands)
        self.assertNotIn("reset saved-configuration", commands)

    def test_skips_management_login_blocks(self):
        config = """#
sysname R1
#
user-interface con 0
 authentication-mode password
 set authentication password cipher SECRET
#
user-interface vty 0 4
 authentication-mode aaa
#
interface GigabitEthernet0/0/0
 ip address 10.0.0.1 255.255.255.0
#
"""
        commands = studio.config_commands(config)
        self.assertIn("sysname R1", commands)
        self.assertNotIn("user-interface con 0", commands)
        self.assertNotIn("authentication-mode password", commands)
        self.assertNotIn("set authentication password cipher SECRET", commands)
        self.assertIn("interface GigabitEthernet0/0/0", commands)

    def test_restore_warning_classification(self):
        self.assertTrue(studio.restore_issue_is_warning(
            "priority 15", "priority 15 → Error: Wrong parameter"))
        self.assertTrue(studio.restore_issue_is_warning(
            "ip address 10.0.0.1 24", "Error: The address already exists."))
        self.assertFalse(studio.restore_issue_is_warning(
            "interface GigabitEthernet0/0/0", "Error: Unrecognized command"))

    def test_strips_terminal_control_sequences(self):
        commands = studio.config_commands(
            "display current-configuration\nsysname\x1b[42DR1\n<R1>")
        self.assertEqual(commands, ["sysnameR1"])


class SandboxTests(unittest.TestCase):
    def make_lab(self):
        return studio.build_sandbox_lab({
            "title": "测试沙箱",
            "subtitle": "两路由器",
            "devices": BASE_DEVICES[:2],
            "links": [{"a": "R1", "b": "R2"}],
        })

    def test_zip_roundtrip(self):
        lab = self.make_lab()
        data = studio.zip_bytes(lab, [])
        imported, snapshots = studio.read_import_package(data)
        self.assertEqual(snapshots, [])
        self.assertTrue(imported["id"].startswith("import-"))
        self.assertEqual(imported["title"], "测试沙箱")
        self.assertEqual(imported["links"][0]["aPort"], "GE0/0/0")
        self.assertTrue(imported["sandbox"])

    def test_rejects_path_traversal_in_zip(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("lab.json", json.dumps(self.make_lab(), ensure_ascii=False))
            zf.writestr("../evil.txt", "x")
        with self.assertRaises(ValueError):
            studio.read_import_package(buf.getvalue())

    def test_rejects_destructive_import_apply(self):
        lab = self.make_lab()
        lab["steps"][0]["apply"] = {"R1": ["reboot"]}
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("lab.json", json.dumps(lab, ensure_ascii=False))
        with self.assertRaises(ValueError):
            studio.read_import_package(buf.getvalue())

    def test_snapshot_lifecycle(self):
        lab = self.make_lab()
        config = "display current-configuration\n#\nsysname R1\n#\nreturn\n<R1>"
        with tempfile.TemporaryDirectory() as folder:
            item = studio.save_snapshot(folder, lab, {"R1": {"model": "AR2220", "config": config}},
                                        label="测试")
            items = studio.list_snapshots(folder, lab["id"])
            self.assertEqual(len(items), 1)
            loaded = studio.load_snapshot(folder, lab["id"], item["id"])
            self.assertEqual(loaded["label"], "测试")
            self.assertTrue(studio.delete_snapshot(folder, lab["id"], item["id"]))
            self.assertEqual(studio.list_snapshots(folder, lab["id"]), [])


if __name__ == "__main__":
    unittest.main()
