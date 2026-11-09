import unittest
from unittest import mock

from ensp_kit import Vrp


class VrpLoginTests(unittest.TestCase):
    def test_relogs_after_console_idle_message(self):
        client = Vrp()
        client.s = mock.Mock()
        client.read = mock.Mock(side_effect=["Configuration console exit, please press any key to log on", "<R1>"])
        with mock.patch("ensp_kit.socket.create_connection", return_value=client.s):
            text = client.open()
        self.assertIn("<R1>", text)
        self.assertEqual(client.s.sendall.call_args_list, [mock.call(b"\r"), mock.call(b"\r")])

    def test_refuses_password_prompt(self):
        client = Vrp()
        client.s = mock.Mock()
        client.read = mock.Mock(return_value="Login authentication\r\n\r\nPassword:")
        with mock.patch("ensp_kit.socket.create_connection", return_value=client.s):
            with self.assertRaisesRegex(RuntimeError, "登录密码"):
                client.open()
        client.s.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
