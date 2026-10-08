"""Run one check from the command line and print the event stream.

    uv run python -m scripts.check "Blue Dart" [number] [city] [--domain example.com] [--json out.json]
"""

from __future__ import annotations

import asyncio
import json
import sys

from app.config import load_settings
from app.deps import build_deps
from app.pipeline import run

sys.stdout.reconfigure(encoding="utf-8")


async def main(argv: list[str]) -> None:
    out = None
    domain = None
    if "--json" in argv:
        i = argv.index("--json"); out = argv[i + 1]; del argv[i:i + 2]
    if "--domain" in argv:
        i = argv.index("--domain"); domain = argv[i + 1]; del argv[i:i + 2]
    brand, number, city = (argv + [None, None, None])[:3]
    deps = build_deps(load_settings())
    events = []

    async def emit(event: str, data: dict) -> None:
        events.append({"event": event, "data": data})
        if event == "serp_call":
            print(f"  [{data['source']:>7}{' · 1 credit' if data['credit'] else ''}] {data['engine']}: {data['purpose']}"
                  f" ({data['ms']} ms){'  ERROR ' + str(data['error']) if not data['ok'] else ''}")
        elif event == "page_read":
            print(f"  [page {data['source']}] {data['final_url'][:80]} ok={data['ok']} chars={data['chars']} {data['error'] or ''}")
        elif event in ("notice", "error", "official", "step"):
            print(f"  {event}: {json.dumps(data, ensure_ascii=False)[:300]}")

    res = await run(brand, number, city, deps, emit, user_domain=domain)
    if res:
        print("\nVERDICT:", json.dumps(res["verdict"], ensure_ascii=False, indent=1)[:1500])
        print("CALL INSTEAD:", [(c["display"], c["sources"][0]["url"], c["sources"][0]["context"][:80]) for c in res["call_instead"]])
        print("WARNED:", [c["display"] for c in res["warned_numbers"]])
        print("PIN STATS:", res["pin_stats"])
        print("GOOGLE VIEW:", {k: v for k, v in res["google_view"].items() if k != "top"})
        print("SUMMARY:", res["summary_source"], "|", res["summary"])
        print("credits:", res["credits_spent"], "ms:", res["ms"])
    if out:
        with open(out, "w", encoding="utf-8") as f:  # noqa: ASYNC230 - CLI script
            json.dump(events, f, ensure_ascii=False, indent=1)
    await deps.serp.aclose(); await deps.pages.aclose()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
