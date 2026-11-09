import unittest

from vrp_config import build_expected, compare_config, parse_config


class ConfigDiffTests(unittest.TestCase):
    def check(self, apply, actual):
        return compare_config(build_expected(apply), parse_config(actual))

    def test_ospf_area_uses_nested_view(self):
        result = self.check(
            ["system-view", "ospf 1", "area 0", "network 10.0.12.0 0.0.0.255", "quit", "quit"],
            """#
ospf 1 router-id 1.1.1.1
 area 0.0.0.1
  network 10.0.12.0 0.0.0.255
#
return
""",
        )
        self.assertEqual(result["hit"], 0)
        self.assertTrue(any("network 10.0.12.0" in item for item in result["missing"]))

    def test_ospf_dotted_area_is_equivalent(self):
        result = self.check(
            ["ospf 1", "area 0", "network 10.0.12.0 0.0.0.255"],
            """#
ospf 1 router-id 1.1.1.1
 area 0.0.0.0
  network 10.0.12.0 0.0.0.255
#
return
""",
        )
        self.assertEqual(result["missing"], [])

    def test_command_on_another_interface_does_not_match(self):
        result = self.check(
            ["interface GigabitEthernet0/0/1", "ip address 192.0.2.1 24"],
            """#
interface GigabitEthernet0/0/2
 ip address 192.0.2.1 255.255.255.0
#
return
""",
        )
        self.assertTrue(any("ip address 192.0.2.1 24" in item for item in result["missing"]))

    def test_interface_abbreviation_and_mask_are_normalized(self):
        result = self.check(
            ["interface GE0/0/1", "ip address 192.0.2.1 255.255.255.0"],
            """#
interface GigabitEthernet0/0/1
 ip address 192.0.2.1 24
#
return
""",
        )
        self.assertEqual(result["missing"], [])

    def test_undo_shutdown_fails_when_interface_is_still_shutdown(self):
        result = self.check(
            ["interface GigabitEthernet0/0/1", "undo shutdown"],
            """#
interface GigabitEthernet0/0/1
 shutdown
#
return
""",
        )
        self.assertTrue(any("仍存在 shutdown" in item for item in result["missing"]))

    def test_undo_shutdown_passes_when_default_is_restored(self):
        result = self.check(
            ["interface GigabitEthernet0/0/1", "undo shutdown"],
            """#
interface GigabitEthernet0/0/1
 ip address 192.0.2.1 24
#
return
""",
        )
        self.assertEqual(result["missing"], [])

    def test_undo_area_detects_remaining_wrong_area(self):
        result = self.check(
            ["system-view", "ospf 1", "undo area 1", "area 0"],
            """#
ospf 1 router-id 1.1.1.1
 area 0.0.0.1
  network 10.0.12.0 0.0.0.255
#
return
""",
        )
        self.assertTrue(any("仍存在 area 1" in item for item in result["missing"]))

    def test_positive_command_after_undo_is_the_final_state(self):
        result = self.check(
            ["interface GigabitEthernet0/0/1", "undo ip address",
             "ip address 192.0.2.1 24"],
            """#
interface GigabitEthernet0/0/1
 ip address 192.0.2.1 255.255.255.0
#
return
""",
        )
        self.assertEqual(result["missing"], [])

    def test_vlan_batch_equivalence(self):
        result = self.check(
            ["vlan batch 10 20"],
            """#
vlan batch 10 20
#
return
""",
        )
        self.assertEqual(result["missing"], [])

    def test_extra_interface_command_is_reported(self):
        result = self.check(
            ["interface GigabitEthernet0/0/1", "port default vlan 10"],
            """#
interface GigabitEthernet0/0/1
 port default vlan 20
#
return
""",
        )
        self.assertTrue(any("port default vlan 20" in item for item in result["extra"]))

    def test_bgp_family_scope(self):
        result = self.check(
            ["bgp 100", "ipv4-family unicast", "network 192.0.2.0 255.255.255.0"],
            """#
bgp 100
 router-id 1.1.1.1
 ipv4-family unicast
  network 198.51.100.0 255.255.255.0
#
return
""",
        )
        self.assertTrue(any("192.0.2.0" in item for item in result["missing"]))


if __name__ == "__main__":
    unittest.main()
