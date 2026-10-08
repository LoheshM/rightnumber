"""Live data probe: one call per engine, cached + scrubbed to probe/raw/."""
import asyncio, json, os, sys
from pathlib import Path
from dotenv import load_dotenv
sys.path.insert(0, ".")
from app.serp import SerpClient
load_dotenv(".env")
IN = {"gl": "in", "hl": "en", "google_domain": "google.co.in"}

async def main(step):
    c = SerpClient(os.environ["SERPAPI_API_KEY"], Path("data/cache"))
    calls = {
        "g_brand": ("google", {"q": "Blue Dart customer care number", **IN}),
        "maps": ("google_maps", {"type": "search", "q": "Blue Dart customer care", "ll": "@28.6139,77.2090,12z", "hl": "en", "gl": "in"}),
    }
    if step in calls:
        eng, p = calls[step]
    else:
        eng, p = sys.argv[2], json.loads(sys.argv[3])
    d = await c.search(eng, p, purpose="probe")
    Path("probe/raw").mkdir(parents=True, exist_ok=True)
    Path(f"probe/raw/{step}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    await c.aclose()
    print("ok", step, list(d.keys()))
asyncio.run(main(sys.argv[1]))
