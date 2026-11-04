import time
import httpx
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging

def forward_uris_to_running_instance_httpx(uris, host="127.0.0.1", port=8765, token=None, timeout=1.5):
    url = f"http://{host}:{port}/api/desktop/open"
    body = {"uris": list(uris)}
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if token:
        headers["X-API-Key"] = token
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=body, headers=headers)
            return resp.status_code == 200
    except Exception as e:
        return False

class MockHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.send_response(200)
        self.end_headers()

def run_server():
    server = HTTPServer(('127.0.0.1', 8766), MockHandler)
    server.handle_request()

server_thread = threading.Thread(target=run_server)
server_thread.daemon = True
server_thread.start()

time.sleep(0.5)


start = time.perf_counter()
res = forward_uris_to_running_instance_httpx(["/tmp/a.flac"], port=8766)
end = time.perf_counter()
print(f"Time: {end - start:.5f}s, res: {res}")
