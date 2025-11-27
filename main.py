# file: main.py
# author: Yug Patel
# last modified: 26 November 2025

import ssl
import socket

class URL:
    def __init__(self, url):
        """
        a url contains these properties: scheme, host, port, path
        """
        if url == None:
            self.scheme = None
            self.port = None
            self.host = None
            return

        # check for data scheme first, because it needs to be handled differently
        if url[:4] == "data": # example, "data:text/html, Hello world"
            self.scheme, self.path = url.split(":", 1)
            self.port = None
            self.host = None
            return
        
        # check for view-source, example: "view-source:https://example.org/"
        if url.split(":", 1) == "view-source":
            view_source, self.scheme, self.path = url.split(":", 2)
            self.path = self.path.split[2:] # get rid of initial "//" from path

        self.scheme, url = url.split("://", 1)
        # we only support http
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

    def request(self):
        # no need to make a socket connection if opening a local file
        if self.scheme == "file":
            self.path = self.path.split("/", 1)[1] # remove the extra / from beginning of "file:///path_to_file" type urls
            f = open(self.path, "r", encoding="utf8")
            return f.read()

        if self.scheme == "data":
            content_type, content = self.path.split(",", 1)
            assert content_type == "text/html", "scheme is data but content_type is not text/html"
            return content

        s = socket.socket(
                family=socket.AF_INET,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
                )
        # tell the socket ot connect to host
        s.connect((self.host, self.port))
        if self.scheme == "https":
            ctx = ssl.create_default_context()
            s = ctx.wrap_socket(s, server_hostname=self.host)

        request = f"GET {self.path} HTTP/1.0\r\n"
        request += f"Host: {self.host}\r\n"
        request += f"Connection: close\r\n"
        request += f"User-Agent: yug-patel-browser\r\n"
        request += "\r\n"
        s.send(request.encode("utf8"))

        # makefile gives us a file like object which is decoded with utf8 back to a string
        response = s.makefile("r", encoding="utf8", newline="\r\n")

        statusline = response.readline()
        version, status, explanation = statusline.split(" ", 2)
        
        # not asserting version is same as ours, because many misconfigured servers respond in 1.1 when we talk to them with 1.0

        response_headers = {}
        while True:
            line = response.readline()
            if line == "\r\n": break
            header, value = line.split(":", 1)
            response_headers[header.casefold()] = value.strip()

        assert "transfer-encoding" not in response_headers
        assert "content-encoding" not in response_headers

        content = response.read()
        s.close()

        return content

def show(body):
    in_tag = False
    i = 0
    while i < len(body):
        c = body[i]
        if c == "&" and not in_tag:
            prospective_entity = c
            # grab the next 3 chars too and check if we have a valid entity sequence
            prospective_entity = body[i:i+4]
            if prospective_entity == "&lt;":
                print("<", end="")
                i += 4
                continue
            elif prospective_entity == "&gt;":
                print(">", end="")
                i += 4
                continue

        if c == "<":
            in_tag = True
        elif c == ">":
            in_tag = False
        elif not in_tag:
            print(c, end="")
        i += 1

# "a &lt; b"

def show(body):
    in_tag = False
    for c in body:
        if c == "<":
            in_tag = True
        elif c == ">":
            in_tag = False
        elif not in_tag:
            print(c, end="")

def load(url):
    body = url.request()
    show(body)

if __name__ == "__main__":
    import sys
    load(URL(sys.argv[1]))
