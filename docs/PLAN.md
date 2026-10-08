# RightNumber — plan

**Track:** Knowledge & Public Interest (civic information / public safety).
**One line:** before you dial a "customer care" number you found on Google or Maps, RightNumber checks whether the brand's *own website* prints it, shows you the number the brand itself publishes, and audits the Maps pins people actually see.

## 1. Problem (evidence in `docs/IDEA_ITERATIONS.md`, rounds 1–3, 11)
- Kerala Police, 3 Oct 2026: *"not to blindly trust customer care numbers found through internet searches"* (Outlook India).
- Victims typically lose ₹90K–₹5L (Uber ₹5L, IRCTC ₹4.5L, Amazon ₹1.07L, Jabalpur doctor-number ₹2.73L). CloudSEK counted 31,179 fake customer-care numbers in 2022 data.
- Probe: Google's top-10 for "Blue Dart customer care number" is **10/10 Justdial**; one snippet calls a number a fraud number. Maps pins carry numbers the brand never publishes.
- Existing tools (Truecaller, Sanchar Saathi, I4C Suspect Search) are blacklists: they know a number only after victims report it and never tell you the right one.

## 2. What it is / isn't
- **Is:** a positive-verification pipeline. "Is this number printed on the brand's official site? If not, here's what is." Plus a neutral audit of Maps pins.
- **Isn't:** a scam database, a caller-ID app, or a "safe" certificate. It never says fake/scam/fraud in its own voice and never invents a number (the LLM never outputs digits).

## 3. User flow
1. Type a brand (e.g. *Blue Dart*), optionally the number you found, optionally pick a city (default Delhi).
2. Watch the live trail (each SerpApi call: engine, purpose, ms, live · 1 credit / cached · free; each official page read).
3. Verdict card on your number + "Call instead" numbers with source links.
4. Two columns: *What Google shows you* vs *What <brand> itself says*.
5. Pin audit (masked mobiles), sources, transparency panel.

## 4. Architecture
```
web/ (vanilla JS + SVG, no build)  ── EventSource SSE ──►  FastAPI (app/main.py)
 pipeline.run(brand, number, city, deps, emit)
   events: step · serp_call · page_read · official · numbers · pins · voices · verdict · summary · notice · done
   ├─ phones.py   Indian number parsing (+91/0/STD grouping/toll-free/short codes), strict extraction
   ├─ domains.py  registrable domains (.co.in, .bank.in…), directory sites, brand tokens
   ├─ serp.py     SerpApi client: disk cache · replay fixtures · per-check budget · hourly cap · scrub
   ├─ pages.py    free HTTPS reads of the official domain's pages (same-domain only, 2 MB, 20 s deadline, linear HTML tokenizer, cached/replayable); redirect-alias resolution
   ├─ official.py official-domain decision (Maps majority × KG/organic/local pack × LLM sanity × site: confirmation)
   ├─ evidence.py number→sources, complaint snippets (keyword rules), pin audit, verdict (all in code)
   └─ llm.py      Gemini 2.5 Flash (OpenAI-compatible): (1) official-domain guess (domain only, one vote of three),
                  (2) 2-sentence summary that only shortens code-written fact sentences (rejected if it names any
                  number not suggested, or uses vouching words). Snippet/complaint labelling is deterministic rules.
```

## 5. SerpApi calls per check (≤ 4 credits; brand-level calls cached 72 h per brand+city)
| # | Engine | Query | Why |
|---|---|---|---|
| 1 | `google_maps` | `<brand> customer care`, `ll` = city | the pins victims see; phones + websites → domain consensus + pin audit |
| 2 | `google` | `<brand> customer care number` (gl=in, google.co.in) | what a victim's search shows; KG/local pack/organic domains; complaint snippets |
| 3 | `google` | `site:<official> customer care OR contact OR helpline` | finds the brand's own contact/help/fraud pages (+ snippets with numbers) |
| 4 | `google` | `"<number variants>"` (only if a number was given) | where this exact number appears; complaint text naming it |
Calls 1, 2, 4 and the LLM domain guess run in parallel; 3 waits for the domain decision; then up to 5 page reads.

## 6. Core logic & thresholds
- **Official domain:** candidates = Maps majority domain (≥3 pins with that site and ≥60% of pins that have a website), KG website, local-pack websites, non-directory organic domains whose label carries a brand token, LLM guess. Accept the domain backed by **≥2 independent sources** (Maps / Google results / LLM), not a directory. Redirect aliases (hdfcbank.com → hdfc.bank.in) are kept as the same brand. Then call 3 must return ≥1 page on it, else abstain. User-typed domain overrides (still needs call 3 to return pages).
- **Official numbers:** numbers found in the official pages' text (fetched) and in call-3 snippets, each with source URL + ±50-char label context. Numbers in `site:` snippets need the snippet to be on the official domain.
- **Number verdict** (user number N):
  - ✅ `on_official_site` — N in official numbers.
  - 🔴 `verify_before_calling` — not official and a complaint snippet names N exactly (keyword rules: fraud, scam, cheat, fake, duped, lost money, don't call… or LLM label `complaint_or_warning`).
  - 🟡 `not_on_official_pages` — not official, no complaint text. Context: "shown on k Maps pins" / "appears on directory sites".
  - ⚪ `no_official_source` — domain not established or no official pages readable.
  - Short codes (1930, 139) only match exact official text.
- **Pin audit:** per pin: number on official pages? website = official / other / none; mobile masked unless it's N. Counts: pins with official number, pins whose number isn't on official pages, pins whose website isn't the official domain.
- **"What Google shows":** share of top-10 organic results that are directory sites; the official domain's best rank (or "not in top 10").
- **Summary:** LLM writes from pre-formatted facts; rejected (template used) if it contains any digit run not in the facts or banned words.

## 7. API
- `GET /api/check/stream?brand=&number=&city=&domain=` → SSE stream (events: start · step · serp_call · page_read · official · notice · result · done · error).
- `GET /api/examples` → recorded example queries (replay works with no keys).
- `GET /api/status` → mode (live/replay), LLM model, credits left (free account API).
- Cross-site guard (`Sec-Fetch-Site: cross-site` → 403), per-check budget 4, hourly live cap 30.

## 8. Repo layout
`app/{config,serp,phones,domains,pages,official,evidence,llm,pipeline,main}.py` · `web/{index.html,app.js,styles.css}` · `scripts/{check,record_fixtures,secret_scan,ui_shot,dump_results}.py` · `data/fixtures/` (scrubbed) · `tests/` · `docs/{IDEA_ITERATIONS,PLAN,VERIFICATION}.md`.

## 9. Test plan
Number parsing traps (AWB ids, prices, pincodes, dates, +1 numbers, STD grouping, merged runs), domains (.co.in/.bank.in, directories, tokens), official-domain decision (agree/disagree/abstain), verdict rules, masking, summary validation, serp client (cache/replay/budget/scrub), pages (same-domain redirects, size cap), replay e2e of recorded examples, SSE API.

## 10. Credit budget (≤ 60 total; 5 spent on the probe)
| Phase | Credits |
|---|---|
| Probe | 5 (done) |
| Dev on Blue Dart + 2 brands | ~10 |
| Verification: ~7 brands × 3 + ~6 numbers | ~27 |
| Fixtures / demo pre-warm (mostly cached) | ~5 |
| Reserve | ~13 |

## 11. Submission checklist
See HACKATHON_PLAYBOOK.md §9 — public repo LoheshM/rightnumber, replay with no keys, secret scan, README (problem, screenshots, engines table, verified table, limitations, AI disclosure, MIT), demo < 3 min from git-ignored DEMO_SCRIPT.md, form: Knowledge & Public Interest, AI tools = Claude Code + Gemini 2.5 Flash.

## 12. Changes after verification and review
See docs/VERIFICATION.md: care-labelled numbers only; fax / other-org / escalation / seller / branch / user-generated sources never suggested; Maps never breaks a domain tie; user-entered domain labelled as such; shared links prefill but never auto-run; anti-framing headers.
