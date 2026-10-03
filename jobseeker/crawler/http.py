"""HTTP client with retries, cookies and polite pacing."""

import http.cookiejar
import json
import logging
import time
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)
RETRY_STATUSES = {429, 500, 502, 503, 504}


class HttpClient:
    def __init__(self, delay: float = 0.5, timeout: float = 30, retries: int = 3):
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self._last_request = 0.0
        # Keep cookies across requests: some sites tie their API to a session
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def _request(self, url: str, data: bytes | None = None, headers: dict | None = None) -> bytes:
        hdrs = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
        hdrs.update(headers or {})
        for attempt in range(self.retries + 1):
            wait = self.delay - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()
            req = urllib.request.Request(url, data=data, headers=hdrs, method="POST" if data else "GET")
            try:
                with self._opener.open(req, timeout=self.timeout) as resp:
                    return resp.read()
            except urllib.error.HTTPError as e:
                if e.code not in RETRY_STATUSES or attempt == self.retries:
                    body = e.read()[:300].decode("utf-8", "replace")
                    raise RuntimeError(f"HTTP {e.code} for {url}: {body}") from e
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt == self.retries:
                    raise RuntimeError(f"Request failed for {url}: {e}") from e
            backoff = 2 ** attempt * 2
            log.warning("Retrying %s in %ss (attempt %d)", url, backoff, attempt + 1)
            time.sleep(backoff)
        raise AssertionError("unreachable")

    def get_text(self, url: str) -> str:
        return self._request(url).decode("utf-8", "replace")

    def get_json(self, url: str):
        return json.loads(self._request(url, headers={"Accept": "application/json"}))

    def post_json(self, url: str, payload: dict, headers: dict | None = None):
        return json.loads(self._request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Accept": "application/json", "Content-Type": "application/json",
                     **(headers or {})},
        ))
