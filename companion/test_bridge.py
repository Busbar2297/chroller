import json
import os
import socket
import threading
import unittest
import urllib.error
import urllib.request

from companion.input_win import INPUT, absolute_from_physical, parse_key
from companion.server import Companion
from companion.wsframes import FrameParser, accept_key, encode_client_text


class FramingTests(unittest.TestCase):
    def test_absolute_mapping_uses_the_virtual_screen(self):
        self.assertEqual(absolute_from_physical(0, 0, 0, 0, 65536, 65536), (0, 0))
        self.assertEqual(absolute_from_physical(100, 50, -100, -50, 200, 100), (65535, 65535))

    def test_key_parser_accepts_shortcuts(self):
        mods, vk = parse_key("Control+Enter")
        self.assertEqual(mods, [0x11])
        self.assertEqual(vk, 0x0D)

    def test_input_struct_matches_windows(self):
        if os.name != "nt":
            self.skipTest("Windows struct")
        bits = 64 if __import__("ctypes").sizeof(__import__("ctypes").c_void_p) == 8 else 32
        self.assertEqual(__import__("ctypes").sizeof(INPUT), 40 if bits == 64 else 28)

    def test_round_trip_masked_text(self):
        parser = FrameParser()
        frames = parser.feed(encode_client_text('{"type":"auth"}'))
        self.assertEqual(frames, [(1, b'{"type":"auth"}')])
        self.assertEqual(accept_key("dGhlIHNhbXBsZSBub25jZQ=="), "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")


class Reader:
    def __init__(self, sock, prelude=b""):
        self.sock = sock
        self.parser = FrameParser()
        self.queued = []
        self.sock.settimeout(5)
        if prelude:
            self._take(prelude)

    def _take(self, chunk):
        for opcode, payload in self.parser.feed(chunk):
            if opcode == 1:
                self.queued.append(json.loads(payload.decode("utf-8")))

    def next_text(self):
        while not self.queued:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise AssertionError("socket closed")
            self._take(chunk)
        return self.queued.pop(0)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.performed = []
        self.bridge = Companion("127.0.0.1", 0, 0, "test-token", performer=self._perform)
        self.bridge.start()

    def tearDown(self):
        self.bridge.stop()

    def _perform(self, payload):
        kind = payload.get("kind")
        self.performed.append(kind)
        if kind == "click" and payload.get("x") == -1:
            from companion.input_win import FocusError
            raise FocusError("Chrome did not take focus. Click the Chrome window once and retry.")

    def _request(self, payload, token="test-token"):
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            "http://127.0.0.1:%s/v1/command" % self.bridge.http_port,
            data=data,
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def _client(self, token="test-token"):
        sock = socket.create_connection(("127.0.0.1", self.bridge.ws_port), timeout=5)
        key = "dGhlIHNhbXBsZSBub25jZQ=="
        sock.sendall((
            "GET / HTTP/1.1\r\n"
            "Host: 127.0.0.1\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: %s\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n" % key
        ).encode("ascii"))
        data = b""
        while b"\r\n\r\n" not in data:
            data += sock.recv(4096)
        self.assertIn(b"101", data.split(b"\r\n", 1)[0])
        extra = data.split(b"\r\n\r\n", 1)[1]
        sock.sendall(encode_client_text(json.dumps({"type": "auth", "token": token})))
        return sock, Reader(sock, extra)

    def _next(self, sock, reader):
        return reader.next_text()

    def test_rejects_a_bad_token(self):
        request = urllib.request.Request(
            "http://127.0.0.1:%s/v1/command" % self.bridge.http_port,
            data=b'{"op":"chroller_status","args":{}}',
            headers={"Authorization": "Bearer wrong", "Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(caught.exception.code, 401)

    def test_times_out_without_an_extension(self):
        result = self.bridge.command("chroller_status", {}, timeout=0.4)
        self.assertFalse(result["ok"])
        self.assertIn("not connected", result["error"])

    def test_status_round_trip(self):
        sock, parser = self._client()
        try:
            self.assertEqual(self._next(sock, parser)["type"], "auth_ok")
            holder = {}

            def call():
                holder["result"] = self._request({"op": "chroller_status", "args": {}})

            thread = threading.Thread(target=call)
            thread.start()
            command = self._next(sock, parser)
            self.assertEqual(command["op"], "chroller_status")
            sock.sendall(encode_client_text(json.dumps({
                "type": "result",
                "id": command["id"],
                "ok": True,
                "data": {"connected": True, "armed": True, "attached": [3]},
            })))
            thread.join(5)
            self.assertTrue(holder["result"]["ok"])
            self.assertEqual(holder["result"]["data"]["attached"], [3])
        finally:
            sock.close()

    def test_click_uses_os_input_and_hides_typed_text_from_the_result(self):
        sock, parser = self._client()
        try:
            self.assertEqual(self._next(sock, parser)["type"], "auth_ok")
            holder = {}

            def call():
                holder["result"] = self._request({
                    "op": "chroller_type",
                    "args": {"tab_id": 7, "ref": "f0e1", "text": "s3cret-password"},
                })

            thread = threading.Thread(target=call)
            thread.start()
            command = self._next(sock, parser)
            sock.sendall(encode_client_text(json.dumps({
                "type": "needs_input",
                "id": command["id"],
                "input": {"kind": "click", "x": 10, "y": 20, "dpr": 1, "window": {"left": 0, "top": 0, "width": 10, "height": 10}},
            })))
            done = self._next(sock, parser)
            self.assertEqual(done["type"], "input_done")
            self.assertTrue(done["ok"])
            sock.sendall(encode_client_text(json.dumps({
                "type": "needs_input",
                "id": command["id"],
                "input": {"kind": "type", "text": "s3cret-password", "dpr": 1, "window": {"left": 0, "top": 0, "width": 10, "height": 10}},
            })))
            done = self._next(sock, parser)
            self.assertEqual(done["type"], "input_done")
            sock.sendall(encode_client_text(json.dumps({
                "type": "result",
                "id": command["id"],
                "ok": True,
                "data": {"tab_id": 7, "ref": "f0e1", "method": "os"},
            })))
            thread.join(5)
            self.assertEqual(self.performed, ["click", "type"])
            encoded = json.dumps(holder["result"])
            self.assertNotIn("s3cret-password", encoded)
        finally:
            sock.close()

    def test_focus_failure_is_returned_to_the_caller(self):
        sock, parser = self._client()
        try:
            self._next(sock, parser)
            holder = {}

            def call():
                holder["result"] = self._request({"op": "chroller_click", "args": {"tab_id": 1, "ref": "f0e1"}})

            thread = threading.Thread(target=call)
            thread.start()
            command = self._next(sock, parser)
            sock.sendall(encode_client_text(json.dumps({
                "type": "needs_input",
                "id": command["id"],
                "input": {"kind": "click", "x": -1, "y": 0, "dpr": 1, "window": {}},
            })))
            done = self._next(sock, parser)
            self.assertFalse(done["ok"])
            sock.sendall(encode_client_text(json.dumps({
                "type": "result",
                "id": command["id"],
                "ok": False,
                "error": done["error"],
            })))
            thread.join(5)
            self.assertFalse(holder["result"]["ok"])
            self.assertIn("focus", holder["result"]["error"])
        finally:
            sock.close()


if __name__ == "__main__":
    unittest.main()
