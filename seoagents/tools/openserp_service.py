"""Native Python OpenSERP microservice (L4).

Runs on port 7000 as a real SERP scraper service using httpx + BeautifulSoup4
to fetch live Google search results, eliminating docker dependencies.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from fastapi import FastAPI, Query
from bs4 import BeautifulSoup
import httpx
import uvicorn

app = FastAPI(title="OpenSERP Native Service", version="1.0.0")

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]

def _clean_url(raw_url: str) -> str:
    if raw_url.startswith("/url?q="):
        parsed = urlparse(raw_url)
        qs = parse_qs(parsed.query)
        if "q" in qs:
            return qs["q"][0]
    return raw_url

@app.get("/google/search")
async def google_search(
    text: str = Query(..., description="Search keyword query"),
    lang: str = Query("EN", description="Language code"),
    limit: int = Query(20, description="Max search results limit"),
) -> dict[str, Any]:
    url = "https://www.google.com/search"
    headers = {
        "User-Agent": _USER_AGENTS[0],
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9" if lang.upper() == "EN" else "zh-CN,zh;q=0.9",
    }
    params = {"q": text, "num": max(limit, 10), "hl": lang.lower()}

    results = []
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers, params=params)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                # Find search result blocks
                blocks = soup.find_all("div", class_="g") or soup.find_all("div", class_=re.compile(r"MjjYud|tF2Cxc"))
                rank = 1
                for block in blocks:
                    a_tag = block.find("a", href=True)
                    if not a_tag:
                        continue
                    href = a_tag["href"]
                    clean_href = _clean_url(href)
                    if not clean_href.startswith("http") or "google.com" in clean_href:
                        continue
                    title_tag = block.find("h3")
                    title = title_tag.get_text() if title_tag else ""
                    results.append({
                        "rank": rank,
                        "position": rank,
                        "title": title,
                        "url": clean_href,
                    })
                    rank += 1
                    if len(results) >= limit:
                        break
    except Exception as err:
        print(f"[OpenSERP Service Error] {err}")

    # Fallback to duckduckgo HTML search if google blocked or returned empty
    if not results:
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                ddg_resp = await client.get(
                    "https://html.duckduckgo.com/html/",
                    headers=headers,
                    params={"q": text},
                )
                if ddg_resp.status_code == 200:
                    soup = BeautifulSoup(ddg_resp.text, "html.parser")
                    rank = 1
                    for a in soup.find_all("a", class_="result__url", href=True):
                        href = unquote(a["href"].replace("//duckduckgo.com/l/?uddg=", "").split("&")[0])
                        if href.startswith("http"):
                            results.append({
                                "rank": rank,
                                "position": rank,
                                "title": text,
                                "url": href,
                            })
                            rank += 1
                            if len(results) >= limit:
                                break
        except Exception as ddg_err:
            print(f"[DuckDuckGo Fallback Error] {ddg_err}")

    return {"results": results, "query": text, "total": len(results)}

def main():
    uvicorn.run(app, host="127.0.0.1", port=7000, log_level="info")

if __name__ == "__main__":
    main()
