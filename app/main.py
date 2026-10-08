"""FastAPI app: an SSE endpoint for the pipeline plus the static UI."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from . import pipeline
from .config import ROOT, Settings, load_settings
from .deps import build_deps
from .domains import registrable

log = logging.getLogger("rightnumber")
WEB = ROOT / "web"

EXAMPLES = [
    {"label": "Blue Dart + a number from a review", "brand": "Blue Dart", "number": "6291610240", "city": "Delhi",
     "hint": "Number named in complaints · official numbers instead"},
    {"label": "Blue Dart's own toll-free", "brand": "Blue Dart", "number": "1860 233 1234", "city": "Delhi",
     "hint": "Printed on bluedart.com"},
]


def create_app(settings: Settings | None = None, deps: pipeline.Deps | None = None) -> FastAPI:
    s = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.deps = deps or build_deps(s)
        yield
        await app.state.deps.serp.aclose()
        await app.state.deps.pages.aclose()

    app = FastAPI(title="RightNumber", lifespan=lifespan)

    @app.middleware("http")
    async def same_origin_api(request: Request, call_next):
        # Credit-spending endpoints must not be triggerable by other websites (<img src=…>, fetch).
        if request.url.path.startswith("/api/") and request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"error": "cross-site requests are not allowed"}, status_code=403)
        return await call_next(request)

    def stream(runner) -> EventSourceResponse:
        queue: asyncio.Queue[tuple[str, Any] | None] = asyncio.Queue()

        async def emit(event: str, data: dict) -> None:
            await queue.put((event, data))

        async def work() -> None:
            try:
                await runner(emit)
            except Exception:
                log.exception("pipeline failed")
                await queue.put(("error", {"text": "Something went wrong while checking this helpline."}))
            finally:
                await queue.put(None)

        async def gen():
            task = asyncio.create_task(work())
            try:
                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    event, data = item
                    yield {"event": event, "data": json.dumps(data, ensure_ascii=False, default=str)}
            finally:
                if not task.done():
                    task.cancel()

        return EventSourceResponse(gen(), ping=15)

    @app.get("/api/check/stream")
    async def check(brand: str = Query(..., min_length=2, max_length=60),
                    number: str = Query("", max_length=40),
                    city: str = Query("Delhi", max_length=30),
                    domain: str = Query("", max_length=100)):
        if domain and not registrable(domain):
            return JSONResponse({"error": "official website must be a domain like example.com"}, status_code=400)
        d = app.state.deps
        return stream(lambda emit: pipeline.run(brand, number or None, city, d, emit, user_domain=domain or None))

    @app.get("/api/status")
    async def status():
        d: pipeline.Deps = app.state.deps
        acct = await d.serp.account() if d.serp.mode != "replay" else None
        return {"mode": d.serp.mode, "llm": d.llm.model if d.llm.available else None,
                "credits_per_check": d.credits_per_check, "account": acct, "cities": list(pipeline.CITIES)}

    @app.get("/api/examples")
    async def examples():
        return EXAMPLES

    @app.get("/")
    async def index():
        return FileResponse(WEB / "index.html")

    app.mount("/static", StaticFiles(directory=WEB), name="static")
    return app


app = create_app()
