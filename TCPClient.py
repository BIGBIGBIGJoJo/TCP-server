import socket

clientSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
serverName = '127.0.0.1'
serverPort = 12346
clientPort = 451
clientSocket.bind(('', clientPort))
clientSocket.connect((serverName, serverPort))

http_request = """GET /private/image.png http/1.1
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36
Accept: image/png
Accept-Language: en-US,en;q=0.9
Authorization: Basic dXNlcm5hbWU6cGFzc3dvcmQ=

"""

# add If-Modified-Since: Sun, 27 Apr 3000 10:00:00 GMT  ->  304 response
# add Connection: keep-alive / Connection: close  ->  start/close presisent connection
# request private file and remove Authorization header  ->  403 response
# request not exist file  ->  404 response
# remove Accept header  ->  415 response
# damage request message(e.g. change GET method to DAMAGED)  ->  400 response


clientSocket.send(http_request.encode())

print(clientSocket.recv(2048).decode())
    
clientSocket.close()
