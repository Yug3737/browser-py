# file: main.py
# author: Yug Patel
# last modified: 9 December 2025

import gzip
import ssl
import socket
import tkinter
from datetime import datetime, timedelta

# stores (host, port) keys and previously used socket objects
socket_cache = {}
# stores urls as keys and values as dicts with these keys:
# status_code, response_headers, body, timestamp, max_age
# dict of dicts
response_cache = {}
REDIRECT_LIMIT = 5

class URL:
    def __init__(self, url):
        """
        Initilize the following variables(in order from left to right in the URL):
            metascheme: allows view-source
            scheme: allows http, https, file, data
            host: host part of the URL
            port: mentioning a port is optional
            path: everything following port is considered part of the path

        Currently urls for data:text, file:/// do not allow a port in the url.
        """
        self.url = url

        if url is None:
            self.metascheme = None
            self.scheme = None
            self.host = None
            self.port = None
            self.path = None
            return

        # check for data scheme first, because it needs to be handled differently
        if url.startswith("data"): # example, "data:text/html, Hello world"
            self.metascheme = None
            self.scheme, self.path = url.split(":", 1)
            self.host = None
            self.port = None
            return
        
        # check for view-source, example: "view-source:https://example.org/"
        if url.startswith("view-source:"):
            self.metascheme = "view-source"
            remaining_url = url[len("view-source:"):]

            # split scheme
            self.scheme, rest = remaining_url.split("://", 1)

            # split host and path
            if "/" in rest:
                self.host, path = rest.split("/", 1)
                self.path = "/" + path
            else:
                self.host = rest
                self.path = "/"

            self.port = 443 if self.scheme == "https" else 80
            return

        self.metascheme = None
        self.scheme, url = url.split("://", 1)
        assert self.scheme in ["http", "https", "file", "data"], "Invalid url scheme provided"

        if self.scheme == "http":
            self.port = 80
        elif self.scheme == "https":
            self.port = 443

        if not "/" in url:
            url += "/"
        self.host, url = url.split("/", 1)
        if ":" in self.host:
            self.host, port = self.host.split(":", 1)
            self.port = int(port)

        self.path = "/" + url

    def read_chunked(response):
        """
        Read a chunked-encoded HTTP body.
        Returns raw bytes (exactly what was shared by the server)
        """
        chunks = []

        while True:
            size_line = response.readline().decode("ascii").strip()
            chunk_size = int(size_line, 16)

            if chunk_size == 0:
                response.readline()
                break

            chunk = response.read(chunk_size)
            chunks.append(chunk)

            response.readline()

        return b"".join(chunks)

    def read_http_body(self, response, headers):
        """
        Returns raw bytes of the full HTTP body, handling content-length, chunked encoding and gzip.
        Uses read_chunked method.
        """

        # step 1: read trasnport encoding (chunked or content-length)
        if headers.get("transfer-encoding") == "chunked":
            # server is sending chunks
            raw = self.read_chunked(response)
        elif "content-length" in headers:
            # server tells us exactly how many bytes to read
            length = int(headers["content-length"])
            raw = response.read(length)

        else:
            # neither chunked nor content-length, read until connection closes
            # allowed for HTTP 1.0
            raw = response.read()
        
        # Step 2: handle content encodinng (gzip compression)
        if headers.get("content-encoding") == "gzip":
            # this means, raw contains compressed bytes which need to be decompressed
            raw = gzip.decompress(raw)
        return raw

    def request(self, redirects_remaining=REDIRECT_LIMIT):
        """
        Handles the url's request depending on the scheme/metascheme.
        For data, the content returned is text that follows "," in the url.
        For file:///, file contents on the local machine are returned.
        For view-source and all other schemes, a socket wrapped in ssl context is created to 
            request data from the given URL.
        """

        # no need to make a socket connection if opening a local file
        if self.scheme == "file":
            self.path = self.path.split("/", 1)[1] # remove the extra / from beginning of "file:///path_to_file" type urls
            f = open(self.path, "r", encoding="utf8")
            return f.read()

        if self.scheme == "data":
            content_type, content = self.path.split(",", 1)
            assert content_type == "text/html", "when scheme is 'data', content_type must be 'text/html'"
            print(f"content {content}")
            return content
        
        # check response_cache before making a socket request or checking for active sockets
        if self.url in response_cache:
            max_age = response_cache[self.url]["max_age"]
            if not max_age:
                raise Exception("max_age is stored in response cache for url: {url} but is None. URLs with no max_age should not be cached.")

            max_age = timedelta(seconds=max_age)
            
            # is the cached response fresh enough?
            if datetime.now() - response_cache[self.url]["timestamp"] <= max_age:
                print("Returning cached response ------------------------")
                return response_cache[self.url]["content"].decode("utf8", errors="replace")

        # no need to split anything here
        if getattr(self, "metascheme", None) == "view-source":
            self.path = "/" + (self.path if self.path else "")

        key = (self.host, self.port)

        # try reusing existing socket
        if key in socket_cache:
            s = socket_cache[key]
            try:
                s.send(b"")
            except OSError:
                # closed by server, need to recreate
                s = socket.socket(
                        family=socket.AF_INET,
                        type=socket.SOCK_STREAM,
                        proto=socket.IPPROTO_TCP,
                        )
                s.connect(key)
                if self.scheme == "https":
                    ctx = ssl.create_default_context()
                    s = ctx.wrap_socket(s, server_hostname=self.host)

                socket_cache[key] = s
        else:
            # create new socket, connect, wrap
            s = socket.socket(
                    family=socket.AF_INET,
                    type=socket.SOCK_STREAM,
                    proto=socket.IPPROTO_TCP,
                    )

            s.connect(key)
            if self.scheme == "https":
                ctx = ssl.create_default_context()
                s = ctx.wrap_socket(s, server_hostname=self.host)

            socket_cache[key] = s

        method = "GET"
        request = f"{method} {self.path} HTTP/1.0\r\n"
        request += f"Host: {self.host}\r\n"
        request += f"Connection: keep-alive\r\n"
        request += f"User-Agent: yug-patel-browser\r\n"
        request += f"Accept-Encoding: gzip\r\n"
        request += "\r\n"

        s.send(request.encode("utf8"))

        # makefile gives us a file like object which is decoded with utf8 back to a string
        response = s.makefile("rb")

        statusline = response.readline().decode("ascii")
        version, status, explanation = statusline.split(" ", 2)
        status = int(status)
        
        # read response headers
        response_headers = {}
        while True:
            line = response.readline().decode("ascii")
            if line == "\r\n": break
            header, value = line.split(":", 1)
            response_headers[header.casefold()] = value.strip()

        # redirect handling
        if 300 <= status <= 399:
            if "location" not in response_headers:
                raise Exception("Redirect with no location header.")

            new_url = response_headers["location"]

            # if relative path, build full path
            if new_url.startswith("/"):
                new_url = f"{self.scheme}://{self.host}{new_url}"

            # enforce redirect limit:
            if redirects_remaining == 0:
                raise Exception("Redirect limit of {REDIRECT_LIMIT} reached.")

            # recursive call
            redirected = URL(new_url)
            return redirected.request(redirects_remaining - 1)
        
        # not asserting http version is same as ours, because many misconfigured servers respond in 1.1 when we talk to them with 1.0

        
        # content_length = int(response_headers["content-length"])
        # content = response.read(content_length)

        raw_bytes = self.read_http_body(response, response_headers)
        content = raw_bytes.decode("utf8", errors="replace")

        # not closing the socket but keeping it alive

        # caching (no-store and max-age)
        directives_str = response_headers.get("cache-control", None)
        if not directives_str:
            return content

        # print("caching directives ", directives_str)

        if (method == "GET" and status in [200, 301, 404]):
            supported = ["max-age", "no-store"]

            if directives_str:
                directives = [dir.strip() for dir in directives_str.split(",")]
                
                # no caching if encounter an unsupported directive
                directive_names = []
                for dir in directives:
                    name = dir.split("=")[0]
                    directive_names.append(name)

                for dir_name in directive_names:
                    if dir_name not in supported:
                        return content.decode("utf8", errors="replace")

                # reject if no-store
                if "no-store" in directives_str:
                    return content

                # extract max_age value
                max_age = None
                for dir in directives:
                    if "max-age" == dir.split("=")[0]:
                        max_age = int(dir.split("=")[1])
                # print(f"max_age obtained to be {max_age}")

                if max_age is not None:
                    response_cache[self.url] = {
                            "status_code": status,
                            "response_headers": response_headers,
                            "content": content,
                            "timestamp": datetime.now(),
                            "max_age": max_age
                    }

        return content # is already decoded

def lex(body):
    text = ""

    in_tag = False
    i = 0
    while i < len(body):
        c = body[i]
        if c == "&" and not in_tag:
            prospective_entity = c
            # grab the next 3 chars too and check if we have a valid entity sequence
            prospective_entity = body[i:i+4]
            if prospective_entity == "&lt;":
                text += "<"
                # print("<", end="")
                i += 4
                continue
            elif prospective_entity == "&gt;":
                text += ">"
                # print(">", end="")
                i += 4
                continue

        if c == "<":
            in_tag = True
        elif c == ">":
            in_tag = False
        elif not in_tag:
            text += c
            # print(c, end="")
        i += 1
    return text


#     while i < len(body):
#         c = body[i]
#         if c == "&" and not in_tag:
#             prospective_entity = c
#             # grab the next 3 chars too and check if we have a valid entity sequence
#             prospective_entity = body[i:i+4]
#             if prospective_entity == "&lt;":
#                 print("<", end="")
#                 i += 4
#                 continue
#             elif prospective_entity == "&gt;":
#                 print(">", end="")
#                 i += 4
#                 continue
#
#         if c == "<":
#             in_tag = True
#         elif c == ">":
#             in_tag = False
#         elif not in_tag:
#             print(c, end="")
#         i += 1

def lex_source(body):
    return body

def show_source(body):
    """
    Print the source body as it is. Used for view-source metascheme.
    """
    for c in body:
        print(c, end="")



WIDTH, HEIGHT = 800, 600

class Browser:
    def __init__(self):
        self.window = tkinter.Tk()
        self.canvas = tkinter.Canvas(
                self.window,
                width=WIDTH,
                height=HEIGHT
                )
        self.canvas.pack()

    def load(self, url):
        """
        Calls request() in the given url string and displays the body returned.
        """

        body = url.request(REDIRECT_LIMIT)
        text = ""
        if url.metascheme and url.metascheme == "view-source":
            text = lex_souce(body)
        else:
            text = lex(body)
            

        HSTEP, VSTEP = 13, 18
        cursor_x, cursor_y = HSTEP, VSTEP
        for c in text:
            self.canvas.create_text(cursor_x, cursor_y, text=c)
            cursor_x += HSTEP
            if cursor_x + HSTEP >= WIDTH:
                cursor_y += VSTEP
                cursor_x = HSTEP


if __name__ == "__main__":
    import sys
    Browser().load(URL(sys.argv[1]))
    tkinter.mainloop()
