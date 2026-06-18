# Multi-thread Raw-Socket HTTP Server

This project is an educational HTTP/1.1 file server built directly on Python TCP sockets. It supports concurrent clients, `GET` and `HEAD`, persistent connections, basic authentication for private files, MIME detection, conditional requests, and access logging.

## Features

- Serves files from configurable public and private directories.
- Uses one thread per accepted TCP connection.
- Handles `Connection: keep-alive` and `Connection: close`.
- Protects `/private/...` URLs with Basic authentication.
- Sends byte-correct text and binary responses.
- Supports `If-Modified-Since` and returns `304 Not Modified`.
- Rejects malformed requests, unsupported methods, unsupported media types, and path traversal attempts.
- Includes a reusable TCP client and automated tests.

## Layout

The default server expects these content directories:

```text
public/
private/
```

URL mapping:

- `/public/file.html` maps to `public/file.html`.
- `/private/file.html` maps to `private/file.html`.
- `/file.html` also maps to `public/file.html`.
- `/` maps to `public/index.html`.

The repository includes `server_log.txt` as a sample log. The default server appends to `server_log.txt`; use `--log-file` if you want runtime logs somewhere else.

## Run The Server

```bash
python3 TCPServer.py --host 127.0.0.1 --port 12346 --public-dir public --private-dir private
```

Useful options:

```bash
python3 TCPServer.py \
  --host 127.0.0.1 \
  --port 12346 \
  --public-dir public \
  --private-dir private \
  --log-file server_log.txt \
  --username username \
  --password password \
  --keep-alive-timeout 30
```

Create sample files before testing manually:

```bash
mkdir -p public private
printf '<h1>Hello</h1>\n' > public/file1.html
printf '<h1>Secret</h1>\n' > private/file2.html
```

## Open The Web Demo

The repository includes a light browser demo in `public/index.html`.

Start the server, then open:

```text
http://127.0.0.1:12346/
```

The demo lets you send sample `GET`, `HEAD`, private-file, conditional, and unsupported-method requests. It displays the request line, request headers, response status, response headers, response body, and request timing.

## Use The Client

Request a public file:

```bash
python3 TCPClient.py --host 127.0.0.1 --port 12346 --method GET --path /public/file1.html
```

Request a private file:

```bash
python3 TCPClient.py \
  --host 127.0.0.1 \
  --port 12346 \
  --method GET \
  --path /private/file2.html \
  --header 'Authorization: Basic dXNlcm5hbWU6cGFzc3dvcmQ='
```

Keep the connection alive for the response:

```bash
python3 TCPClient.py --path /public/file1.html --keep-alive
```

Save a binary response body:

```bash
python3 TCPClient.py --path /public/image.png --header 'Accept: image/*' --output image.png
```

## Tests

Run the automated test suite:

```bash
python3 -m unittest discover -s tests
```

The tests create temporary public/private directories and a temporary log file, then start the raw socket server on an ephemeral local port.

## Troubleshooting

- `404 Not Found`: confirm the requested URL maps to an existing file under `public/` or `private/`.
- `403 Forbidden`: private files require `Authorization: Basic dXNlcm5hbWU6cGFzc3dvcmQ=` with the default credentials.
- `415 Unsupported Media Type`: adjust the request `Accept` header or omit it.
- Connection hangs: send `Connection: close`, or make sure the client reads the response using `Content-Length`.
