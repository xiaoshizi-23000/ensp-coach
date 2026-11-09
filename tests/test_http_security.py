import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer

import app


class LocalApiSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def request(self, method, path, body=None, token=None, host=None, origin=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        payload = json.dumps(body or {}).encode("utf-8") if body is not None else None
        headers = {}
        if payload is not None:
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(payload))
        if token:
            headers["X-Ensp-Token"] = token
        headers["Origin"] = origin or f"http://127.0.0.1:{self.port}"
        if host:
            headers["Host"] = host
        conn.request(method, path, body=payload, headers=headers)
        response = conn.getresponse()
        data = response.read()
        status = response.status
        conn.close()
        try:
            return status, json.loads(data.decode("utf-8")) if data else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            return status, {}

    def session_token(self):
        status, data = self.request("GET", "/api/session")
        self.assertEqual(status, 200)
        return data["token"]

    def test_post_without_token_is_rejected(self):
        status, data = self.request("POST", "/api/not-a-route", {})
        self.assertEqual(status, 403)
        self.assertFalse(data["ok"])

    def test_valid_token_reaches_router(self):
        token = self.session_token()
        status, data = self.request("POST", "/api/not-a-route", {}, token=token)
        self.assertEqual(status, 404)
        self.assertEqual(data["error"], "no route")

    def test_foreign_origin_is_rejected(self):
        token = self.session_token()
        status, _ = self.request("POST", "/api/not-a-route", {}, token=token,
                                 origin="http://evil.example")
        self.assertEqual(status, 403)

    def test_foreign_host_is_rejected(self):
        token = self.session_token()
        status, _ = self.request("POST", "/api/not-a-route", {}, token=token,
                                 host="evil.example")
        self.assertEqual(status, 403)

    def test_foreign_host_cannot_read_session_on_get(self):
        status, _ = self.request("GET", "/api/session", host="evil.example")
        self.assertEqual(status, 403)

    def test_static_path_traversal_is_rejected(self):
        status, _ = self.request("GET", "/../config.json")
        self.assertEqual(status, 404)

    def test_pages_and_readonly_routes_are_served(self):
        for path in ("/", "/client.js", "/api/labs", "/api/review", "/api/course"):
            with self.subTest(path=path):
                status, _ = self.request("GET", path)
                self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
