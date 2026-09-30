// TrustLens frontend. SECURITY: all dynamic text uses textContent, never innerHTML.
// Mock mode: open /?mock=1 to render static/sample_response.json without the API.

// Used only if /api/companies can't be reached; normally questions come from data/companies.json.
const FALLBACK_QUESTIONS = [
  "What percentage is Belgian double holiday pay and when is it paid?",
  "How long is sick pay continued at 100% for a Belgian employee?",
  "What is the payroll cutoff in December in Belgium?",
];
const MOCK_COMPANY = "brouwerij-van-de-leie";
const MOCK_QUESTION = "When do I pay double holiday pay for Brouwerij Van de Leie?";
const STORAGE_KEY = "trustlens.company";

const VERDICT_TEXT = { pass: "Reliable", warn: "Use with care", fail: "Don't use" };
const TYPE_TEXT = {
  policy: "Policy", procedure: "Procedure", client_note: "Client note", email: "Email", chat: "Teams chat",
};
const LEVELS = ["Low", "Medium", "High"];
const FALLBACK_AS_OF = "2026-09-30";

// Stroke icons, 24x24 grid. Hand-drawn paths, no icon library (CSP: self only).
const ICONS = {
  policy: ["M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z", "M14 3v5h5", "M9 13h6", "M9 17h6"],
  procedure: ["M4 6l1.5 1.5L8 5", "M11 6h9", "M4 12l1.5 1.5L8 11", "M11 12h9", "M4 18l1.5 1.5L8 17", "M11 18h9"],
  client_note: ["M5 4h14v10l-6 6H5z", "M13 20v-6h6"],
  email: ["M3 6h18v12H3z", "M3 7l9 6 9-6"],
  chat: ["M4 5h16v11H9l-5 4z", "M8 9h8", "M8 12h5"],
  person: ["M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8z", "M4 21c1-4 4-6 8-6s7 2 8 6"],
  calendar: ["M4 6h16v14H4z", "M4 10h16", "M8 3v5", "M16 3v5"],
  pass: ["M5 12l5 5L20 7"],
  warn: ["M12 3l10 18H2z", "M12 10v5", "M12 18v.01"],
  fail: ["M6 6l12 12", "M18 6L6 18"],
  info: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M12 11v6", "M12 7.5v.01"],
  spark: ["M12 3v4", "M12 17v4", "M3 12h4", "M17 12h4", "M6 6l2.5 2.5", "M15.5 15.5L18 18", "M18 6l-2.5 2.5", "M8.5 15.5L6 18"],
  rules: ["M4 7h10", "M18 7h2", "M16 5v4", "M4 17h2", "M10 17h10", "M8 15v4"],
  clock: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M12 7v5l3 2"],
  building: ["M4 21V4h11v17", "M15 9h5v12", "M2 21h20", "M8 8h3", "M8 12h3", "M8 16h3"],
  chevron: ["M6 9l6 6 6-6"],
  search: ["M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14z", "M20 20l-4-4"],
  pdf: ["M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z", "M14 3v5h5", "M8 14h8", "M8 17h5"],
  external: ["M14 4h6v6", "M20 4l-9 9", "M18 14v6H4V6h6"],
  globe: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M3 12h18", "M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3z"],
};

const $ = (id) => document.getElementById(id);
const isMock = new URLSearchParams(location.search).get("mock") === "1";
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const state = {
  data: null, focusId: null, asOf: FALLBACK_AS_OF,
  companies: [], generalQuestions: FALLBACK_QUESTIONS, company: null, activeOption: -1,
};

// Server path of a document's PDF. The server checks access; the UI only links.
const pdfUrl = (id) => `/api/sources/${encodeURIComponent(id)}/pdf`;

function pdfLink(id, text, className) {
  const a = el("a", className);
  a.href = pdfUrl(id);
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  a.appendChild(icon("pdf"));
  a.appendChild(el("span", null, text));
  a.appendChild(icon("external", "ext"));
  return a;
}

function storageGet(key) {
  try { return window.localStorage.getItem(key); } catch { return null; }
}

function storageSet(key, value) {
  try {
    if (value) window.localStorage.setItem(key, value); else window.localStorage.removeItem(key);
  } catch { /* storage unavailable: selection just isn't remembered */ }
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function icon(name, className) {
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("class", `icon ${className || ""}`.trim());
  (ICONS[name] || ICONS.info).forEach((d) => {
    const p = document.createElementNS(NS, "path");
    p.setAttribute("d", d);
    svg.appendChild(p);
  });
  return svg;
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function formatDate(iso) {
  if (!iso) return "no date";
  const d = new Date(iso + "T00:00:00");
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

function daysBetween(fromIso, toIso) {
  const a = new Date(fromIso + "T00:00:00");
  const b = new Date(toIso + "T00:00:00");
  return Math.round((b - a) / 86400000);
}

// "jens.wouters" -> "Jens Wouters"; external addresses stay as they are.
function personName(id) {
  if (!id) return "No owner";
  if (id.includes("@")) return id;
  return id.split(".").map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join(" ");
}

function setStatus(text, isError = false) {
  const s = $("status");
  s.textContent = text || "";
  s.classList.toggle("error", isError);
}

function provenance(target, iconName, text) {
  clear(target);
  target.appendChild(icon(iconName));
  target.appendChild(el("span", null, text));
}

function sourceButton(id) {
  const b = el("button", "src-ref", id);
  b.type = "button";
  b.addEventListener("click", () => focusSource(id, true));
  return b;
}

// ---------- rendering ----------

function renderHandover(data) {
  const box = $("handover");
  clear(box);
  let hit = null;
  for (const s of data.sources || []) {
    const r = (s.rules || []).find((x) => x.rule === "handover_risk" && x.status !== "pass");
    if (r) { hit = { s, r }; break; }
  }
  box.hidden = !hit;
  if (!hit) return;
  const date = (hit.r.label.match(/\d{4}-\d{2}-\d{2}/) || [])[0];
  const days = date ? daysBetween(state.asOf, date) : null;
  box.appendChild(icon("clock"));
  const text = el("span");
  text.appendChild(el("strong", null, personName(hit.s.owner)));
  const when = date ? ` leaves on ${formatDate(date)}${days !== null && days >= 0 ? `, in ${days} days` : ""}.` : " is leaving.";
  text.appendChild(document.createTextNode(` owns ${hit.s.id} and${when} Capture this knowledge before then.`));
  box.appendChild(text);
}

function renderAnswer(data) {
  const a = data.answer || {};
  provenance($("answer-prov"), "spark", "Answer, read from the sources by the AI");
  $("answer-text").textContent = a.answer || "No answer.";
  const cited = $("cited");
  clear(cited);
  const ids = a.cited_source_ids || [];
  if (!ids.length) return;
  cited.appendChild(el("span", "cited-label", "Based on"));
  ids.forEach((id) => cited.appendChild(sourceButton(id)));
}

function renderConfidence(data) {
  const c = data.confidence || {};
  const level = LEVELS.includes(c.level) ? c.level : "Low";
  const card = $("confidence-card");
  card.classList.remove("lvl-high", "lvl-medium", "lvl-low");
  card.classList.add(`lvl-${level.toLowerCase()}`);
  provenance($("conf-prov"), "rules", "Confidence, decided by trust rules, not the AI");

  const idx = LEVELS.indexOf(level);
  [...$("meter").children].forEach((seg, i) => seg.classList.toggle("on", i <= idx));
  $("level").textContent = `${level} confidence`;

  const list = $("reasons");
  clear(list);
  (c.reasons || []).forEach((r) => list.appendChild(el("li", null, r)));
  $("action").textContent = c.action || "";
  $("action").hidden = !c.action;
}

function renderExpert(data) {
  const e = data.ask_expert;
  $("expert-card").hidden = !e;
  if (!e) return;
  $("expert-name").textContent = e.name || personName(e.id);
  $("expert-role").textContent = e.role || "";
  $("expert-why").textContent = e.why || "";
}

function renderFindings(data) {
  const a = data.answer || {};
  const list = $("findings");
  clear(list);

  const add = (kind, tag, ids, summary, sub, joiner) => {
    const li = el("li", `finding ${kind}`);
    const head = el("div", "finding-head");
    head.appendChild(el("span", "finding-tag", tag));
    const refs = el("span", "finding-ids");
    (ids || []).forEach((id, i) => {
      if (i) refs.appendChild(el("span", "joiner", joiner));
      refs.appendChild(sourceButton(id));
    });
    head.appendChild(refs);
    li.appendChild(head);
    li.appendChild(el("p", "finding-text", summary));
    if (sub) li.appendChild(el("p", "finding-sub", sub));
    list.appendChild(li);
  };

  (a.conflicts || []).forEach((c) => add(
    c.resolved ? "resolved" : "unresolved",
    c.resolved ? "Resolved conflict" : "Unresolved conflict",
    c.source_ids, c.summary, c.resolution, "vs",
  ));
  (a.exceptions || []).forEach((x) => add("exception", "Exception", x.source_ids, x.summary, null, "+"));

  $("findings-block").hidden = list.children.length === 0;
}

function thumbLines(n) {
  const box = el("div", "lines");
  for (let i = 0; i < n; i++) box.appendChild(el("span"));
  return box;
}

// A small drawn preview of the source, shaped like its type.
function buildThumb(s) {
  const type = s.source_type || "policy";
  const kind = { email: "email", chat: "chat", client_note: "note" }[type] || "page";
  const t = el("div", `thumb t-${kind}`);

  const head = el("div", "thumb-head");
  head.appendChild(icon(type));
  head.appendChild(el("span", null, TYPE_TEXT[type] || type));
  head.appendChild(el("span", "thumb-id", s.id));
  if (s.has_pdf) head.appendChild(el("span", "thumb-pdf", "PDF"));
  t.appendChild(head);

  if (kind === "email") {
    const from = el("p", "mail-row");
    from.appendChild(el("span", "mail-key", "From"));
    from.appendChild(el("span", null, s.owner || "unknown"));
    const subj = el("p", "mail-row");
    subj.appendChild(el("span", "mail-key", "Subject"));
    subj.appendChild(el("span", null, (s.title || "").replace(/^Email:\s*/i, "")));
    t.appendChild(from);
    t.appendChild(subj);
    t.appendChild(thumbLines(3));
  } else if (kind === "chat") {
    t.appendChild(el("p", "thumb-title", s.title));
    const b = el("div", "bubbles");
    ["", "me", ""].forEach((c) => b.appendChild(el("span", `bubble ${c}`.trim())));
    t.appendChild(b);
  } else {
    t.appendChild(el("p", "thumb-title", s.title));
    t.appendChild(thumbLines(kind === "note" ? 3 : 5));
  }

  const verdict = s.verdict || "warn";
  t.appendChild(el("span", `stamp s-${verdict}`, VERDICT_TEXT[verdict] || verdict));
  return t;
}

function renderSources(data) {
  const index = $("index");
  const stack = $("stack");
  clear(index);
  clear(stack);
  const winner = data.answer && data.answer.winning_source_id;

  (data.sources || []).forEach((s) => {
    const verdict = s.verdict || "warn";

    const li = el("li");
    const item = el("button", `index-item v-${verdict}`);
    item.type = "button";
    item.dataset.id = s.id;
    item.appendChild(el("span", "index-id", s.id));
    item.appendChild(el("span", "index-title", s.title));
    item.appendChild(icon(verdict, "index-mark"));
    item.addEventListener("click", () => focusSource(s.id, false));
    li.appendChild(item);
    index.appendChild(li);

    const frame = el("button", "frame");
    frame.type = "button";
    frame.dataset.id = s.id;
    frame.setAttribute("aria-label", `Inspect ${s.id}: ${s.title}`);
    ["tl", "tr", "bl", "br"].forEach((c) => frame.appendChild(el("span", `corner c-${c}`)));
    frame.appendChild(buildThumb(s));
    if (s.id === winner) frame.appendChild(el("span", "main-tag", "Main source"));
    frame.addEventListener("click", () => focusSource(s.id, false));
    stack.appendChild(frame);
  });

  if (!stack.children.length) stack.appendChild(el("p", "empty", "No matching sources found."));
}

function renderInspector(s) {
  const box = $("inspector");
  clear(box);
  if (!s) return;
  const verdict = s.verdict || "warn";
  const winner = state.data.answer && state.data.answer.winning_source_id;

  const type = el("p", "insp-type");
  type.appendChild(icon(s.source_type));
  type.appendChild(el("span", null, `${TYPE_TEXT[s.source_type] || s.source_type} ${s.id}`));
  box.appendChild(type);
  box.appendChild(el("h3", "insp-title", s.title));

  const pills = el("div", "insp-pills");
  pills.appendChild(el("span", `pill pill-${verdict}`, VERDICT_TEXT[verdict] || verdict));
  if (s.id === winner) pills.appendChild(el("span", "pill pill-main", "Main source"));
  box.appendChild(pills);

  const meta = el("dl", "insp-meta");
  const row = (iconName, label, value) => {
    const wrap = el("div");
    const dt = el("dt");
    dt.appendChild(icon(iconName));
    dt.appendChild(el("span", "sr-only", label));
    wrap.appendChild(dt);
    wrap.appendChild(el("dd", null, value));
    meta.appendChild(wrap);
  };
  row("person", "Owner", personName(s.owner));
  row("calendar", "Last updated", formatDate(s.last_updated));
  box.appendChild(meta);
  if (s.has_pdf) box.appendChild(pdfLink(s.id, "Open document (PDF)", "insp-pdf"));

  box.appendChild(el("p", "insp-sub", "Trust signals"));
  const rules = el("ul", "rules");
  (s.rules || []).forEach((r) => {
    const li = el("li", `rule r-${r.status}`);
    li.appendChild(icon(r.status));
    li.appendChild(el("span", null, r.label));
    rules.appendChild(li);
  });
  if (!rules.children.length) rules.appendChild(el("li", "rule", "No signals recorded."));
  box.appendChild(rules);
}

function focusSource(id, scroll) {
  const s = (state.data.sources || []).find((x) => x.id === id);
  if (!s) return;
  state.focusId = id;
  document.querySelectorAll(".index-item").forEach((n) => {
    const on = n.dataset.id === id;
    n.classList.toggle("is-active", on);
    if (on) n.setAttribute("aria-current", "true"); else n.removeAttribute("aria-current");
  });
  document.querySelectorAll(".frame").forEach((n) => {
    const on = n.dataset.id === id;
    n.classList.toggle("is-active", on);
    n.setAttribute("aria-pressed", String(on));
  });
  renderInspector(s);
  const behavior = reduceMotion ? "auto" : "smooth";
  if (scroll) $("lens").scrollIntoView({ behavior, block: "start" });
  const frame = document.querySelector(`.frame[data-id="${CSS.escape(id)}"]`);
  if (frame) frame.scrollIntoView({ behavior, block: "nearest", inline: "center" });
}

function renderExcluded(data) {
  const items = data.excluded_sources || [];
  const box = $("excluded");
  box.hidden = items.length === 0;
  $("excluded-summary").textContent = `${items.length} excluded source${items.length === 1 ? "" : "s"}, listed so nothing is hidden`;
  const list = $("excluded-list");
  clear(list);
  items.forEach((x) => {
    const li = el("li");
    li.appendChild(el("strong", null, `${x.id} ${x.title}`));
    li.appendChild(el("span", "excluded-reason", x.reason));
    list.appendChild(li);
  });
}

function render(data) {
  state.data = data;
  if (data.context && data.context.as_of_date) state.asOf = data.context.as_of_date;
  renderHandover(data);
  renderAnswer(data);
  renderConfidence(data);
  renderExpert(data);
  renderFindings(data);
  renderSources(data);
  renderExcluded(data);
  $("result").hidden = false;

  const sources = data.sources || [];
  const winner = data.answer && data.answer.winning_source_id;
  const first = sources.some((s) => s.id === winner) ? winner : (sources[0] && sources[0].id);
  if (first) focusSource(first, false);
  else renderInspector(null);
}

// ---------- data ----------

async function ask(question) {
  const btn = $("ask-btn");
  btn.disabled = true;
  document.body.classList.add("is-loading");
  setStatus("Checking sources…");
  try {
    let res;
    if (isMock) {
      res = await fetch("/static/sample_response.json", { cache: "no-store" });
    } else {
      res = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(state.company ? { question, company: state.company } : { question }),
      });
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setStatus(data.detail || data.error || "Something went wrong. Please try again.", true);
      return;
    }
    setStatus("");
    render(data);
  } catch (err) {
    setStatus("Could not reach the server. Start it with uvicorn and try again.", true);
  } finally {
    btn.disabled = false;
    document.body.classList.remove("is-loading");
  }
}

async function loadContext() {
  const ctx = $("context");
  try {
    if (isMock) throw new Error("mock");
    const res = await fetch("/api/context");
    const c = await res.json();
    if (c.as_of_date) state.asOf = c.as_of_date;
    ctx.textContent = `${personName(c.user)}, ${c.country}, as of ${formatDate(c.as_of_date)}`;
  } catch {
    ctx.textContent = `Arne Goossens, BE, as of ${formatDate(FALLBACK_AS_OF)}`;
  }
}

// ---------- companies ----------

function currentCompany() {
  return state.companies.find((c) => c.id === state.company) || null;
}

function updateCounter() {
  $("counter").textContent = `${$("question").value.length} / 500`;
}

function renderChips() {
  const chips = $("chips");
  clear(chips);
  const company = currentCompany();
  const questions = company ? company.questions : state.generalQuestions;
  questions.forEach((text) => {
    const b = el("button", "chip", text);
    b.type = "button";
    b.addEventListener("click", () => { $("question").value = text; updateCounter(); ask(text); });
    chips.appendChild(b);
  });
}

function renderCompanyCard() {
  const company = currentCompany();
  const card = $("company-card");
  card.hidden = !company;
  $("company-btn-text").textContent = company ? company.name : "All clients";
  if (!company) return;
  $("company-name").textContent = company.name;
  $("company-meta").textContent = [
    `${company.sector}, ${company.city}`,
    company.joint_committee,
    `${company.employees} employees`,
    `Consultant: ${company.consultant}`,
  ].join("   /   ");
  const docs = $("company-docs");
  clear(docs);
  company.documents.forEach((d) => {
    const li = el("li");
    li.appendChild(pdfLink(d.id, `${d.id}  ${d.title}`, "doc-link"));
    docs.appendChild(li);
  });
  if (!company.documents.length) docs.appendChild(el("li", "empty", "No client documents on file."));
}

// One option per company, plus "All clients". Search matches name, city, sector and PC.
function companyOptions() {
  const term = $("company-search").value.trim().toLowerCase();
  const all = [{ id: null, name: "All clients", sub: "General questions, no client documents" }]
    .concat(state.companies.map((c) => ({ id: c.id, name: c.name, sub: `${c.sector}, ${c.city}  /  ${c.joint_committee}` })));
  if (!term) return all;
  return all.filter((o) => `${o.name} ${o.sub}`.toLowerCase().includes(term));
}

function renderCompanyList() {
  const list = $("company-list");
  clear(list);
  const options = companyOptions();
  if (state.activeOption >= options.length) state.activeOption = options.length - 1;
  options.forEach((o, i) => {
    const li = el("li", "option");
    li.id = `company-opt-${i}`;
    li.setAttribute("role", "option");
    li.setAttribute("aria-selected", String(o.id === state.company));
    li.classList.toggle("is-active", i === state.activeOption);
    li.appendChild(icon(o.id ? "building" : "globe"));
    const text = el("span", "option-text");
    text.appendChild(el("span", "option-name", o.name));
    text.appendChild(el("span", "option-sub", o.sub));
    li.appendChild(text);
    if (o.id === state.company) li.appendChild(icon("pass", "option-check"));
    li.addEventListener("mousedown", (e) => e.preventDefault()); // keep focus in the search box
    li.addEventListener("click", () => selectCompany(o.id));
    list.appendChild(li);
  });
  if (!options.length) list.appendChild(el("li", "option-empty", "No client matches your search."));
  const search = $("company-search");
  if (state.activeOption >= 0 && options.length) {
    search.setAttribute("aria-activedescendant", `company-opt-${state.activeOption}`);
  } else {
    search.removeAttribute("aria-activedescendant");
  }
  return options;
}

function openSwitcher() {
  $("company-panel").hidden = false;
  $("company-btn").setAttribute("aria-expanded", "true");
  $("company-search").value = "";
  state.activeOption = -1;
  renderCompanyList();
  $("company-search").focus();
}

function closeSwitcher(returnFocus) {
  $("company-panel").hidden = true;
  $("company-btn").setAttribute("aria-expanded", "false");
  if (returnFocus) $("company-btn").focus();
}

function selectCompany(id, options = {}) {
  const changed = id !== state.company;
  state.company = id;
  storageSet(STORAGE_KEY, id);
  renderCompanyCard();
  renderChips();
  if (!options.silent) closeSwitcher(true);
  if (changed && !options.keepResult) {
    // An answer for another client would be misleading next to the new client's details.
    $("result").hidden = true;
    const company = currentCompany();
    setStatus(company ? `Now working on ${company.name}.` : "Now working on general questions.");
  }
}

function wireSwitcher() {
  const btn = $("company-btn");
  const search = $("company-search");
  btn.appendChild(icon("chevron", "chevron"));
  btn.addEventListener("click", () => ($("company-panel").hidden ? openSwitcher() : closeSwitcher(true)));
  search.addEventListener("input", () => { state.activeOption = 0; renderCompanyList(); });
  search.addEventListener("keydown", (e) => {
    const options = companyOptions();
    if (e.key === "ArrowDown") {
      e.preventDefault();
      state.activeOption = Math.min(options.length - 1, state.activeOption + 1);
      renderCompanyList();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      state.activeOption = Math.max(0, state.activeOption - 1);
      renderCompanyList();
    } else if (e.key === "Enter") {
      e.preventDefault(); // this input sits inside the question form: never submit it
      const pick = options[state.activeOption] || options[0];
      if (pick) selectCompany(pick.id);
    } else if (e.key === "Escape") {
      e.preventDefault();
      closeSwitcher(true);
    }
  });
  document.addEventListener("click", (e) => {
    if (!$("company-panel").hidden && !$("switcher").contains(e.target)) closeSwitcher(false);
  });
}

async function loadCompanies() {
  try {
    const res = await fetch("/api/companies");
    if (!res.ok) throw new Error("companies");
    const data = await res.json();
    state.companies = data.companies || [];
    if ((data.general_questions || []).length) state.generalQuestions = data.general_questions;
  } catch {
    state.companies = [];
  }
  const saved = isMock ? MOCK_COMPANY : storageGet(STORAGE_KEY);
  const valid = state.companies.some((c) => c.id === saved) ? saved : null;
  selectCompany(valid, { silent: true, keepResult: true });
  setStatus("");
}

// ---------- wiring ----------

async function init() {
  $("mock-banner").hidden = !isMock;
  const q = $("question");
  wireSwitcher();
  renderChips();

  q.addEventListener("input", updateCounter);
  q.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("ask-form").requestSubmit(); }
  });
  $("ask-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = q.value.trim();
    if (text.length < 3) { setStatus("Type a question of at least 3 characters.", true); return; }
    ask(text);
  });

  loadContext();
  await loadCompanies();
  if (isMock) { q.value = MOCK_QUESTION; updateCounter(); ask(MOCK_QUESTION); }
}

document.addEventListener("DOMContentLoaded", init);
