# Verification log

How RightNumber was checked against reality (8 Oct 2026):

1. A ground-truth agent collected official numbers from each brand's own website, and publicly reported fake numbers, using WebSearch/WebFetch only ([ground_truth.json](ground_truth.json)).
2. Ten real cases were run through the app on live SerpApi data. Raw event dumps are in `results/`. Run `bash scripts/verify_batch.sh` to rerun them for free from cache.
3. An independent agent fact-checked every output against the web, opening the cited source pages ([VERIFICATION_web_check.md](VERIFICATION_web_check.md)).
4. Every problem found was fixed, given a regression test (`tests/test_regressions.py`), and rerun from cache.

## Final results (after fixes)

| # | Case (input) | RightNumber says | Checked against the web | Result |
|---|---|---|---|---|
| 1 | **Blue Dart** · 6291610240 (number from a Justdial review) | 🔴 *Verify before calling*: complaint text names this exact number. Call instead 1860 233 1234 · 022 4061 1234 · 080 4661 1234 | A Justdial review (2019) calls it "a fraud no.". All three numbers are on [bluedart.com/fraudawareness](https://www.bluedart.com/fraudawareness) and [/call-us](https://www.bluedart.com/call-us) | ✅ |
| 2 | **Blue Dart** · 1860 233 1234 | ✅ *Printed on the official site* | The fraud-awareness page says "contact on its official number 18602331234" | ✅ |
| 3 | **Blue Dart** · 07016493282 (scam caller reported on TechEnclave) | 🟡 *Not found on the official pages we read* | Correctly not official. The TechEnclave report wasn't surfaced, so the result is 🟡 rather than 🔴 | ⚠️ |
| 4 | **IRCTC** · 09002327947 (posted on Facebook as a refund number) | 🔴 *Verify before calling*: advertised as the helpline of Koovs, IndiGo, Google Pay, Flipkart and Paytm. Call 14646 | It was posted as a "customer care" number for Koovs (econsumercourt) and Google Pay (blog comment, 2022). 14646 is on IRCTC's [Contact Us](https://contents.irctc.co.in/en/ContactUsEn.html) page | ✅ |
| 5 | **IRCTC** · 14646 | ✅ *Printed on the official site* | Contact Us lists it as "Customer support within India" | ✅ |
| 6 | **DTDC** · +91 9606 911 811 | ✅ *Printed on dtdc.com* | It's on [dtdc.com/customer-care](https://www.dtdc.com/customer-care/) | ✅ |
| 7 | **HDFC Bank** (no number) | Call 1800 1600 · 1800 258 6161 | 1800 1600 is on the hdfc.bank.in home page ("how to reach us"). 1800 258 6161 is on [/upi/report-frauds](https://www.hdfc.bank.in/upi/report-frauds) ("To report any unauthorised … transactions, please call") | ✅ |
| 8 | **State Bank of India** · 1800 1234 | ⚪ *Abstains*, because SBI runs bank.sbi and sbi.bank.in. One click on "Use sbi.bank.in" → ✅ *printed on* sbi.bank.in/web/customer-care/contact-us | [sbi.bank.in contact-us](https://sbi.bank.in/web/customer-care/contact-us/) says "Toll free number: 1800 1234" | ✅ one click · ⚠️ automatic |
| 9 | **Airtel** · 6290133964 (named as a scam caller on a complaint site, 2020) | 🟡 *Not on the airtel.in pages we read*. No call-instead number, because only escalation desks were found | The verdict is fair. Airtel's care line is the short code 121, which wasn't on the pages read | ⚠️ |
| 10 | **Amazon** · +91 80 6605 5000 (reported as a fake Amazon number) | 🟡 *Not on the amazon.in pages we read*. No call-instead number | Correct: Amazon India publishes no customer-care phone number. Numbers on seller product listings are excluded | ✅ |

**7 ✅ · 3 ⚠️ · 0 ❌.** None of the verdicts on a user's number overclaimed. The ⚠️ rows are honest misses: an un-surfaced complaint, an automatic abstain, and a short code that wasn't found.

## Bugs found by verification, all fixed with regression tests

| Found by | Bug (real data) | Fix |
|---|---|---|
| Live run | bluedart.com's regional office table put **fax** lines into "call instead" | Fax-labelled numbers are never suggested |
| Live run | HDFC's fraud page lists **Google Pay / WhatsApp** helplines as "Partner Customer Care" | Labelled "another organisation"; never suggested |
| Live run | "To report any unauthorised … transactions, please call 1800 258 6161" was read as a **warning** | Report-fraud instructions are care lines; label windows stop at sentence ends |
| Live run | **amazon.in product listings** carry sellers' "customer care" numbers | Listings, reviews, Q&A, forums and blogs on the official domain never count |
| Live run | Amazon's "Call 112 for emergency services" and US "844-311-0406" were suggested | Emergency codes and North-American numbers are rejected |
| Live run | dtdc.in vs dtdc.com and hdfcbank.com vs hdfc.bank.in **split the domain vote** | Redirect aliases are resolved before voting (free HEAD requests) |
| Live run | The LLM summary turned "20 pins checked" into "your number appears on 20 pins" | Facts are code-written sentences; the summary is rejected if it names any number not suggested to call |
| Web check | Airtel **appellate officers** and the HDFC **RBI-bonds** line were suggested | Escalation, agent and seller desks are never suggested; only care-labelled numbers are |
| Web check | DTDC **retail-outlet** numbers from stores.dtdc.com were suggested | Branch/store pages are used only when the brand publishes nothing for everyone |
| Web check | "Aircel Complaint Daudnagar" (a site's category label) counted as an Aircel helpline claim | A brand counts only when helpline words directly follow it |
| Code review | "Beware of **fake customer care** numbers such as 98…" let "customer care" cancel the warning | Qualified fakes, fraudster/impostor sentences and "reported as fraudulent" lists are always warnings |
| Code review | Scam-only Maps pins plus one SEO'd result could outvote the knowledge graph plus the model | Maps never breaks a tie; equal support means abstain |
| Code review | Hostile HTML could freeze the server (quadratic regex) | Linear tokenizer, 20 s page deadline, parsing in a worker thread |
| Test suite | Delhi's **011** landlines, `3.9876543210` decimals, `+91 1800…` input, `co.in` as a domain | Parser fixes |
