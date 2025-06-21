import socket
import os
import threading
import mimetypes
import datetime
import time

isPresistent = False
isClosedConnection = False
PRIVATE_BASIC_TOKEN = "Basic dXNlcm5hbWU6cGFzc3dvcmQ="  # currently the only authorization token


def serverProcess(connectionSocket, clientAddress):
    try:
        global isPresistent
        global isClosedConnection
        requestMes = connectionSocket.recv(2048).decode()
        time.sleep(1)   # wait for message transport
        requestMesLine = requestMes.splitlines()
        responseMessage = messageHandler(requestMesLine, connectionSocket, clientAddress)
        connectionSocket.send(responseMessage.encode())
        if not isPresistent:        # non presistent -> close connection (Connection: close)
            connectionSocket.close()
        # else presistent -> keep connection

    except Exception as e:       # 400 Bad Request
        responseMessage = messageHandler(requestMesLine, connectionSocket, clientAddress)
        connectionSocket.send(responseMessage.encode())

def getTime():
    return datetime.datetime.now(datetime.UTC)

def fileModified(lastModifiedTime, ifModifiedSince):            # compare file last modified time to If-Modified-Since Header and formatting
    lastModifiedTimestamp = datetime.datetime.strptime(lastModifiedTime, "%a %b %d %H:%M:%S %Y")
    ifModifiedSinceTimestamp = datetime.datetime.strptime(ifModifiedSince, "%a, %d %b %Y %H:%M:%S %Z")
    lastModifiedTimeFormated = lastModifiedTimestamp.strftime("%a, %d %b %Y %H:%M:%S GMT")
    if lastModifiedTimestamp > ifModifiedSinceTimestamp: return True, lastModifiedTimeFormated
    else: return False, lastModifiedTimeFormated

def findFile(url):          # file searching process
    absolutePrivateFolderPath = os.path.abspath("./private")
    absolutefilePath = os.path.abspath(url)
    content = ""

    if os.path.exists(absolutefilePath):
        isPrivate = (os.path.commonpath([absolutefilePath, absolutePrivateFolderPath]) == absolutePrivateFolderPath)
        fileType, _ = mimetypes.guess_type(absolutefilePath)

        if fileType and fileType.startswith('text/'):
            with open(absolutefilePath, 'r') as file:
                content = str(file.read())
        elif fileType and fileType.startswith('image/'):
            with open(absolutefilePath, 'rb') as file:
                content = str(file.read())
        lastModifiedTimestamp = os.path.getmtime(absolutefilePath)
        lastModifiedTime = time.ctime(lastModifiedTimestamp)

        return content, os.path.getsize(absolutefilePath), lastModifiedTime, fileType, True, isPrivate
    return None, None, None, None, False, False

def messageHandler(requestMesLine, connectionSocket, clientAddress):
    global isPresistent         # presistent control variable
    global isClosedConnection
    
    statusCode = ""
    statusPhase = ""
    version = "HTTP/1.1"    # default server side HTTP version
    
    endLine = "\r\n"            # general headers
    time = getTime()
    timeStr = f"{time.strftime("%a, %d %b %Y %X")} GMT"
    server = "MyServer/1.0"
    acceptRange = "bytes"

    try:
        requestLine = requestMesLine[0].split()     # get reqestion line args
        method = requestLine[0]
        url = '.' + requestLine[1]
        version = requestLine[2]
        
        headerDict = {}                     # put reqestion headers in hash map
        for i in range(1, len(requestMesLine)-1):
            headerDict[requestMesLine[i].split(':')[0]] = requestMesLine[i].split(':', 1)[1][1:]

        if "Connection" in headerDict:       # check if the connection is presistent and change control variable
            if headerDict["Connection"] == "keep-alive":
                isPresistent = True
                isClosedConnection = False
                connectionSocket.settimeout(30)
            elif headerDict["Connection"] == "close":
                isPresistent = False
                isClosedConnection = True
        else:
            isPresistent = False
            isClosedConnection = False

        # server default supported file type (if request has no "Accept:" header)
        requestFileTypeset = {'text/plain', 'text/html', 'text/css', 'text/javascript', 'image/jpeg', 'image/png', 'image/gif'}
        if "Accept" in headerDict:
            requestFileType = headerDict["Accept"].split(',')        # create request file type set
            requestFileTypeset = set(item.strip() for item in requestFileType)

        body, fileSize, lastModifiedTime, fileType, fileIsExist, fileIsPrvate = findFile(url)       # get file information

        authorizedUser = True
        if "Authorization" in headerDict and fileIsPrvate:      # checking user's authorization if file in private file is requested
            authorizedUser = True if headerDict["Authorization"] == PRIVATE_BASIC_TOKEN else False

        if "If-Modified-Since" in headerDict and fileIsExist:
            ifModifiedSince = headerDict["If-Modified-Since"]
            isModified, lastModifiedTime = fileModified(lastModifiedTime, ifModifiedSince)
        else:
            isModified = True

        if fileIsExist:
            if not authorizedUser:  # 403 Forbidden
                statusCode = "403"
                statusPhase = "Forbidden" 
                body = "You have no access to this file."
                fileSize = len(body)
            elif fileType in requestFileTypeset and isModified:  # 200 OK
                statusCode = "200"
                statusPhase = "OK"           
            elif fileType in requestFileTypeset and not isModified:     # 304 Not Modified
                statusCode = "304"
                statusPhase = "Not Modified"
            else:                               # 415 Unsupported media type
                statusCode = "415"
                statusPhase = "Unsupported Media Type"
                body = statusCode + ' ' + statusPhase
                fileType = "text/plain"
                fileSize = len(body)
        else:
            statusCode = "404"      # 404 Not Found
            statusPhase = "Not Found"
            body = statusCode + ' ' + statusPhase
            fileType = "text/plain"
            fileSize = len(body)

        statusLine = f"{version} {statusCode} {statusPhase}{endLine}"
        header = f"Date: {timeStr}{endLine}Server: {server}{endLine}Content-Type: {fileType}{endLine}Accept-Ranges: {acceptRange}{endLine}Content-Length: {fileSize}{endLine}"

        if isPresistent:            # adding additional headers
            header += f"Connection: keep-alive{endLine}"
        elif isClosedConnection:
            header += f"Connection: close{endLine}"
        elif "If-Modified-Since" in headerDict and fileIsExist:
            header += f"Last-Modified: {lastModifiedTime}{endLine}"

        loggingMessage = f"{statusCode} {statusPhase}"
        log(clientAddress, timeStr, url, loggingMessage)       # logging

        if method == "GET":
            return statusLine + header + endLine + body   # for GET method
        elif method == "HEAD":
            return statusLine + header      # for HEAD method
        
        raise Exception("Unexpected error occurred")
            
    except socket.timeout:      #timeout
        isPresistent = False
        isClosedConnection = False
        loggingMessage = "Connection timeout"
        log(clientAddress, timeStr, url, loggingMessage)
    
    except Exception as e:      # 400 Bad Request
        isPresistent = False
        isClosedConnection = False
        statusCode = "400"
        statusPhase = "Bad request"
        body = "Unexpected error occurred"
        fileSize = len(body)

        statusLine = f"{version} {statusCode} {statusPhase}{endLine}"
        header = f"Date: {timeStr}{endLine}Server: {server}{endLine}Content-Type: text/plain{endLine}Accept-Ranges: {acceptRange}{endLine}Content-Length: {fileSize}{endLine}{endLine}"

        loggingMessage = f"{statusCode} {statusPhase}"
        log(clientAddress, timeStr, url, loggingMessage)       # logging

        if method == "HEAD":
            return statusLine + header
        else:       # default method = GET and return body part in 400 situation
            return statusLine + header + endLine + body

def log(clientIP, accessTime, url, loggingMessage):
    logFile = "server_log.txt"
    with open(logFile, 'a') as f:
        f.write(f"Connection from client IP: {clientIP}\nAccess time: {accessTime}\nRequest file: {url}\nResponse: {loggingMessage}\n\n\n")
        f.close()

def serverInit(serverAddress='127.0.0.1', serverPort=12346):
    serverSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    serverSocket.bind((serverAddress, serverPort))
    print(f"Server initiated\nServer IP: {serverAddress}, Server Port: {serverPort}\n\n\n")
    serverSocket.listen(5)      # maximum 5 queueing clients
    while True:
        connectionSocket, clientAddress = serverSocket.accept()
        clientThread = threading.Thread(target=serverProcess, args=(connectionSocket, clientAddress))   # mulit-threading
        clientThread.start()

if __name__ == "__main__":
    serverInit()