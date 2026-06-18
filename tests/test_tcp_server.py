import base64
import socket
import tempfile
import threading
import time
import unittest
from email.utils import formatdate
from pathlib import Path

import TCPServer


def read_response(sock):
    buffer = b""
    while b"\r\n\r\n" not in buffer:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buffer += chunk

    header_bytes, _, body = buffer.partition(b"\r\n\r\n")
    header_text = header_bytes.decode("iso-8859-1")
    lines = header_text.splitlines()
    status_parts = lines[0].split(" ", 2)
    headers = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        headers[name.lower()] = value.strip()

    content_length = int(headers.get("content-length", "0"))
    while len(body) < content_length:
        chunk = sock.recv(4096)
        if not chunk:
            break
        body += chunk

    return int(status_parts[1]), status_parts[2], headers, body[:content_length]


class TCPServerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.public_dir = root / "public"
        self.private_dir = root / "private"
        self.public_dir.mkdir()
        self.private_dir.mkdir()
        (self.public_dir / "file1.html").write_text("<h1>Hello</h1>", encoding="utf-8")
        (self.private_dir / "file2.html").write_text("<h1>Secret</h1>", encoding="utf-8")
        (self.public_dir / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x01binary")
        self.log_file = root / "server_log.txt"
        config = TCPServer.ServerConfig(
            public_dir=self.public_dir,
            private_dir=self.private_dir,
            log_file=self.log_file,
            username="username",
            password="password",
            keep_alive_timeout=1,
        )
        self.server = TCPServer.ThreadedHTTPServer("127.0.0.1", 0, config)
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.host, self.port = self.server.server_address

    def tearDown(self):
        self.server.shutdown()
        self.server_thread.join(timeout=2)
        self.temp_dir.cleanup()

    def send_request(self, request_bytes):
        with socket.create_connection((self.host, self.port), timeout=2) as sock:
            sock.settimeout(2)
            sock.sendall(request_bytes)
            return read_response(sock)

    def test_get_public_text_file_returns_200(self):
        status, reason, headers, body = self.send_request(
            b"GET /public/file1.html HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
        )

        self.assertEqual(status, 200)
        self.assertEqual(reason, "OK")
        self.assertEqual(headers["content-type"], "text/html")
        self.assertEqual(body, b"<h1>Hello</h1>")

    def test_head_returns_headers_without_body(self):
        status, _, headers, body = self.send_request(
            b"HEAD /public/file1.html HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
        )

        self.assertEqual(status, 200)
        self.assertEqual(int(headers["content-length"]), len(b"<h1>Hello</h1>"))
        self.assertEqual(body, b"")

    def test_missing_file_returns_404(self):
        status, _, _, body = self.send_request(
            b"GET /public/missing.html HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
        )

        self.assertEqual(status, 404)
        self.assertEqual(body, b"404 Not Found")

    def test_private_file_without_auth_returns_403(self):
        status, _, _, body = self.send_request(
            b"GET /private/file2.html HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
        )

        self.assertEqual(status, 403)
        self.assertEqual(body, b"403 Forbidden")

    def test_private_file_with_auth_returns_200(self):
        token = base64.b64encode(b"username:password").decode("ascii")
        request = (
            "GET /private/file2.html HTTP/1.1\r\n"
            "Host: localhost\r\n"
            f"Authorization: Basic {token}\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")

        status, _, _, body = self.send_request(request)

        self.assertEqual(status, 200)
        self.assertEqual(body, b"<h1>Secret</h1>")

    def test_if_modified_since_returns_304_without_body(self):
        future_date = formatdate(time.time() + 100000, usegmt=True)
        request = (
            "GET /public/file1.html HTTP/1.1\r\n"
            "Host: localhost\r\n"
            f"If-Modified-Since: {future_date}\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")

        status, _, headers, body = self.send_request(request)

        self.assertEqual(status, 304)
        self.assertEqual(headers["content-length"], "0")
        self.assertEqual(body, b"")

    def test_binary_response_preserves_bytes_and_length(self):
        status, _, headers, body = self.send_request(
            b"GET /public/image.png HTTP/1.1\r\nHost: localhost\r\nAccept: image/*\r\nConnection: close\r\n\r\n"
        )

        self.assertEqual(status, 200)
        self.assertEqual(body, b"\x89PNG\r\n\x1a\n\x00\x01binary")
        self.assertEqual(int(headers["content-length"]), len(body))

    def test_connection_close_closes_after_response(self):
        with socket.create_connection((self.host, self.port), timeout=2) as sock:
            sock.settimeout(2)
            sock.sendall(b"GET /public/file1.html HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
            status, _, _, _ = read_response(sock)
            self.assertEqual(status, 200)
            self.assertEqual(sock.recv(1), b"")

    def test_keep_alive_handles_multiple_requests_on_one_socket(self):
        with socket.create_connection((self.host, self.port), timeout=2) as sock:
            sock.settimeout(2)
            sock.sendall(b"GET /public/file1.html HTTP/1.1\r\nHost: localhost\r\nConnection: keep-alive\r\n\r\n")
            first_status, _, first_headers, first_body = read_response(sock)
            sock.sendall(b"GET /public/missing.html HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
            second_status, _, _, second_body = read_response(sock)

        self.assertEqual(first_status, 200)
        self.assertEqual(first_headers["connection"], "keep-alive")
        self.assertEqual(first_body, b"<h1>Hello</h1>")
        self.assertEqual(second_status, 404)
        self.assertEqual(second_body, b"404 Not Found")

    def test_path_traversal_is_rejected(self):
        status, _, _, body = self.send_request(
            b"GET /../TCPServer.py HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
        )

        self.assertEqual(status, 403)
        self.assertEqual(body, b"403 Forbidden")

    def test_malformed_request_returns_400(self):
        status, _, _, body = self.send_request(b"BAD\r\n\r\n")

        self.assertEqual(status, 400)
        self.assertEqual(body, b"400 Bad Request")

    def test_unsupported_method_returns_405(self):
        status, _, headers, body = self.send_request(
            b"POST /public/file1.html HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
        )

        self.assertEqual(status, 405)
        self.assertEqual(headers["allow"], "GET, HEAD")
        self.assertEqual(body, b"405 Method Not Allowed")


if __name__ == "__main__":
    unittest.main()
