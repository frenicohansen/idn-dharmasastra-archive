"""HTTP session for peraturan.bpk.go.id, which sits behind a Cloudflare managed challenge.

A real browser clears the challenge once (Scrapling's StealthyFetcher, chosen in
docs/ARCHITECTURE.md "Reused instead of written" after a comparison of four tools); its
cookies (cf_clearance) and user agent then go into a curl_cffi session that looks like the
same Chrome, which does the actual requests. When Cloudflare challenges again (clearance
expired), the browser runs again. With ``state`` (a file), the cookies and user agent are kept
between processes, so the workflow's batches (one process each) reuse one clearance instead of
opening the browser every batch (~2.5 min each). Needs the `bpk` extra and, on Linux without a
screen, a virtual display (xvfb-run): the challenge is only passed by a headful browser.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

BASE = "https://peraturan.bpk.go.id"


class Challenged(RuntimeError):
    """Cloudflare still shows its challenge after the browser tried."""


def is_challenge(status: int, headers, text: str = "") -> bool:
    return (status in (403, 503) and (headers.get("cf-mitigated") == "challenge"
                                     or "_cf_chl_opt" in text[:20000]))


def browser_clearance(url: str = BASE + "/") -> tuple[dict[str, str], str]:
    """Open ``url`` in a stealth Chrome, let Scrapling pass the challenge, return cookies and
    the browser's user agent."""
    from scrapling.fetchers import StealthyFetcher

    got: dict = {}

    def grab(page):
        got["cookies"] = {c["name"]: c["value"] for c in page.context.cookies()}
        got["ua"] = page.evaluate("navigator.userAgent")
        return page

    StealthyFetcher.fetch(url, headless=False, real_chrome=True, solve_cloudflare=True,
                          timeout=120_000, page_action=grab)
    if "cf_clearance" not in got.get("cookies", {}):
        raise Challenged("the browser did not get past Cloudflare (no cf_clearance cookie)")
    return got["cookies"], got["ua"]


class Session:
    """Polite: one request at a time, ``delay`` seconds apart, retries with backoff,
    re-clears Cloudflare when needed (at most ``max_clearances`` times per run)."""

    def __init__(self, delay: float = 3.0, max_clearances: int = 5, clearance=browser_clearance,
                 state: Path | None = None):
        self.delay, self.max_clearances, self._clearance = delay, max_clearances, clearance
        self.state = state                  # saved clearance from an earlier process, if any
        self.clearances = 0
        self._last = 0.0
        self.http = None

    def _clear(self) -> None:
        from curl_cffi import requests as cr

        saved = self._load()
        if saved:
            cookies, ua = saved
        else:
            if self.clearances >= self.max_clearances:
                raise Challenged(f"Cloudflare challenged {self.clearances} times; stopping")
            self.clearances += 1
            cookies, ua = self._clearance()
            if self.state:
                self.state.write_text(json.dumps({"cookies": cookies, "ua": ua}))
        self.http = cr.Session(impersonate="chrome")
        self.http.headers["User-Agent"] = ua
        for k, v in cookies.items():
            self.http.cookies.set(k, v, domain=".bpk.go.id")

    def _load(self) -> tuple[dict[str, str], str] | None:
        """The saved clearance (deleted by ``get`` when Cloudflare challenges it)."""
        if not (self.state and self.state.exists()):
            return None
        saved = json.loads(self.state.read_text())
        return saved["cookies"], saved["ua"]

    def get(self, url: str, retries: int = 5, timeout: int = 300):
        """GET ``url`` (absolute, or a path on BASE). Raises on persistent failure."""
        if url.startswith("/"):
            url = BASE + url
        last = None
        for attempt in range(retries):
            if self.http is None:
                self._clear()
            wait = self.delay - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                r = self.http.get(url, timeout=timeout)
            except Exception as e:  # noqa: BLE001 - network errors: back off and retry
                last = repr(e)
            else:
                if is_challenge(r.status_code, r.headers, r.text if r.status_code != 200 else ""):
                    self.http = None                     # clearance expired: browser again
                    if self.state and self.state.exists():
                        self.state.unlink()
                    last = "Cloudflare challenge"
                    continue
                if r.status_code < 500 and r.status_code != 429:
                    r.raise_for_status()
                    return r
                last = f"HTTP {r.status_code}"
            time.sleep(min(300, 10 * 2 ** attempt))
        raise RuntimeError(f"giving up on {url}: {last}")
