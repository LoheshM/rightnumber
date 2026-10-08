"""Playwright screenshots of a full check (desktop light/dark + mobile). Fails on console errors or overflow.

    uv run python -m scripts.ui_shot <base_url> <out_dir> [brand] [number]
"""

import sys

from playwright.sync_api import sync_playwright

base, out = sys.argv[1], sys.argv[2]
brand = sys.argv[3] if len(sys.argv) > 3 else "Blue Dart"
number = sys.argv[4] if len(sys.argv) > 4 else "6291610240"
errors: list[str] = []
with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge")
    for name, vp, scheme in [("desktop-light", (1366, 900), "light"), ("desktop-dark", (1366, 900), "dark"),
                             ("mobile", (390, 844), "light")]:
        pg = b.new_page(viewport={"width": vp[0], "height": vp[1]}, color_scheme=scheme)
        pg.on("console", lambda m, n=name: errors.append(f"{n}: {m.type}: {m.text}") if m.type in ("error", "warning") else None)
        pg.on("pageerror", lambda e, n=name: errors.append(f"{n}: pageerror: {e}"))
        pg.goto(base + "/")
        pg.wait_for_timeout(700)
        if name == "desktop-light":
            pg.screenshot(path=f"{out}/landing.png")
        pg.fill("#brand", brand)
        pg.fill("#number", number)
        pg.click("#go")
        pg.wait_for_selector("#result:not(.hidden)", timeout=180000)
        pg.wait_for_timeout(600)
        pg.screenshot(path=f"{out}/{name}.png", full_page=True)
        if name == "desktop-light":
            pg.screenshot(path=f"{out}/killer.png")
        if pg.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
            errors.append(f"{name}: horizontal overflow")
        pg.close()
    b.close()
print("\n".join(errors) or "no console errors, no overflow")
sys.exit(1 if errors else 0)
