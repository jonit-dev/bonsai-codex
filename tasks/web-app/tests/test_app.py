import json
import os
import sys
import tempfile
import threading
import unittest
from http.client import HTTPConnection

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app


class NotesAppTests(unittest.TestCase):
    def setUp(self):
        handle, self.store_path = tempfile.mkstemp(suffix=".json")
        os.close(handle)
        os.unlink(self.store_path)
        self.server = create_app(self.store_path)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.server_address[0], self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        if os.path.exists(self.store_path):
            os.unlink(self.store_path)

    def request(self, method, path, body=None):
        conn = HTTPConnection(self.host, self.port, timeout=5)
        payload = None if body is None else json.dumps(body)
        headers = {"content-type": "application/json"} if payload else {}
        conn.request(method, path, body=payload, headers=headers)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        content_type = response.getheader("content-type", "")
        parsed = json.loads(data) if "application/json" in content_type else data.decode()
        return response.status, parsed

    def test_page_renders_a_form_and_lists_notes(self):
        status, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("<html", body.lower())
        self.assertIn("<form", body.lower())

    def test_create_then_see_the_note_in_the_page_and_the_api(self):
        status, created = self.request("POST", "/api/notes", {"text": "buy milk"})
        self.assertEqual(status, 201)
        self.assertEqual(created["text"], "buy milk")
        self.assertEqual(created["id"], 1)

        status, listing = self.request("GET", "/api/notes")
        self.assertEqual(status, 200)
        self.assertEqual([note["text"] for note in listing["notes"]], ["buy milk"])

        status, page = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("buy milk", page)

    def test_notes_survive_a_restart(self):
        self.request("POST", "/api/notes", {"text": "persisted"})
        self.server.shutdown()
        self.thread.join(timeout=5)

        self.server = create_app(self.store_path)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.server_address[0], self.server.server_address[1]

        status, listing = self.request("GET", "/api/notes")
        self.assertEqual(status, 200)
        self.assertEqual([note["text"] for note in listing["notes"]], ["persisted"])

    def test_blank_note_is_rejected(self):
        status, body = self.request("POST", "/api/notes", {"text": "   "})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "text is required")

    def test_unknown_route_is_404_json(self):
        status, body = self.request("GET", "/nope")
        self.assertEqual(status, 404)
        self.assertEqual(body["error"], "not found")


if __name__ == "__main__":
    unittest.main()
