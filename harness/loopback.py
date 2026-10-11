"""HTTP servers for loopback that bind without a reverse DNS lookup (#711)."""
import http.server
import socketserver


class _NoReverseDNS:
    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class HTTPServer(_NoReverseDNS, http.server.HTTPServer):
    pass


class ThreadingHTTPServer(_NoReverseDNS, http.server.ThreadingHTTPServer):
    pass
