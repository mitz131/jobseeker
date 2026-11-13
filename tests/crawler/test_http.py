"""HttpClient against a real local server: decoding, and the size and time limits."""

import gzip
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from jobseeker.crawler.http import HttpClient

MB = 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        route = {
            "/text": lambda: self.reply("Genève".encode(), "text/html"),            # no charset: UTF-8
            "/latin1": lambda: self.reply("Genève".encode("latin-1"), "text/html; charset=ISO-8859-1"),
            "/json": lambda: self.reply(json.dumps({"city": "Zürich"}).encode(), "application/json"),
            "/big": lambda: self.reply(b"x" * (3 * MB), "text/html"),
            # 3 MB of zeros, about 3 KB on the wire: only the unpacked size counts
            "/bomb": lambda: self.reply(gzip.compress(b"0" * (3 * MB)), "text/html", gzip=True),
            "/slow": self.trickle,
            "/missing": lambda: self.reply(b"no such job", "text/plain", status=404),
        }[self.path]
        route()

    def reply(self, body, content_type, status=200, gzip=False):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        if gzip:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def trickle(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", "1000")
        self.end_headers()
        try:
            for _ in range(1000):   # one byte every 0.1 s: never silent long enough for `timeout`
                self.wfile.write(b"x")
                self.wfile.flush()
                time.sleep(0.1)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


@pytest.fixture
def client(monkeypatch):
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(var, raising=False)   # the test server is local
    return HttpClient(delay=0, retries=0, max_bytes=2 * MB, max_seconds=1)


def test_text_and_json(server, client):
    assert client.get_text(f"{server}/text") == "Genève"
    assert client.get_text(f"{server}/latin1") == "Genève"
    assert client.get_json(f"{server}/json") == {"city": "Zürich"}


def test_too_big(server, client):
    with pytest.raises(RuntimeError, match="over 2 MB"):
        client.get_text(f"{server}/big")


def test_gzip_bomb_counts_the_unpacked_size(server, client):
    with pytest.raises(RuntimeError, match="over 2 MB"):
        client.get_text(f"{server}/bomb")


def test_trickling_server_hits_the_total_time_limit(server, client):
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="took over 1 s"):
        client.get_text(f"{server}/slow")
    assert time.monotonic() - started < 5


def test_http_error_quotes_the_body(server, client):
    with pytest.raises(RuntimeError, match="HTTP 404 .*no such job"):
        client.get_text(f"{server}/missing")
