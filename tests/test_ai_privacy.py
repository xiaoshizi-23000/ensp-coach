import unittest

from ai import Redactor


class RedactorTests(unittest.TestCase):
    def test_secrets_are_removed_without_eating_next_line(self):
        text = "local-user admin password cipher Secret123\ninterface GE0/0/1"
        result = Redactor("secrets").text(text)
        self.assertNotIn("Secret123", result)
        self.assertIn("interface GE0/0/1", result)

    def test_community_is_removed(self):
        result = Redactor("secrets").text("snmp-agent community read cipher Public123")
        self.assertNotIn("Public123", result)

    def test_strict_mode_preserves_ip_relationships(self):
        redactor = Redactor("strict")
        result = redactor.text("source 10.0.0.1 peer 10.0.0.2 again 10.0.0.1")
        self.assertEqual(result.count("192.0.2.1"), 2)
        self.assertIn("192.0.2.2", result)
        self.assertNotIn("10.0.0.1", result)

    def test_strict_mode_keeps_netmasks_and_default_routes(self):
        result = Redactor("strict").text("ip address 10.0.0.1 255.255.255.0\nnext 0.0.0.0")
        self.assertIn("255.255.255.0", result)
        self.assertIn("0.0.0.0", result)

    def test_off_mode_does_not_change_content(self):
        text = "password cipher Secret123\nip address 10.0.0.1 24"
        self.assertEqual(Redactor("off").text(text), text)


if __name__ == "__main__":
    unittest.main()
