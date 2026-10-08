"use strict";

const $ = (s) => document.querySelector(s);
const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ESC[c]);
const safeHref = (u) => (/^https?:\/\//i.test(String(u || "")) ? esc(u) : "#");
const telHref = (key) => "tel:" + String(key || "").replace(/[^0-9+]/g, "");
const shortUrl = (u) => {
  try { const x = new URL(u); return (x.hostname.replace(/^www\./, "") + x.pathname).replace(/\/$/, ""); } catch { return String(u || ""); }
};

let es = null;
let state = {};

/* ---------- theme ---------- */
(function theme() {
  try { const t = localStorage.getItem("rn-theme"); if (t) document.documentElement.dataset.theme = t; } catch {}
  $("#theme").addEventListener("click", () => {
    const cur = document.documentElement.dataset.theme
      || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = cur === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("rn-theme", next); } catch {}
  });
})();

/* ---------- boot ---------- */
async function boot() {
  try {
    const st = await (await fetch("/api/status")).json();
    const m = $("#mode");
    m.textContent = st.mode === "replay" ? "Replay · recorded examples" : `Live · ${st.account?.searches_left ?? "?"} searches left`;
    m.className = "pill " + (st.mode === "replay" ? "replay" : "live");
    m.title = st.mode === "replay" ? "No SerpApi key: recorded examples only, no credits spent" : "Live SerpApi searches (cached results are free)";
    $("#city").innerHTML = (st.cities || ["Delhi"]).map((c) => `<option>${esc(c)}</option>`).join("");
  } catch { $("#city").innerHTML = "<option>Delhi</option>"; }
  try {
    const ex = await (await fetch("/api/examples")).json();
    $("#examples").innerHTML = ex.map((e, i) =>
      `<button type="button" class="chip" data-i="${i}">${esc(e.label)}<small>${esc(e.hint)}</small></button>`).join("");
    $("#examples").querySelectorAll(".chip").forEach((b) => b.addEventListener("click", () => {
      const e = ex[+b.dataset.i];
      $("#brand").value = e.brand; $("#number").value = e.number || ""; $("#city").value = e.city || "Delhi";
      $("#domain").value = "";
      start();
    }));
  } catch {}
  const p = new URLSearchParams(location.search);
  if (p.get("brand")) {
    $("#brand").value = p.get("brand"); $("#number").value = p.get("number") || "";
    if (p.get("city")) $("#city").value = p.get("city");
    start();
  }
}

$("#form").addEventListener("submit", (e) => { e.preventDefault(); start(); });

/* ---------- streaming ---------- */
function start() {
  const brand = $("#brand").value.trim();
  if (brand.length < 2) { $("#brand").focus(); return; }
  if (es) es.close();
  state = { brand, calls: 0, credits: 0, pages: 0, steps: {} };
  const q = new URLSearchParams({ brand, number: $("#number").value.trim(), city: $("#city").value, domain: $("#domain").value.trim() });
  history.replaceState(null, "", "?" + new URLSearchParams({ brand, number: $("#number").value.trim(), city: $("#city").value }));
  $("#live").classList.remove("hidden");
  $("#trail").innerHTML = ""; $("#notices").innerHTML = ""; $("#trail-meta").textContent = "";
  $("#live").classList.remove("collapsed"); $("#trail-toggle")?.remove();
  $("#result").classList.add("hidden"); $("#result").innerHTML = "";
  $("#go").disabled = true; $("#go").textContent = "Checking…";
  es = new EventSource("/api/check/stream?" + q);
  const on = (name, fn) => es.addEventListener(name, (ev) => { try { fn(JSON.parse(ev.data)); } catch (err) { console.warn(err); } });
  on("step", step);
  on("serp_call", serpCall);
  on("page_read", pageRead);
  on("notice", (n) => $("#notices").insertAdjacentHTML("beforeend", `<div class="notice ${n.level === "info" ? "info" : ""}">${esc(n.text)}</div>`));
  on("result", render);
  on("error", (d) => { $("#notices").insertAdjacentHTML("beforeend", `<div class="notice">${esc(d.text || "Something went wrong.")}</div>`); finish(); });
  on("done", (d) => { meta(d.ms); finish(); });
  es.onerror = () => { if (es && es.readyState !== EventSource.CLOSED) { es.close(); finish(); } };
}

function finish() {
  if (es) es.close();
  $("#go").disabled = false; $("#go").textContent = "Check";
}

function meta(ms) {
  const parts = [`${state.calls} SerpApi searches`, `${state.credits} credit${state.credits === 1 ? "" : "s"} spent`, `${state.pages} official pages read`];
  if (ms) parts.push(ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`);
  $("#trail-meta").textContent = parts.join(" · ");
}

function step(s) {
  let li = state.steps[s.id];
  if (!li) {
    li = document.createElement("li"); li.className = "step"; state.steps[s.id] = li;
    $("#trail").appendChild(li);
  }
  li.innerHTML = `${s.status === "done" ? '<span class="tick">✓</span>' : '<span class="spin"></span>'}<span>${esc(s.label)}</span>`;
}

function serpCall(c) {
  state.calls += 1; if (c.credit) state.credits += 1;
  const cost = !c.ok ? `<span class="cost bad">failed · free</span>`
    : c.source === "live" ? `<span class="cost live">live · 1 credit · ${c.ms} ms</span>`
    : `<span class="cost">${c.source === "fixture" ? "recorded" : "cached"} · free</span>`;
  $("#trail").insertAdjacentHTML("beforeend",
    `<li><span class="eng ${esc(c.engine)}">${esc(c.engine)}</span><span class="purpose" title="${esc(c.purpose)}">${esc(c.purpose)}</span>${cost}</li>`);
  meta();
}

function pageRead(p) {
  if (p.ok) state.pages += 1;
  const cost = p.ok ? `<span class="cost">${p.source === "live" ? `read · free · ${p.ms} ms` : "cached · free"}</span>`
    : `<span class="cost bad">couldn't read</span>`;
  $("#trail").insertAdjacentHTML("beforeend",
    `<li><span class="eng page">official page</span><span class="purpose" title="${esc(p.final_url)}">${esc(shortUrl(p.final_url))}${p.ok ? "" : " — " + esc(p.error || "")}</span>${cost}</li>`);
  meta();
}

/* ---------- result ---------- */
const VCLASS = {
  on_official_site: ["good", "✓"], warned_on_official_site: ["bad", "!"], verify_before_calling: ["bad", "!"],
  other_org_on_official_site: ["warn", "?"],
  not_on_official_pages: ["warn", "?"], no_official_source: ["grey", "–"],
};

function highlight(text, digits, brands) {
  // Mark the user's number inside a quoted snippet (digits may be spaced or prefixed differently).
  let html = esc(text);
  if (!digits) return html;
  const tail = digits.slice(-10);
  const pattern = tail.split("").map((d) => d).join("[\\s\\-.]?");
  try { html = html.replace(new RegExp("(" + pattern + ")", "g"), "<mark>$1</mark>"); } catch {}
  for (const b of brands || []) {
    const rx = esc(b).replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/ /g, "\\s?");
    try { html = html.replace(new RegExp("(?<![A-Za-z])(" + rx + ")(?![A-Za-z])", "gi"), "<mark>$1</mark>"); } catch {}
  }
  return html.replace(/(fraud\w*|scam\w*|cheat\w*|fake|unauthori[sz]ed|duped)/gi, "<mark>$1</mark>");
}

function groupMentions(list) {
  // Directory sites repeat one review across many city pages; show it once with a count.
  const groups = new Map();
  for (const m of list) {
    const k = m.domain + "|" + String(m.snippet || m.title).replace(/^[^0-9]*?(?=\d)/, "").slice(0, 80);
    if (groups.has(k)) groups.get(k).n += 1; else groups.set(k, { m, n: 1 });
  }
  return [...groups.values()];
}

function render(r) {
  const out = [];
  const dom = r.domain;
  const brand = esc(r.brand);
  const v = r.verdict;
  const digits = (r.number || "").replace(/\D/g, "");

  /* verdict */
  if (v) {
    const [cls, icon] = VCLASS[v.label] || ["grey", "–"];
    let why = "";
    if (v.label === "on_official_site") why = `This exact number is printed on ${esc(dom)}.`;
    else if (v.label === "warned_on_official_site") why = `${esc(dom)} mentions this number only inside a fraud warning.`;
    else if (v.label === "other_org_on_official_site") why = `${esc(dom)} lists this number as another organisation's helpline (see the words around it below), not as ${esc(r.brand)}'s own.`;
    else if (v.label === "verify_before_calling" && v.other_brands?.length) why = `The same number is advertised on the web as the helpline of <b>${v.other_brands.map(esc).join(", ")}</b>. A genuine helpline belongs to one company.${dom && (r.pages || []).some((p) => p.ok && p.chars) ? ` It is not on the ${esc(dom)} pages we read.` : ""}`;
    else if (v.label === "verify_before_calling") why = dom && (r.pages || []).some((p) => p.ok && p.chars) ? `It is not on the ${esc(dom)} pages we read, and text on the web names this exact number in a complaint.` : `We couldn't establish an official website, and text on the web names this exact number in a complaint.`;
    else if (v.label === "not_on_official_pages") why = `It is not printed on the ${esc(dom)} pages we read. It may be a local branch — but never pay, share an OTP or install an app because a caller on this number asks.`;
    else why = dom ? `${esc(dom)} is the official website, but we couldn't read any phone number from it, so we can't compare. Use the number on your bill, card, ticket or the official app.`
      : `We couldn't establish the brand's official website from search, so we can't compare. Use the number on your bill, card, ticket or the official app.`;
    const quoteSrc = (v.complaints || []).length ? v.complaints : (v.other_brand_examples || []);
    const quotes = groupMentions(quoteSrc).slice(0, 2).map(({ m }) =>
      `<blockquote class="quote">“${highlight(m.complaint || m.snippet, digits, v.other_brands)}”<cite>— text on ${esc(m.domain)} (a third-party site; not checked by us) · <a href="${safeHref(m.url)}" target="_blank" rel="noopener nofollow">open</a></cite></blockquote>`).join("");
    out.push(`<article class="card verdict ${cls}">
      <div class="v-top"><span class="v-num">${esc(r.number)}</span><span class="label ${cls}">${icon} ${esc(v.title)}</span></div>
      <p class="v-why">${why}</p>${quotes}
      ${r.summary ? `<p class="v-sum">${esc(r.summary)} <small>${r.summary_source === "template" ? "" : "· summary by Gemini from the facts below"}</small></p>` : ""}
    </article>`);
  } else if (r.summary) {
    out.push(`<article class="card verdict ${dom ? "good" : ""}"><p class="v-sum">${esc(r.summary)}</p></article>`);
  }

  /* call instead */
  if (r.call_instead?.length) {
    out.push(`<article class="card"><h2>${v && v.label === "on_official_site" ? "Numbers" : "Call instead"} — printed on ${esc(dom)}</h2>
      <p class="muted" style="margin:4px 0 12px">Copied from the brand's own pages, with the words around each number so you can see how the site labels it.</p>
      <div class="callbox">${r.call_instead.map((c) => {
        const s = c.sources[0] || {};
        return `<div class="call"><a class="tel" href="${telHref(c.kind === "mobile" ? "+91" + c.key : (c.kind === "landline" ? "0" + c.key : c.key))}">${esc(c.display)}</a>
          <span class="ctx">“…${esc(s.context)}…”</span>
          <span class="src">${s.kind === "page" ? "Read from" : "Google snippet of"} <a href="${safeHref(s.url)}" target="_blank" rel="noopener">${esc(shortUrl(s.url))}</a>${c.sources.length > 1 ? ` and ${c.sources.length - 1} more page${c.sources.length > 2 ? "s" : ""}` : ""}</span></div>`;
      }).join("")}</div></article>`);
  }

  /* two columns: what google shows vs what the brand says */
  const g = r.google_view || {};
  const top = (g.top || []).map((t, i) => `<li><span class="pos">${i + 1}</span><a class="t" href="${safeHref(t.link)}" target="_blank" rel="noopener nofollow" title="${esc(t.title)}">${esc(t.title)}</a>
      ${t.official ? '<span class="tag off">official</span>' : t.directory ? `<span class="tag dir">${esc(t.domain)}</span>` : `<span class="tag other">${esc(t.domain)}</span>`}</li>`).join("");
  const left = `<article class="card side"><h2>What Google shows you</h2>
    <p class="sub">Top results for “${brand} customer care number”</p>
    ${g.results ? `<div class="big-stat">${g.directory}<small> of ${g.results} top results are directory sites</small></div>
      <p class="muted" style="margin:6px 0 0">${dom ? (g.official_rank ? `${esc(dom)} is result #${g.official_rank}.` : `${esc(dom)} isn't in the top ${g.results}.`) : ""} Directory listings can be edited by anyone.</p>
      <ol class="serp">${top}</ol>` : `<p class="muted">No search results available.</p>`}
  </article>`;
  const seenPage = new Set();
  const pages = (r.pages || []).filter((p) => p.ok && p.chars)
    .filter((p) => { const k = shortUrl(p.final_url).split("/").pop(); if (seenPage.has(k)) return false; seenPage.add(k); return true; }).map((p) => `<li>✓ <a href="${safeHref(p.final_url)}" target="_blank" rel="noopener">${esc(shortUrl(p.final_url))}</a></li>`).join("");
  const warned = (r.warned_numbers || []).map((w) => `<li><span class="mono">${esc(w.display)}</span> — <span class="tag bad">named in a warning</span> “…${esc(w.sources[0]?.context)}…”</li>`).join("");
  const right = `<article class="card side"><h2>What ${brand} itself says</h2>
    <p class="sub">${dom ? `Official website: <b>${esc(dom)}</b>` : "Official website: not established"}</p>
    ${dom ? `<div class="big-stat">${r.call_instead?.length || 0}<small> callable number${(r.call_instead?.length || 0) === 1 ? "" : "s"} printed on its own pages</small></div>
      <ul class="pages">${pages || "<li class='muted'>No page could be read.</li>"}</ul>
      ${r.call_instead?.length ? "" : `<p class="muted">We couldn't copy a phone number from ${esc(dom)}'s pages (some sites load them with JavaScript or block automated reading). Use the number on your bill, card, ticket or in the official app.</p>`}
      ${warned ? `<h3 style="margin-top:14px">Numbers the site warns about</h3><ul class="pages">${warned}</ul>` : ""}`
      : `<p class="muted">${esc(r.decision?.reason || "")}. If you know which of these is ${brand}'s website, pick it and we'll read it:</p>
         <div class="chips">${(r.decision?.votes || []).filter((x) => /^[a-z0-9.-]+\.[a-z]{2,}$/i.test(x.domain)).slice(0, 4)
           .map((x) => `<button type="button" class="chip use-domain" data-domain="${esc(x.domain)}">Use ${esc(x.domain)}<small>${esc(x.sources[0] || "")}</small></button>`).join("")}</div>`}
  </article>`;
  out.push(`<div class="split">${left}${right}</div>`);

  /* where the number appears */
  if (r.number && r.mentions?.length) {
    out.push(`<article class="card"><h2>Where ${esc(r.number)} appears on the web</h2>
      <p class="muted" style="margin:4px 0 12px">Only results whose own text contains this exact number are counted.</p>
      <ul class="mentions">${groupMentions(r.mentions).map(({ m, n }) => `<li><b>${esc(m.domain)}</b>${n > 1 ? ` <span class="dup">same text on ${n} pages</span>` : ""} ${m.official ? '<span class="tag off">official</span>' : m.directory ? '<span class="tag dir">directory</span>' : ""} ${m.complaint ? '<span class="tag bad">complaint text</span>' : ""}<br>
        ${highlight(m.snippet || m.title, digits)} <a href="${safeHref(m.url)}" target="_blank" rel="noopener nofollow">open</a></li>`).join("")}</ul></article>`);
  } else if (r.number) {
    out.push(`<article class="card"><h2>Where ${esc(r.number)} appears on the web</h2><p class="muted">No search result's text contains this exact number.</p></article>`);
  }

  /* pin audit */
  const ps = r.pin_stats || {};
  if (ps.total) {
    const pct = (n) => (100 * n / ps.total).toFixed(2);
    const none = ps.total - ps.official_number - ps.number_not_on_official;
    const bar = ps.judged ? `<div class="pinbar" role="img" aria-label="${ps.official_number} pins show an official number, ${ps.number_not_on_official} show a number not on the official pages">
        <span style="width:${pct(ps.official_number)}%;background:var(--good)"></span><span style="width:${pct(ps.number_not_on_official)}%;background:var(--warn)"></span><span style="width:${pct(none)}%;background:var(--grey-soft)"></span></div>
      <div class="legend"><span><i style="background:var(--good)"></i>${ps.official_number} show a number printed on ${esc(dom)}</span><span><i style="background:var(--warn)"></i>${ps.number_not_on_official} show a number not on its pages</span>${ps.website_not_official ? `<span>${ps.website_not_official} link to a website other than ${esc(dom)}</span>` : ""}</div>` : `<p class="muted">No official website established, so pins can't be compared.</p>`;
    const pins = (r.pins || []).map((p) => {
      const nt = p.number_status === "official" ? '<span class="tag off">number on official site</span>'
        : p.number_status === "not_on_official" ? '<span class="tag dir">number not on official pages</span>'
        : p.number_status === "warned" ? '<span class="tag bad">number the site warns about</span>' : "";
      const wt = p.website_status === "official" ? "" : p.website_status === "other" ? `<span class="tag other">website: ${esc(p.website)}</span>`
        : p.website_status === "none" ? '<span class="tag other">no website</span>' : "";
      return `<div class="pin ${p.is_user_number ? "you" : ""}"><span class="pt" title="${esc(p.title)}">${esc(p.title)}</span>
        <span class="pp">${esc(p.phone_shown || "no phone")}${p.is_user_number ? " ← your number" : ""}</span>
        <span class="pa" title="${esc(p.address)}">${esc(p.address)}${p.rating ? ` · ★ ${esc(p.rating)} (${esc(p.reviews ?? 0)})` : ""}</span>
        <span class="tags">${nt}${wt}</span></div>`;
    }).join("");
    out.push(`<details class="card more" ${ps.user_number_pins ? "open" : ""}><summary>Google Maps audit — ${ps.total} “${brand} customer care” pins near ${esc(r.city)}</summary>
      ${bar}<p class="muted" style="font-size:13px">Pins are listed by their owners and anyone can suggest edits. A number not printed on the official pages may still be a genuine local branch; mobile numbers are partly hidden for privacy.</p>
      <div class="pins">${pins}</div></details>`);
  }

  /* transparency */
  const votes = (r.decision?.votes || []).map((x) => `<li><b>${esc(x.domain)}</b> — ${x.sources.map(esc).join("; ")}</li>`).join("");
  out.push(`<details class="card more"><summary>How this was checked</summary><div class="how">
    <ol><li>Google Maps pins for “${brand} customer care” and Google results for “${brand} customer care number” (SerpApi)${r.number ? `, plus a Google search for the exact spellings of ${esc(r.number)}` : ""}.</li>
    <li>The official website is accepted only when two independent sources agree: the website most Maps pins link to, Google's own results, and the AI model's knowledge (a domain name only — the model never supplies phone numbers). ${dom ? `Result: <b>${esc(dom)}</b> (${esc(r.decision?.reason)}).` : `Result: not established — ${esc(r.decision?.reason)}.`}</li>
    <li>A Google <span class="mono">site:</span> search finds the brand's contact pages; we then read those pages directly (no credit) and copy every phone number with the words around it. Fax lines and numbers inside fraud warnings are never suggested.</li>
    <li>Your number is compared digit-for-digit after normalising +91, 0 and spacing. Complaint text only counts when it names your exact number.</li></ol>
    ${votes ? `<p><b>Candidate websites</b></p><ul class="votes">${votes}</ul>` : ""}
    <p class="muted">${r.searches} searches · ${r.credits_spent} credit${r.credits_spent === 1 ? "" : "s"} spent · ${(r.ms / 1000).toFixed(1)} s. RightNumber never says a number is safe — only whether the brand's own website prints it.</p></div></details>`);

  $("#result").innerHTML = out.join("");
  $("#result").querySelectorAll(".use-domain").forEach((b) => b.addEventListener("click", () => {
    $("#domain").value = b.dataset.domain; $(".adv").open = true; start();
  }));
  $("#result").classList.remove("hidden");
  // The trail did its job on camera; fold it so the verdict is the first thing in view.
  $("#live").classList.add("collapsed");
  if (!$("#trail-toggle")) {
    $(".trail-head").insertAdjacentHTML("beforeend", '<button id="trail-toggle" type="button" class="trail-toggle">Show trail</button>');
    $("#trail-toggle").addEventListener("click", () => {
      const c = $("#live").classList.toggle("collapsed");
      $("#trail-toggle").textContent = c ? "Show trail" : "Hide trail";
    });
  }
  $("#trail-toggle").textContent = "Show trail";
  $("#live").scrollIntoView({ behavior: "smooth", block: "start" });
}

boot();
