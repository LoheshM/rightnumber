"""Record the example checks into data/fixtures/ so the app runs with no keys (replay mode).

    uv run python -m scripts.record_fixtures

Uses the warm disk cache (free). SerpApi responses are already scrubbed of api_key; this refuses to
write any fixture that contains one.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys

from app.config import load_settings
from app.deps import build_deps
from app.main import EXAMPLES
from app.pipeline import run

sys.stdout.reconfigure(encoding="utf-8")


def _copy(src, dst) -> bool:
    if not src.exists():
        return False
    text = src.read_text(encoding="utf-8")
    assert "api_key" not in text.replace('"api_key"', ""), f"refusing to write {src.name}: contains api_key"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return True


async def main() -> None:
    s = load_settings()
    deps = build_deps(s)
    fx = s.fixtures_dir

    async def emit(event: str, data: dict) -> None:
        if event == "serp_call" and data["source"] == "live":
            print(f"   LIVE (1 credit) {data['engine']}: {data['purpose']}")
        elif event in ("error",):
            print(f"   {event}: {data}")
        elif event == "result":
            print(f"   verdict={(data.get('verdict') or {}).get('label')} domain={data['domain']} "
                  f"call_instead={[c['display'] for c in data['call_instead']]}")

    for e in EXAMPLES:
        print(f"> {e['brand']} {e['number']} ({e['city']})")
        await run(e["brand"], e["number"], e["city"], deps, emit)
    n = sum(_copy(s.cache_dir / f"{k}.json", fx / f"{k}.json") for k in deps.serp.used_keys)
    n += sum(_copy(s.cache_dir / "pages" / f"{k}.json", fx / "pages" / f"{k}.json") for k in deps.pages.used_keys)
    n += sum(_copy(s.cache_dir / "llm" / f"{k}.json", fx / "llm" / f"{k}.json") for k in deps.llm.used_keys)
    (fx / "llm").mkdir(parents=True, exist_ok=True)
    (fx / "llm" / "MODEL").write_text(deps.llm.model, encoding="utf-8")
    print(f"wrote {n} fixture files to {fx}")
    for d in (fx, fx / "pages", fx / "llm"):
        print(f"  {d.name}: {sum(f.stat().st_size for f in d.glob('*.json')) // 1024} KB")
    await deps.serp.aclose()
    await deps.pages.aclose()
    json.dumps({})


if __name__ == "__main__":
    asyncio.run(main())
