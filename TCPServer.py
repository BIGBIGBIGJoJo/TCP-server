import argparse
import base64
import mimetypes
import os
import socket
import threading
from dataclasses import dataclass
from email.utils import formatdate, parsedate_to_datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 12346
DEFAULT_PUBLIC_DIR = "public"
DEFAULT_PRIVATE_DIR = "private"
DEFAULT_LOG_FILE = "server_log.txt"
DEFAULT_USERNAME = "username"
DEFAULT_PASSWORD = "password"
DEFAULT_KEEP_ALIVE_TIMEOUT = 30
SERVER_NAME = "MyServer/1.0"
MAX_HEADER_BYTES = 65536


class BadRequest(Exception):
    pass


class ForbiddenPath(Exception):
    pass


@dataclass
class ServerConfig:
    public_dir: Path | str = DEFAULT_PUBLIC_DIR
    private_dir: Path | str = DEFAULT_PRIVATE_DIR
    log_file: Path | str = DEFAULT_LOG_FILE
    username: str = DEFAULT_USERNAME
    password: str = DEFAULT_PASSWORD
    keep_alive_timeout: int = DEFAULT_KEEP_ALIVE_TIMEOUT
    server_name: str = SERVER_NAME

    def __post_init__(self):
        self.public_dir = Path(self.public_dir).resolve()
        self.private_dir = Path(self.private_dir).resolve()
        self.log_file = Path(self.log_file)

    @property
    def basic_auth_token(self):
        credentials = f"{self.username}:{self.password}".encode("utf-8")
        return "Basic " + base64.b64encode(credentials).decode("ascii")


@dataclass
class HttpRequest:
    method: str
    target: str
    version: str
    headers: dict[str, str]

    def header(self, name):
        return self.headers.get(name.lower())


@dataclass
class FileInfo:
    path: Path
    is_private: bool
    content_type: str
    modified_time: float
    size: int


@dataclass
class ResponseResult:
    response: bytes
    keep_alive: bool
    request_path: str
    status_code: int
    reason: str
    date_header: str


STATUS_REASONS = {
    200: "OK",
    304: "Not Modified",
    400: "Bad Request",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    415: "Unsupported Media Type",
}


_log_lock = threading.Lock()


def getTime():
    return formatdate(usegmt=True)


def parse_http_request(raw_request):
    try:
        request_text = raw_request.decode("iso-8859-1")
    except UnicodeDecodeError as exc:
        raise BadRequest("Request is not valid HTTP header text") from exc

    lines = request_text.splitlines()
    if not lines:
        raise BadRequest("Request is empty")

    request_line = lines[0].strip()
    request_parts = request_line.split()
    if len(request_parts) != 3:
        raise BadRequest("Request line must contain method, target, and version")

    method, target, version = request_parts
    if not method.isalpha():
        raise BadRequest("HTTP method is invalid")
    if not target.startswith("/"):
        raise BadRequest("Only origin-form request targets are supported")
    if version not in {"HTTP/1.0", "HTTP/1.1"}:
        raise BadRequest("Only HTTP/1.0 and HTTP/1.1 are supported")

    headers = {}
    for line in lines[1:]:
        if not line:
            continue
        if ":" not in line:
            raise BadRequest("Header line is missing ':'")
        name, value = line.split(":", 1)
        name = name.strip().lower()
        if not name:
            raise BadRequest("Header name is empty")
        headers[name] = value.strip()

    return HttpRequest(method=method.upper(), target=target, version=version, headers=headers)


def should_keep_alive(request):
    connection = (request.header("Connection") or "").lower()
    if request.version == "HTTP/1.0":
        return connection == "keep-alive"
    return connection != "close"


def find_header_end(buffer):
    crlf_index = buffer.find(b"\r\n\r\n")
    lf_index = buffer.find(b"\n\n")
    candidates = []
    if crlf_index != -1:
        candidates.append((crlf_index, 4))
    if lf_index != -1:
        candidates.append((lf_index, 2))
    if not candidates:
        return None
    return min(candidates, key=lambda item: item[0])


def read_next_request(connection_socket, buffer):
    while True:
        header_end = find_header_end(buffer)
        if header_end is not None:
            index, delimiter_length = header_end
            raw_request = buffer[:index]
            remainder = buffer[index + delimiter_length:]
            if not raw_request.strip():
                raise BadRequest("Request is empty")
            return raw_request, remainder

        if len(buffer) > MAX_HEADER_BYTES:
            raise BadRequest("HTTP headers are too large")

        chunk = connection_socket.recv(4096)
        if not chunk:
            if buffer.strip():
                raise BadRequest("Connection closed before request headers completed")
            return None, b""
        buffer += chunk


def request_path_from_target(target):
    parsed_target = urlsplit(target)
    if parsed_target.scheme or parsed_target.netloc:
        raise BadRequest("Only origin-form request targets are supported")
    path = unquote(parsed_target.path)
    if not path:
        path = "/"
    if "\x00" in path:
        raise BadRequest("Request path contains a null byte")
    if not path.startswith("/"):
        raise BadRequest("Only absolute paths are supported")
    return path


def safe_join(base_dir, path_parts):
    base_dir = Path(base_dir).resolve()
    candidate = base_dir.joinpath(*path_parts).resolve()
    if os.path.commonpath([str(candidate), str(base_dir)]) != str(base_dir):
        raise ForbiddenPath("Request path escapes the configured document root")
    return candidate


def find_file(target, config):
    request_path = request_path_from_target(target)
    segments = [segment for segment in request_path.split("/") if segment and segment != "."]
    if any(segment == ".." for segment in segments):
        raise ForbiddenPath("Path traversal is not allowed")

    if not segments:
        base_dir = config.public_dir
        relative_parts = ["index.html"]
        is_private = False
    elif segments[0] == "private":
        base_dir = config.private_dir
        relative_parts = segments[1:] or ["index.html"]
        is_private = True
    elif segments[0] == "public":
        base_dir = config.public_dir
        relative_parts = segments[1:] or ["index.html"]
        is_private = False
    else:
        base_dir = config.public_dir
        relative_parts = segments
        is_private = False

    candidate = safe_join(base_dir, relative_parts)
    if candidate.is_dir():
        candidate = safe_join(candidate, ["index.html"])

    if not candidate.is_file():
        return None

    content_type, _ = mimetypes.guess_type(candidate)
    if content_type is None:
        content_type = "application/octet-stream"

    stat_result = candidate.stat()
    return FileInfo(
        path=candidate,
        is_private=is_private,
        content_type=content_type,
        modified_time=stat_result.st_mtime,
        size=stat_result.st_size,
    )


def accepts_content_type(accept_header, content_type):
    if not accept_header:
        return True

    content_type = content_type.split(";", 1)[0].lower()
    if "/" not in content_type:
        return False
    actual_type, actual_subtype = content_type.split("/", 1)

    for raw_item in accept_header.split(","):
        media_range = raw_item.split(";", 1)[0].strip().lower()
        if not media_range:
            continue
        if media_range == "*/*":
            return True
        if "/" not in media_range:
            continue
        accepted_type, accepted_subtype = media_range.split("/", 1)
        if accepted_type == actual_type and accepted_subtype in {"*", actual_subtype}:
            return True
    return False


def is_not_modified(if_modified_since, modified_time):
    if not if_modified_since:
        return False
    try:
        parsed_date = parsedate_to_datetime(if_modified_since)
    except (TypeError, ValueError, IndexError, OverflowError):
        return False
    if parsed_date.tzinfo is None:
        return False
    return int(modified_time) <= int(parsed_date.timestamp())


def make_response(version, status_code, headers=None, body=b"", method="GET", keep_alive=False, config=None):
    if headers is None:
        headers = {}
    if isinstance(body, str):
        body = body.encode("utf-8")
    reason = STATUS_REASONS[status_code]
    date_header = getTime()
    response_headers = {
        "Date": date_header,
        "Server": (config.server_name if config else SERVER_NAME),
        **headers,
        "Content-Length": str(len(body)),
        "Connection": "keep-alive" if keep_alive else "close",
    }
    if keep_alive and config:
        response_headers["Keep-Alive"] = f"timeout={config.keep_alive_timeout}"

    header_lines = [f"{version} {status_code} {reason}"]
    header_lines.extend(f"{name}: {value}" for name, value in response_headers.items())
    response_head = ("\r\n".join(header_lines) + "\r\n\r\n").encode("iso-8859-1")
    if method == "HEAD" or status_code == 304:
        return response_head, date_header
    return response_head + body, date_header


def error_result(version, status_code, request_path, method="GET", keep_alive=False, config=None, extra_headers=None):
    reason = STATUS_REASONS[status_code]
    body = f"{status_code} {reason}".encode("utf-8")
    headers = {"Content-Type": "text/plain; charset=utf-8"}
    if extra_headers:
        headers.update(extra_headers)
    response, date_header = make_response(
        version,
        status_code,
        headers=headers,
        body=body,
        method=method,
        keep_alive=keep_alive,
        config=config,
    )
    return ResponseResult(response, keep_alive, request_path, status_code, reason, date_header)


def build_response(raw_request, config=None):
    if config is None:
        config = ServerConfig()

    try:
        request = parse_http_request(raw_request)
    except BadRequest:
        return error_result("HTTP/1.1", 400, "-", keep_alive=False, config=config)

    request_path = "-"
    try:
        request_path = request_path_from_target(request.target)
    except BadRequest:
        return error_result(request.version, 400, request_path, keep_alive=False, config=config)

    keep_alive = should_keep_alive(request)
    if request.method not in {"GET", "HEAD"}:
        return error_result(
            request.version,
            405,
            request_path,
            method=request.method,
            keep_alive=False,
            config=config,
            extra_headers={"Allow": "GET, HEAD"},
        )

    try:
        file_info = find_file(request.target, config)
    except ForbiddenPath:
        return error_result(request.version, 403, request_path, method=request.method, keep_alive=keep_alive, config=config)
    except BadRequest:
        return error_result(request.version, 400, request_path, method=request.method, keep_alive=False, config=config)

    if file_info is None:
        return error_result(request.version, 404, request_path, method=request.method, keep_alive=keep_alive, config=config)

    if file_info.is_private and request.header("Authorization") != config.basic_auth_token:
        return error_result(request.version, 403, request_path, method=request.method, keep_alive=keep_alive, config=config)

    if not accepts_content_type(request.header("Accept"), file_info.content_type):
        return error_result(request.version, 415, request_path, method=request.method, keep_alive=keep_alive, config=config)

    last_modified = formatdate(file_info.modified_time, usegmt=True)
    if is_not_modified(request.header("If-Modified-Since"), file_info.modified_time):
        response, date_header = make_response(
            request.version,
            304,
            headers={"Last-Modified": last_modified},
            body=b"",
            method=request.method,
            keep_alive=keep_alive,
            config=config,
        )
        return ResponseResult(response, keep_alive, request_path, 304, STATUS_REASONS[304], date_header)

    body = file_info.path.read_bytes()
    response, date_header = make_response(
        request.version,
        200,
        headers={
            "Content-Type": file_info.content_type,
            "Accept-Ranges": "bytes",
            "Last-Modified": last_modified,
        },
        body=body,
        method=request.method,
        keep_alive=keep_alive,
        config=config,
    )
    return ResponseResult(response, keep_alive, request_path, 200, STATUS_REASONS[200], date_header)


def log(clientIP, accessTime, url, loggingMessage, logFile=DEFAULT_LOG_FILE):
    log_path = Path(logFile)
    if log_path.parent != Path("."):
        log_path.parent.mkdir(parents=True, exist_ok=True)
    with _log_lock:
        with open(log_path, "a", encoding="utf-8") as file:
            file.write(
                f"Connection from client IP: {clientIP}\n"
                f"Access time: {accessTime}\n"
                f"Request file: {url}\n"
                f"Response: {loggingMessage}\n\n\n"
            )


def serverProcess(connectionSocket, clientAddress, config=None):
    if config is None:
        config = ServerConfig()

    buffer = b""
    connectionSocket.settimeout(config.keep_alive_timeout)
    try:
        while True:
            try:
                raw_request, buffer = read_next_request(connectionSocket, buffer)
            except socket.timeout:
                break
            except BadRequest:
                result = error_result("HTTP/1.1", 400, "-", keep_alive=False, config=config)
                connectionSocket.sendall(result.response)
                log(clientAddress, result.date_header, result.request_path, "400 Bad Request", config.log_file)
                break

            if raw_request is None:
                break

            result = build_response(raw_request, config)
            connectionSocket.sendall(result.response)
            log(
                clientAddress,
                result.date_header,
                result.request_path,
                f"{result.status_code} {result.reason}",
                config.log_file,
            )

            if not result.keep_alive:
                break
    finally:
        connectionSocket.close()


class ThreadedHTTPServer:
    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, config=None):
        self.config = config or ServerConfig()
        self._shutdown = threading.Event()
        self._threads = []
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind((host, port))
        self._server_socket.listen(5)
        self._server_socket.settimeout(0.5)

    @property
    def server_address(self):
        return self._server_socket.getsockname()

    def serve_forever(self):
        try:
            while not self._shutdown.is_set():
                try:
                    connectionSocket, clientAddress = self._server_socket.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                clientThread = threading.Thread(
                    target=serverProcess,
                    args=(connectionSocket, clientAddress, self.config),
                    daemon=True,
                )
                clientThread.start()
                self._threads.append(clientThread)
        finally:
            self._server_socket.close()

    def shutdown(self):
        self._shutdown.set()
        try:
            socket.create_connection(self.server_address, timeout=0.2).close()
        except OSError:
            pass
        try:
            self._server_socket.close()
        except OSError:
            pass
        for clientThread in self._threads:
            clientThread.join(timeout=1)


def serverInit(
    serverAddress=DEFAULT_HOST,
    serverPort=DEFAULT_PORT,
    public_dir=DEFAULT_PUBLIC_DIR,
    private_dir=DEFAULT_PRIVATE_DIR,
    log_file=DEFAULT_LOG_FILE,
    username=DEFAULT_USERNAME,
    password=DEFAULT_PASSWORD,
    keep_alive_timeout=DEFAULT_KEEP_ALIVE_TIMEOUT,
):
    config = ServerConfig(
        public_dir=public_dir,
        private_dir=private_dir,
        log_file=log_file,
        username=username,
        password=password,
        keep_alive_timeout=keep_alive_timeout,
    )
    server = ThreadedHTTPServer(serverAddress, serverPort, config)
    host, port = server.server_address
    print(f"Server initiated\nServer IP: {host}, Server Port: {port}\n\n\n")
    server.serve_forever()


def parse_args():
    parser = argparse.ArgumentParser(description="Run a raw-socket HTTP file server.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Server host to bind.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Server port to bind.")
    parser.add_argument("--public-dir", default=DEFAULT_PUBLIC_DIR, help="Directory for public files.")
    parser.add_argument("--private-dir", default=DEFAULT_PRIVATE_DIR, help="Directory for private files.")
    parser.add_argument("--log-file", default=DEFAULT_LOG_FILE, help="Path to the access log file.")
    parser.add_argument("--username", default=DEFAULT_USERNAME, help="Basic auth username for private files.")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="Basic auth password for private files.")
    parser.add_argument(
        "--keep-alive-timeout",
        type=int,
        default=DEFAULT_KEEP_ALIVE_TIMEOUT,
        help="Seconds to wait for the next request on a keep-alive connection.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    serverInit(
        serverAddress=args.host,
        serverPort=args.port,
        public_dir=args.public_dir,
        private_dir=args.private_dir,
        log_file=args.log_file,
        username=args.username,
        password=args.password,
        keep_alive_timeout=args.keep_alive_timeout,
    )
