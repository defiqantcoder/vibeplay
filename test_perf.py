import time
from urllib.request import urlopen, Request
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import json

class MockHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.send_response(200)
        self.end_headers()

def run_server():
    server = HTTPServer(('127.0.0.1', 8765), MockHandler)
    server.handle_request()

server_thread = threading.Thread(target=run_server)
server_thread.daemon = True
server_thread.start()

time.sleep(0.5)

from vibeplay.desktop.mime import forward_uris_to_running_instance

start = time.perf_counter()
res = forward_uris_to_running_instance(["/tmp/a.flac"])
end = time.perf_counter()
print(f"Time: {end - start:.5f}s, res: {res}")
