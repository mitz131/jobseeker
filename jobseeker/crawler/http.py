"""HTTP client (requests) with retries, cookies and polite pacing."""

import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)
RETRY_STATUSES = (429, 500, 502, 503, 504)


class HttpClient:
    def __init__(self, delay: float = 0.5, timeout: float = 30, retries: int = 3):
        self.delay = delay
        self.timeout = timeout
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

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        wait = self.delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()
        try:
            resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
        except requests.RequestException as e:
            raise RuntimeError(f"Request failed for {url}: {e}") from e
        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code} for {url}: {resp.text[:300]}")
        return resp

    def get_text(self, url: str) -> str:
        resp = self._request("GET", url)
        # Without a charset in Content-Type, requests falls back to ISO-8859-1 (the
        # HTTP default); these sites serve UTF-8
        if "charset" not in resp.headers.get("Content-Type", "").lower():
            resp.encoding = "utf-8"
        return resp.text

    def get_json(self, url: str):
        return self._request("GET", url, headers={"Accept": "application/json"}).json()

    def post_json(self, url: str, payload: dict, headers: dict | None = None):
        return self._request("POST", url, json=payload,
                             headers={"Accept": "application/json", **(headers or {})}).json()
