import time
import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import httpx

# baseline mock logic
class MockHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        # simulate slow response
        time.sleep(0.5)
        self.send_response(200)
        self.end_headers()

def run_server():
    server = HTTPServer(('127.0.0.1', 8769), MockHandler)
    server.handle_request()

server_thread = threading.Thread(target=run_server)
server_thread.daemon = True
server_thread.start()

# wait for server to start
time.sleep(0.5)

from vibeplay.desktop.mime import forward_uris_to_running_instance
import urllib.request
import json

def urllib_version():
    req = urllib.request.Request("http://127.0.0.1:8769/api/desktop/open", data=b'{"uris":[]}', method="POST")
    urllib.request.urlopen(req)

async def test_urllib_blocking():
    loop = asyncio.get_running_loop()
    start_time = loop.time()

    # We will schedule a timer that should execute immediately.
    # If the main thread is blocked by urllib, the timer will be delayed.
    async def fast_timer():
        await asyncio.sleep(0.01)
        return loop.time()

    t1 = asyncio.create_task(fast_timer())

    # run blocking synchronous call in the event loop (BAD practice, simulating the bug)
    try:
        urllib_version()
    except Exception:
        pass

    timer_end = await t1
    return timer_end - start_time

async def test_httpx_async():
    loop = asyncio.get_running_loop()
    start_time = loop.time()

    async def fast_timer():
        await asyncio.sleep(0.01)
        return loop.time()

    t1 = asyncio.create_task(fast_timer())

    await forward_uris_to_running_instance(["/tmp/a.flac"], port=8769)

    timer_end = await t1
    return timer_end - start_time


async def main():
    blocking_delay = await test_urllib_blocking()
    # Need to restart server thread
    server_thread2 = threading.Thread(target=run_server)
    server_thread2.daemon = True
    server_thread2.start()
    time.sleep(0.5)

    async_delay = await test_httpx_async()

    print(f"URLLib Event Loop Blockage Delay: {blocking_delay:.3f}s")
    print(f"HTTPX Async Event Loop Blockage Delay: {async_delay:.3f}s")

asyncio.run(main())
