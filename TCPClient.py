import argparse
import socket
import sys


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 12346


def parse_header(header_value):
    if ":" not in header_value:
        raise argparse.ArgumentTypeError("Headers must use 'Name: value' format.")
    name, value = header_value.split(":", 1)
    name = name.strip()
    if not name:
        raise argparse.ArgumentTypeError("Header name cannot be empty.")
    return name, value.strip()


def build_request(method, path, host, headers=None, body=b"", keep_alive=False):
    if headers is None:
        headers = []
    if isinstance(body, str):
        body = body.encode("utf-8")
    if not path.startswith("/"):
        path = "/" + path

    header_map = {name.lower(): (name, value) for name, value in headers}
    if "host" not in header_map:
        header_map["host"] = ("Host", host)
    if "connection" not in header_map:
        header_map["connection"] = ("Connection", "keep-alive" if keep_alive else "close")
    if body and "content-length" not in header_map:
        header_map["content-length"] = ("Content-Length", str(len(body)))

    request_lines = [f"{method.upper()} {path} HTTP/1.1"]
    request_lines.extend(f"{name}: {value}" for name, value in header_map.values())
    request_head = "\r\n".join(request_lines).encode("iso-8859-1") + b"\r\n\r\n"
    return request_head + body


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


def read_response(client_socket):
    buffer = b""
    while find_header_end(buffer) is None:
        chunk = client_socket.recv(4096)
        if not chunk:
            break
        buffer += chunk

    header_end = find_header_end(buffer)
    if header_end is None:
        return buffer, b""

    index, delimiter_length = header_end
    response_head = buffer[: index + delimiter_length]
    body = buffer[index + delimiter_length:]
    headers = parse_response_headers(response_head)
    content_length = headers.get("content-length")

    if content_length is not None:
        expected_length = int(content_length)
        while len(body) < expected_length:
            chunk = client_socket.recv(4096)
            if not chunk:
                break
            body += chunk
        body = body[:expected_length]
    else:
        while True:
            chunk = client_socket.recv(4096)
            if not chunk:
                break
            body += chunk

    return response_head, body


def parse_response_headers(response_head):
    text = response_head.decode("iso-8859-1", errors="replace")
    headers = {}
    for line in text.splitlines()[1:]:
        if not line or ":" not in line:
            continue
        name, value = line.split(":", 1)
        headers[name.lower()] = value.strip()
    return headers


def print_response(response_head, body, output_path=None):
    sys.stdout.write(response_head.decode("iso-8859-1", errors="replace"))
    if output_path:
        with open(output_path, "wb") as output_file:
            output_file.write(body)
        sys.stdout.write(f"\nSaved response body to {output_path}\n")
        return
    sys.stdout.write(body.decode("utf-8", errors="replace"))


def parse_args():
    parser = argparse.ArgumentParser(description="Send one raw HTTP request over a TCP socket.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Server host.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Server port.")
    parser.add_argument("--method", default="GET", help="HTTP method.")
    parser.add_argument("--path", default="/", help="Request path.")
    parser.add_argument("--header", action="append", type=parse_header, default=[], help="HTTP header, for example 'Accept: text/html'.")
    parser.add_argument("--body", default="", help="Request body text.")
    parser.add_argument("--keep-alive", action="store_true", help="Send Connection: keep-alive.")
    parser.add_argument("--timeout", type=float, default=10, help="Socket timeout in seconds.")
    parser.add_argument("--output", help="Write the response body to this file.")
    return parser.parse_args()


def main():
    args = parse_args()
    request = build_request(
        method=args.method,
        path=args.path,
        host=args.host,
        headers=args.header,
        body=args.body,
        keep_alive=args.keep_alive,
    )
    with socket.create_connection((args.host, args.port), timeout=args.timeout) as client_socket:
        client_socket.settimeout(args.timeout)
        client_socket.sendall(request)
        response_head, body = read_response(client_socket)
    print_response(response_head, body, args.output)


if __name__ == "__main__":
    main()
