# Idea iterations — RightNumber

Each round: **Idea → Strongest objection → Answer / change.** Evidence comes from three research agents (pain points, SerpApi docs + BuiltWithSerpApi gallery, hackathon rules) and a 5-credit live probe saved in `probe/raw/` (scrubbed).

---

## Round 1 — pick the problem
**Idea.** Shortlist from pain research (ranked frequency × intensity × solvable-with-search):
1. Fake customer-care / helpline numbers on Google Search & Maps (Kerala Police advisory 3 Oct 2026: *"not to blindly trust customer care numbers found through internet searches"*; victims lose ₹90K–₹4.8L each; CloudSEK counted 31,179 fake numbers).
2. Fake pilgrimage / hotel booking sites (I4C alert, Uttarakhand STF blocked 51 sites).
3. Old / out-of-context viral images (Lens).
4. Fake job offers (Indeed 2026: 93% of job seekers saw suspicious offers).

**Objection.** Fact-checking (3) and travel (2) are crowded in the gallery; job scams have high frequency but only ~3% lose money.
**Answer.** Go with (1). It is the only one where the victim's *own search* is the attack surface — so search data is both the problem and the cure. Track: **Knowledge & Public Interest** (civic information / public safety). Different from Dealtective (Commerce) in track, data and user.

## Round 2 — is it already done?
**Objection.** Truecaller, I4C "Suspect Search", Sanchar Saathi exist.
**Answer.** All of them are *blacklists*: they only know a number after enough victims report it, and none tells you **what the right number is**. Gallery check (190 projects): *SearchPhone* is generic phone OSINT, *CeaseFire* is brand impersonation across engines — **nothing verifies a helpline number against the brand's own sources**. Our angle: *positive* verification (is it on the official site?) rather than negative reputation.

## Round 3 — can the data support the claim? (live probe, 5 credits)
**Objection.** "Official number" needs an authoritative source; Google may not surface it.
**Probe findings (Blue Dart, Delhi):**
- `google` "Blue Dart customer care number" (gl=in, no location) → **10/10 organic results are Justdial**; no knowledge graph, no bluedart.com in the organic list. One snippet: *"6291610240 is a fraud no."*
- Even `google` "Blue Dart" → knowledge graph has only a `place_id`, no website; 9/9 organic are Justdial (the local pack above them does show 3 bluedart.com pins with official numbers).
- `google_maps` "Blue Dart customer care" (Delhi) → 20 pins; **18 link to bluedart.com**, 12 show `022 4061 1234`; one pin links to **bluedarttracking.in** (a third-party tracking site) with a Hyderabad `040` number on a Delhi address; 4 pins show mobile numbers (all four still link to bluedart.com — the website field is owner-editable).
- `google` `site:bluedart.com customer care contact number` → bluedart.com pages; 2 of 9 snippets carry `02240611234` (site header).
**Answer.** The official domain comes from **Maps consensus** (majority registrable domain of pin websites), confirmed by the `site:` search actually returning pages. Official numbers = numbers printed on the official domain's own pages. The knowledge graph is a bonus, not a dependency.

## Round 4 — what breaks the obvious version?
**Objection.** Reverse-searching a number is noisy: probe query `"040 2331 1919"` returned 10 bluedart.com tracking pages **none of which contain the number** in the snippet.
**Answer.** A number only counts as "seen on X" when it literally appears (after normalisation) in that result's title/snippet. Everything else is "not confirmed". Also: the 040 number may be a real Blue Dart Hyderabad office — the red flag on that pin is the **website**, not necessarily the number. So website and number are scored separately.

## Round 5 — what is harmful if it ships naively?
**Objection.** Labelling a genuine franchise/branch mobile number "fake" defames a small business; saying "safe" about a scammer's number gets someone robbed.
**Answer.** Never say fake/scam/fraud. Three-tier, evidence-stated labels:
- ✅ **On the official site** (number printed on bluedart.com).
- 🟡 **Not on the official site** (branch/franchise/unknown) — *"OK for local pickup questions; never pay, share OTP or install apps for it."*
- 🔴 **Verify before calling** — not on the official site *and* a hard signal: lookalike website, or complaint text naming this exact number.
And always show **"Call instead: <official number> (source link)"**. We never certify any number as "safe" — only "printed on the official site".

## Round 6 — entity & number matching traps
**Objection.** Indian numbers come in many shapes; brands have many domains.
**Answer (rules in code, unit-tested):**
- Normalise: `+91`, `0091`, leading `0`, spaces/dashes/dots/brackets; 10-digit mobiles (6–9 start), STD landlines (`022 4061 1234` = `02240611234` = `+91 22 4061 1234`), toll-free `1800/1860` (10–11 digits), short codes (`139`, `1930`) only when explicitly given.
- Don't match numbers inside longer digit runs (tracking ids, AWB numbers, pincodes, prices `₹1,234`, dates); require non-digit boundaries.
- Registrable domain: `www.bluedart.com/...` → `bluedart.com`; handle `.co.in`, `.gov.in`, `.org.in`. Lookalike = brand token inside a *different* registrable domain (`bluedarttracking.in`), or hyphen/typo variants.
- Directory domains (Justdial, Sulekha, IndiaMart, Tradeindia, Yellowpages, numberdekho…) are *never* official.

## Round 7 — is SerpApi core? Is it an agent?
**Objection.** Cosmetic API usage = invalid entry.
**Answer.** Without SerpApi the product is empty: every verdict is built from 3–4 live searches across `google_maps`, `google` (brand search incl. local pack / AI overview), `google` with `site:` on the official domain, and `google` reverse lookup of the user's number. Honest framing: it's a **deterministic verification pipeline with one LLM step**, not a free-roaming agent. Hence the Knowledge & Public Interest track rather than AI Agents.

## Round 8 — can a judge trust the output?
**Objection.** LLMs hallucinate phone numbers — the worst possible failure here.
**Answer.** **The LLM never emits a phone number.** Code extracts every number with regex from SerpApi data and attaches the source URL. The single batched LLM call only (a) labels each snippet that contains the user's number as `official / complaint_or_warning / directory_listing / unrelated` (max-12-word reason) and (b) writes a 2-sentence summary from pre-formatted facts; the summary is rejected if it contains any digit run not in the facts. Live trail shows every SerpApi call with engine, purpose and "live · 1 credit / cached · free".

## Round 9 — the killer screen
**Objection.** A judge has 20 seconds.
**Answer.** Input: *Blue Dart* + *the number you found*. Output, one screen:
- Big verdict on your number (✅ / 🟡 / 🔴) with the reason in one line.
- **"Call instead: 022 4061 1234 — printed on bluedart.com"** with source link.
- **Maps audit** strip of pins colour-coded (superseded by Round 11).
- "What Google shows you": the top organic results are all directories (10/10 Justdial) — explains *why* people get fooled.

## Round 10 — name
**Objection.** Must be instantly understood by any judge; no conflicts.
**Answer.** Candidates: RingTrue (conflict: *RingsTrue*, a Salesforce phone-validation product), TrueDial (12 repos, dialer apps), TrueLine (popular repo), CallSafe. **RightNumber** — "wrong number? get the right number" — GitHub has only a handful of 0-star repos with the name and no product/app found in web search. Chosen.

## Round 11 — skeptical-judge critique (independent agent, verified against the probe JSON and bluedart.com)
**Objections (the 5 worst):**
1. **The headline demo was wrong.** bluedarttracking.in states *"Unofficial Website – Not affiliated with Blue Dart Express Ltd"* and lists `(040) 23311919` as a Blue Dart Hyderabad office (also on consumercomplaints.in). It is a third-party site carrying a real (possibly stale) number — calling it a "lookalike" would be a defamation-shaped error.
2. **Snippets miss most official numbers.** bluedart.com/contact-us shows `022 4061 1234` and `080 4661 1234`; bluedart.com/fraudawareness says *"contact on its official number 18602331234"*. The `site:` snippets surfaced only the header number, so a snippet-only tool would call Blue Dart's own toll-free line "not official".
3. **Maps-majority domain doesn't generalise** (e-commerce, ride-hailing, government helplines have no genuine "customer care" pins — whatever pins exist may be the scam ones).
4. **Credits:** ~50 left for everything at 4/check.
5. **Tone/privacy:** the pin strip would publish franchise owners' mobile numbers; repeating "fraud" from reviews amplifies strangers' accusations.
Also: doc counts were off (12 pins, not 13, show 022 4061 1234; 6–7, not 4, show numbers absent from bluedart.com); "the searcher can't see the official number" overclaimed (the brand query's local pack shows it).

**Answer / changes adopted:**
- Demo number is **6291610240** — a Justdial review snippet in the brand search names this exact number as fraud. The 040 pin is shown 🟡 *"website is not bluedart.com"*, never red. "Lookalike" removed from verdict logic.
- **Official numbers = the official domain's own pages, read directly.** SerpApi's `site:` search finds the contact/help/fraud pages; the app then fetches up to 4 of those pages over plain HTTPS (free, same registrable domain only, size/time-limited, cached + replayable) and extracts numbers with their surrounding label. Snippets remain a second source.
- **Official domain needs two independent agreeing sources**: Maps majority (≥3 pins, ≥60% of pins with a website), the knowledge-graph website / organic results / local pack, and an LLM sanity check (*"what is the official domain of X"* — a domain, never a number), each confirmed by the `site:` search returning pages. Disagreement → **abstain**: "couldn't establish an official source", and the user can type the official domain.
- Labels: ✅ *Printed on bluedart.com* (link) · 🟡 *Not found on the bluedart.com pages we checked* · 🔴 *Verify before calling* (🟡 + complaint text naming this exact number, quoted with attribution: "A Justdial review says…") · ⚪ *Couldn't establish an official source*. Never "safe", never "fake".
- Mobile numbers on pins are masked (`96546 xxx37`) except the user's own number. Pin facts (website ≠ official, number not on official pages) are stated neutrally.
- **Credits:** Maps, brand search and `site:` search are cached per brand+city (72 h); a new number for a known brand costs 1 credit. Knowledge-graph-only and AI-overview calls dropped. Per check ≤ 4.
- **Killer screen (adopted from the judge):** two columns — *"What Google shows you"* (10/10 directory results, the fraud-number snippet highlighted) vs *"What Blue Dart itself says"* (numbers printed on bluedart.com with links to /contact-us and /fraudawareness) — under a one-line verdict on the user's number. Pin audit below the fold.
- Verification set: should pass — Blue Dart, DTDC/Delhivery, HDFC/SBI; should **abstain gracefully** — IRCTC, Amazon/Uber; likely weak — LPG distributors, airlines. Correct abstentions are reported as wins.
