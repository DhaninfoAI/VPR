"""Check that the URLs the model returned actually load."""

from concurrent.futures import ThreadPoolExecutor

import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "text/html,application/pdf,*/*",
}


def _check(url: str) -> dict:
    try:
        with httpx.Client(timeout=20, follow_redirects=True, headers=HEADERS) as client:
            with client.stream("GET", url) as r:
                status = r.status_code
        if status < 400:
            return {"state": "ok", "status": status}
        if status in (401, 403, 405, 429, 503):
            # Many government sites block automated requests; this does not mean the link is wrong.
            return {"state": "blocked", "status": status}
        return {"state": "broken", "status": status}
    except httpx.HTTPError as exc:
        return {"state": "unreachable", "status": None, "error": type(exc).__name__}


def check_urls(urls: list[str]) -> dict[str, dict]:
    unique = sorted({u for u in urls if u and u.startswith(("http://", "https://"))})
    if not unique:
        return {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        return dict(zip(unique, pool.map(_check, unique)))
