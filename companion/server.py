"""Localhost bridge between the Chrome extension and the Hermes plugin."""

import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import ThreadingTCPServer
import socket

from companion.input_win import FocusError, perform as windows_perform
from companion.wsframes import FrameParser, accept_key, encode_close, encode_text

TOKEN_HEADER = "authorization"
MAX_BODY = 1_000_000


def extension_command_names():
    """Names defined by the extension. The bridge does not rename them."""
    path = Path(__file__).resolve().parent.parent / "extension" / "commands.json"
    return {row["name"] for row in json.loads(path.read_text(encoding="utf-8"))}


def token_path():
    override = os.environ.get("CHROLLER_TOKEN_FILE")
    if override:
        return Path(override)
    return Path.home() / ".chroller" / "token"


def load_or_create_token():
    path = token_path()
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(24)
    path.write_text(token, encoding="utf-8")
    return token


def _same_token(left, right):
    if not left or not right or len(left) != len(right):
        return False
    return secrets.compare_digest(left, right)


class Companion:
    def __init__(self, host, http_port, ws_port, token, performer=None):
        self.host = host
        self.http_port = http_port
        self.ws_port = ws_port
        self.token = token
        self.performer = performer or windows_perform
        self._lock = threading.Lock()
        self._connected = threading.Event()
        self._client = None
        self._send_lock = threading.Lock()
        self._pending = {}
        self._http = None
        self._ws = None
        self._threads = []

    def start(self):
        self._http = _HttpServer((self.host, self.http_port), self._handler())
        self.http_port = self._http.server_address[1]
        self._ws = _WsServer((self.host, self.ws_port), self)
        self.ws_port = self._ws.server_address[1]
        self._threads = [
            threading.Thread(target=self._http.serve_forever, name="chroller-http", daemon=True),
            threading.Thread(target=self._ws.serve_forever, name="chroller-ws", daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    def stop(self):
        if self._http:
            self._http.shutdown()
            self._http.server_close()
        if self._ws:
            self._ws.shutdown()
            self._ws.server_close()
        with self._lock:
            client = self._client
            self._client = None
            pending = list(self._pending.values())
            self._pending.clear()
        if client:
            try:
                client.close()
            except OSError:
                pass
        for box in pending:
            box.fail("Companion stopped.")
        self._connected.clear()

    def command(self, op, args, timeout=30):
        deadline = time.time() + timeout
        if not self._wait_for_client(max(0, deadline - time.time())) or not self._connected.is_set():
            return {"ok": False, "error": "Chroller extension is not connected. Open Chrome and save the pairing token."}
        command_id = secrets.token_hex(8)
        box = _WaitBox()
        with self._lock:
            self._pending[command_id] = box
        self._send({"type": "command", "id": command_id, "op": op, "args": args or {}})
        while time.time() < deadline:
            message = box.wait(deadline - time.time())
            if message is None:
                break
            if message.get("type") == "needs_input":
                self._perform_input(command_id, message.get("input") or {})
                continue
            if message.get("type") == "result":
                with self._lock:
                    self._pending.pop(command_id, None)
                if message.get("ok"):
                    return {"ok": True, "data": message.get("data")}
                return {"ok": False, "error": message.get("error") or "The extension reported a failure."}
            if message.get("type") == "fail":
                with self._lock:
                    self._pending.pop(command_id, None)
                return {"ok": False, "error": message.get("error") or "Extension disconnected."}
        with self._lock:
            self._pending.pop(command_id, None)
        return {"ok": False, "error": "Extension did not respond in time."}

    def _perform_input(self, command_id, payload):
        try:
            self.performer(payload)
            self._send({"type": "input_done", "id": command_id, "ok": True})
        except FocusError as exc:
            self._send({"type": "input_done", "id": command_id, "ok": False, "error": str(exc)})
        except Exception:
            self._send({"type": "input_done", "id": command_id, "ok": False, "error": "OS input failed."})

    def _wait_for_client(self, timeout):
        if self._connected.is_set():
            return True
        return self._connected.wait(timeout)

    def _send(self, message):
        encoded = encode_text(json.dumps(message))
        with self._lock:
            if not self._connected.is_set():
                return
            client = self._client
        if client is None:
            return
        with self._send_lock:
            try:
                client.sendall(encoded)
            except OSError:
                self._drop(client, "Extension disconnected.")

    def accept_client(self, conn, initial=b""):
        with self._lock:
            previous = self._client
            self._client = conn
            self._connected.clear()
        if previous and previous is not conn:
            try:
                previous.close()
            except OSError:
                pass
        threading.Thread(target=self._read_client, args=(conn, initial), daemon=True).start()

    def _read_client(self, conn, initial=b""):
        parser = FrameParser()
        authed = False
        pending = [initial] if initial else []
        try:
            while True:
                if pending:
                    chunk = pending.pop(0)
                else:
                    chunk = conn.recv(65536)
                if not chunk:
                    break
                for opcode, payload in parser.feed(chunk):
                    if opcode == 0x8:
                        return
                    if opcode == 0x9:
                        # Unmasked pong. Browsers accept it.
                        pong = bytearray([0x8A, len(payload)])
                        pong.extend(payload)
                        with self._send_lock:
                            conn.sendall(pong)
                        continue
                    if opcode != 0x1:
                        continue
                    if not authed:
                        authed = self._auth(conn, payload)
                        continue
                    self._on_message(payload)
        except OSError:
            pass
        finally:
            self._drop(conn, "Extension disconnected.")

    def _auth(self, conn, payload):
        try:
            message = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            message = {}
        if message.get("type") == "auth" and _same_token(message.get("token", ""), self.token):
            with self._lock:
                if self._client is not conn:
                    return False
                self._connected.set()
            encoded = encode_text(json.dumps({"type": "auth_ok"}))
            with self._send_lock:
                conn.sendall(encoded)
            return True
        encoded = encode_text(json.dumps({"type": "auth_fail"}))
        with self._send_lock:
            try:
                conn.sendall(encoded)
            except OSError:
                return False
        return False

    def _on_message(self, payload):
        try:
            message = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        command_id = message.get("id")
        with self._lock:
            box = self._pending.get(command_id)
        if box:
            box.push(message)

    def _drop(self, conn, reason):
        with self._lock:
            if self._client is conn:
                self._client = None
                self._connected.clear()
                pending = list(self._pending.values())
            else:
                pending = []
        try:
            conn.close()
        except OSError:
            pass
        for box in pending:
            box.fail(reason)

    def _handler(self):
        companion = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                return

            def _reject(self, code, error):
                body = json.dumps({"ok": False, "error": error}).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _authorized(self):
                header = self.headers.get(TOKEN_HEADER, "")
                prefix = "bearer "
                if not header.lower().startswith(prefix):
                    return False
                return _same_token(header[len(prefix):].strip(), companion.token)

            def do_GET(self):
                if self.path != "/health":
                    self._reject(404, "Not found.")
                    return
                body = json.dumps({"ok": True, "service": "chroller"}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                if self.path != "/v1/command":
                    self._reject(404, "Not found.")
                    return
                if not self._authorized():
                    self._reject(401, "Pairing token was rejected.")
                    return
                length = int(self.headers.get("Content-Length", "0") or 0)
                if length < 0 or length > MAX_BODY:
                    self._reject(400, "Request is too large.")
                    return
                raw = self.rfile.read(length)
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._reject(400, "Request was not JSON.")
                    return
                op = payload.get("op")
                args = payload.get("args") or {}
                if not op:
                    self._reject(400, "op is required.")
                    return
                if op not in extension_command_names():
                    self._reject(400, "Unknown command " + str(op) + ".")
                    return
                self._log_op = op
                self._log_tab = args.get("tab_id", "")
                print("chroller %s tab=%s" % (self._log_op, self._log_tab), flush=True)
                result = companion.command(op, args)
                body = json.dumps(result).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler


class _HttpServer(ThreadingHTTPServer):
    daemon_threads = True


class _WaitBox:
    def __init__(self):
        self._event = threading.Event()
        self._messages = []
        self._lock = threading.Lock()

    def push(self, message):
        with self._lock:
            self._messages.append(message)
        self._event.set()

    def fail(self, error):
        self.push({"type": "fail", "error": error})

    def wait(self, timeout):
        if timeout < 0:
            return None
        if not self._event.wait(timeout):
            return None
        with self._lock:
            if not self._messages:
                self._event.clear()
                return None
            message = self._messages.pop(0)
            if not self._messages:
                self._event.clear()
            return message


class _WsServer(ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, companion):
        self.companion = companion
        super().__init__(address, _WsHandler)

    def handle_error(self, request, client_address):
        return


class _WsHandler:
    def __init__(self, request, client_address, server):
        self.request = request
        self.server = server
        self.handle()

    def handle(self):
        conn = self.request
        try:
            header = b""
            while b"\r\n\r\n" not in header:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                header += chunk
                if len(header) > 16384:
                    return
            text = header.decode("iso-8859-1", errors="replace")
            key = ""
            for line in text.split("\r\n"):
                if line.lower().startswith("sec-websocket-key:"):
                    key = line.split(":", 1)[1].strip()
            if not key:
                conn.sendall(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
                return
            accept = accept_key(key)
            response = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                "Sec-WebSocket-Accept: %s\r\n\r\n" % accept
            )
            conn.sendall(response.encode("ascii"))
            self.server.companion.accept_client(conn, header.split(b"\r\n\r\n", 1)[1])
            # accept_client reads the socket on another thread. Keep this
            # handler alive until that thread closes the socket.
            while True:
                time.sleep(0.5)
                with self.server.companion._lock:
                    current = self.server.companion._client
                if current is not conn:
                    break
        finally:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def main():
    token = load_or_create_token()
    bridge = Companion("127.0.0.1", 8765, 8766, token)
    bridge.start()
    print("Chroller companion", flush=True)
    print("HTTP  http://127.0.0.1:%s" % bridge.http_port, flush=True)
    print("WS    ws://127.0.0.1:%s" % bridge.ws_port, flush=True)
    print("Pairing token: %s" % token, flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        bridge.stop()
