import json
import threading
import unittest
from http.client import HTTPConnection

from api import create_app


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.server = create_app()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.server_address

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method, path, body=None):
        headers = {}
        payload = None
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        conn = HTTPConnection(self.host, self.port, timeout=2)
        try:
            conn.request(method, path, payload, headers)
            response = conn.getresponse()
            raw = response.read().decode("utf-8")
            data = json.loads(raw) if raw else None
            return response.status, data
        finally:
            conn.close()

    def test_health(self):
        status, data = self.request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(data, {"status": "ok"})

    def test_create_and_list_items(self):
        status, data = self.request("POST", "/items", {"name": "alpha"})
        self.assertEqual(status, 201)
        self.assertEqual(data, {"id": 1, "name": "alpha"})

        status, data = self.request("GET", "/items")
        self.assertEqual(status, 200)
        self.assertEqual(data, {"items": [{"id": 1, "name": "alpha"}]})

    def test_rejects_missing_name(self):
        status, data = self.request("POST", "/items", {"name": ""})
        self.assertEqual(status, 400)
        self.assertEqual(data, {"error": "name is required"})

    def test_missing_route(self):
        status, data = self.request("GET", "/missing")
        self.assertEqual(status, 404)
        self.assertEqual(data, {"error": "not found"})


if __name__ == "__main__":
    unittest.main()
