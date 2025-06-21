Multi-thread HTTP Server

## Description
This project implements a simple multi-threaded HTTP server in Python. The server supports `GET` and `HEAD` methods, persistent connections, basic authentication for private files, and MIME type handling. It is compliant with HTTP/1.1 standards.

---

## Features
- **HTTP Methods**: 		Supports `GET` (file content) and `HEAD` (headers only).
- **Persistent Connections**: 	Handles `Connection: keep-alive` with a 30-second timeout.
- **Authorization**: 		Protects private files with a basic authentication token.
- **MIME Type Handling**: 	Dynamically determines file types.
- **Conditional Requests**: 	Processes `If-Modified-Since` headers.
- **Error Handling**: 		Returns appropriate HTTP status codes (`200`, `403`, `404`, etc.).
- **Logging**: 			Logs client interactions in `server_log.txt`.

---

## Usage
. Place public files in the `public` directory.
. Place private files in the `private` directory.
.  Run `TCPServer.py`
. The server listens on `127.0.0.1:12346` or `localhost:12346`.
. Use a tool like a python program to send HTTP requests (A python client sample is provided in the package, change the request message for testing)

---

## Log File
All client interactions are logged in `server_log.txt` with details: client IP, request time, requested file, and server response.
