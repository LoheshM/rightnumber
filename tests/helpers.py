"""Shared test helpers (payload loading, fixture writers)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.pages import PageReader, html_to_text
from app.serp import cache_key

DATA = Path(__file__).parent / "data"


def load_payload(name: str) -> dict[str, Any]:
    return json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))


def write_serp_fixture(fixtures_dir: Path, engine: str, params: dict[str, Any], response: dict[str, Any]) -> Path:
    clean = {k: v for k, v in params.items() if v is not None}
    path = fixtures_dir / f"{cache_key(engine, clean)}.json"
    path.write_text(json.dumps({"engine": engine, "params": clean, "response": response}, ensure_ascii=False),
                    encoding="utf-8")
    return path


def write_page_fixture(fixtures_dir: Path, url: str, html: str, *, final_url: str | None = None,
                       ok: bool = True) -> Path:
    text, links, title = html_to_text(html)
    pages = fixtures_dir / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    rec = {"final_url": final_url or url, "text": text, "links": links, "title": title, "ok": ok}
    path = pages / f"{PageReader.key(url)}.json"
    path.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    return path
