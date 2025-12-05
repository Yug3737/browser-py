# file: main.py
# author: Yug Patel
# last modified: 3 December 2025

import ssl
import socket

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

    def request(self):
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
            return content
        
        # no need to split anything here
        if getattr(self, "metascheme", None) == "view-source":
            self.path = "/" + (self.path if self.path else "")

        s = socket.socket(
                family=socket.AF_INET,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
                )
        # tell the socket ot connect to host
        print(f"connecting host {self.host} and port {self.port}")
        s.connect((self.host, self.port))
        if self.scheme == "https":
            ctx = ssl.create_default_context()
            s = ctx.wrap_socket(s, server_hostname=self.host)

        request = f"GET {self.path} HTTP/1.0\r\n"
        request += f"Host: {self.host}\r\n"
        request += f"Connection: close\r\n"
        request += f"User-Agent: yug-patel-browser\r\n"
        request += "\r\n"

        print(request)
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
    """
    Read the html content obtained as a result of request method.
    Checks for entity sequences for > and < too.
    """

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

def show_source(body):
    """
    Print the source body as it is. Used for view-source metascheme.
    """
    for c in body:
        print(c, end="")

def load(url):
    """
    Calls request() in the given url string and displays the body returned.
    """

    body = url.request()
    if url.metascheme == "view-source":
        show_source(body)
    else:
        show(body)

if __name__ == "__main__":
    import sys
    load(URL(sys.argv[1]))
