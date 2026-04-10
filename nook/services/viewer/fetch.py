from __future__ import annotations

import requests
from bs4 import BeautifulSoup


def fetch_url_content(url: str) -> str | None:
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for element in soup(["script", "style", "nav", "header", "footer"]):
            element.decompose()
        main_content = soup.find("article") or soup.find("main") or soup.find("body")
        if not main_content:
            return None
        text = " ".join(main_content.get_text(separator=" ").split())
        if not text:
            return None
        return text[:1000] + "..." if len(text) > 1000 else text
    except Exception:
        return None
