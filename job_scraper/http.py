from __future__ import annotations

import time
from typing import Any

import httpx

from job_scraper import __version__

USER_AGENT = f"job-scraper/{__version__} (personal job search; +https://github.com)"
DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class Http:
    def __init__(self, timeout: float | httpx.Timeout = DEFAULT_TIMEOUT) -> None:
        self.client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
            limits=httpx.Limits(max_connections=40, max_keepalive_connections=20),
        )

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> Http:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self._request("POST", url, **kwargs)

    def _request(self, method: str, url: str, retries: int = 2, **kwargs: Any) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                response = self.client.request(method, url, **kwargs)
                if response.status_code in {429, 503} and attempt < retries - 1:
                    time.sleep(0.4 * (attempt + 1))
                    continue
                return response
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < retries - 1:
                    time.sleep(0.35 * (attempt + 1))
        if last_error:
            raise last_error
        raise RuntimeError(f"request failed: {method} {url}")
