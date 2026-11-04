import time
import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

class MockHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.send_response(200)
        self.end_headers()

def run_server():
    server = HTTPServer(('127.0.0.1', 8768), MockHandler)
    server.handle_request()

server_thread = threading.Thread(target=run_server)
server_thread.daemon = True
server_thread.start()

time.sleep(0.5)

from vibeplay.desktop.mime import forward_uris_to_running_instance

async def run_it():
    start = time.perf_counter()
    res = await forward_uris_to_running_instance(["/tmp/a.flac"], port=8768)
    end = time.perf_counter()
    print(f"Time (httpx async): {end - start:.5f}s, res: {res}")

asyncio.run(run_it())
