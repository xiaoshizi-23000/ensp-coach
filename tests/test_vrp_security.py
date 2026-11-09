import os
import tempfile
import unittest

from vrp_security import clean_command, clean_plan, resource_path, safe_id


class CommandPolicyTests(unittest.TestCase):
    def test_read_only_allows_display_and_ping(self):
        self.assertEqual(clean_command(" display ospf peer brief ", read_only=True),
                         "display ospf peer brief")
        self.assertEqual(clean_command("ping -c 3 192.0.2.1", read_only=True),
                         "ping -c 3 192.0.2.1")

    def test_read_only_rejects_configuration(self):
        with self.assertRaises(ValueError):
            clean_command("system-view", read_only=True)

    def test_rejects_multiline_injection(self):
        with self.assertRaises(ValueError):
            clean_command("display version\nreboot")

    def test_rejects_destructive_commands(self):
        for command in ("reboot", "reset saved-configuration", "clear ip route-table",
                        "delete flash:/vrpcfg.zip", "undo all"):
            with self.subTest(command=command):
                with self.assertRaises(ValueError):
                    clean_command(command)

    def test_allows_normal_undo(self):
        self.assertEqual(clean_command("undo shutdown"), "undo shutdown")
        self.assertEqual(clean_command("undo ip route-static 10.0.0.0 24 10.0.0.3"),
                         "undo ip route-static 10.0.0.0 24 10.0.0.3")

    def test_plan_validates_all_commands_before_execution(self):
        with self.assertRaises(ValueError):
            clean_plan({"R1": ["system-view", "reboot"]})


class ResourcePathTests(unittest.TestCase):
    def test_rejects_traversal_ids(self):
        for value in ("../config", r"..\config", "a/b", "a.b", ""):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    safe_id(value)

    def test_resource_stays_inside_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            path = resource_path(folder, "tr-route", ".json")
            self.assertEqual(os.path.dirname(path), os.path.realpath(folder))


if __name__ == "__main__":
    unittest.main()
