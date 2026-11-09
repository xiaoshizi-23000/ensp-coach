import unittest

import app


class CheckRetryPolicyTests(unittest.TestCase):
    def test_ping_gets_bounded_retries(self):
        self.assertEqual(app.check_retry_policy({"cmd": "ping -c 3 192.0.2.1"}), (3, 3.0))

    def test_protocol_peer_waits_longer(self):
        self.assertEqual(app.check_retry_policy({"cmd": "display ospf peer brief"}), (4, 5.0))

    def test_static_display_has_no_retry(self):
        self.assertEqual(app.check_retry_policy(
            {"cmd": "display ip routing-table 192.0.2.0"}), (1, 3.0))

    def test_explicit_attempts_override_default(self):
        self.assertEqual(app.check_retry_policy(
            {"cmd": "ping -c 3 192.0.2.1", "attempts": 2, "retry_wait": 1}), (2, 1.0))

    def test_attempts_are_clamped(self):
        self.assertEqual(app.check_retry_policy(
            {"cmd": "display version", "attempts": 99, "retry_wait": 99}), (6, 15.0))


if __name__ == "__main__":
    unittest.main()
