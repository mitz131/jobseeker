"""HTTP client (requests) with retries, cookies and polite pacing.

Responses are read in pieces, up to a size and a time limit: a broken or hostile site
(a huge dump, a gzip bomb, a server that trickles one byte at a time) fails that
request instead of filling the memory or stalling the crawl.
"""

import json
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)
RETRY_STATUSES = (429, 500, 502, 503, 504)
MAX_BYTES = 20 * 1024 * 1024   # per response, after decompression; job pages are < 1 MB
MAX_SECONDS = 120              # per response, in total (`timeout` is per read: silence only)
CHUNK = 64 * 1024


class HttpClient:
    def __init__(self, delay: float = 0.5, timeout: float = 30, retries: int = 3,
                 max_bytes: int = MAX_BYTES, max_seconds: float = MAX_SECONDS):
        self.delay = delay
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.max_seconds = max_seconds
        self._last_request = 0.0
        # The session keeps cookies across requests: some sites tie their API to a session
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
        # Retry connection errors and transient statuses with backoff (4s, 8s, ...),
        # POST included: the search endpoints we post to don't change anything
        retry = Retry(total=retries, backoff_factor=2, status_forcelist=RETRY_STATUSES,
                      allowed_methods=None, raise_on_status=False)
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _request(self, method: str, url: str, **kwargs) -> tuple[requests.Response, bytes]:
        """The response (status, headers) and its body, decompressed."""
        wait = self.delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = started = time.monotonic()
        try:
            with self.session.request(method, url, timeout=self.timeout, stream=True, **kwargs) as resp:
                body = self._read_body(resp, url, started)
        except requests.RequestException as e:
            raise RuntimeError(f"Request failed for {url}: {e}") from e
        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code} for {url}: {body[:300].decode('utf-8', 'replace')}")
        return resp, body

    def _read_body(self, resp: requests.Response, url: str, started: float) -> bytes:
        body = bytearray()
        # read1: whatever has arrived (decompressed, at most CHUNK), so the limits are
        # checked while a slow or endless response is still coming in
        while chunk := resp.raw.read1(CHUNK, decode_content=True):
            body += chunk
            if len(body) > self.max_bytes:
                raise RuntimeError(f"Response from {url} is over {self.max_bytes // (1024 * 1024)} MB; gave up")
            if time.monotonic() - started > self.max_seconds:
                raise RuntimeError(f"Response from {url} took over {self.max_seconds:g} s; gave up")
        return bytes(body)

    def get_text(self, url: str) -> str:
        resp, body = self._request("GET", url)
        # Without a charset in Content-Type, assume UTF-8 (not the HTTP default
        # ISO-8859-1): these sites serve UTF-8
        charset = resp.encoding if "charset" in resp.headers.get("Content-Type", "").lower() else "utf-8"
        try:
            return body.decode(charset, errors="replace")
        except LookupError:   # a charset Python doesn't know
            return body.decode("utf-8", errors="replace")

    def get_json(self, url: str):
        return json.loads(self._request("GET", url, headers={"Accept": "application/json"})[1])

    def post_json(self, url: str, payload: dict, headers: dict | None = None):
        return json.loads(self._request("POST", url, json=payload,
                                        headers={"Accept": "application/json", **(headers or {})})[1])
