// TrustLens frontend. SECURITY: all dynamic text uses textContent, never innerHTML.
// Mock mode: open /?mock=1 to render static/sample_response.json without the API.

const DEMO_QUESTIONS = [
  "When do I pay double holiday pay for Brouwerij Van de Leie?",
  "How long is sick pay continued at 100% for a Belgian employee?",
  "When is the end-of-year premium paid for PC 200 clients this year?",
  "What percentage is Belgian double holiday pay and when is it paid?",
  "What is the payroll cutoff in December in Belgium?",
];

const VERDICT_ICON = { pass: "✓", warn: "!", fail: "✕", info: "i" };
const VERDICT_TEXT = { pass: "Reliable", warn: "Use with care", fail: "Don't use" };
const TYPE_TEXT = {
  policy: "Policy", procedure: "Procedure", client_note: "Client note", email: "Email", chat: "Chat",
};

const $ = (id) => document.getElementById(id);
const isMock = new URLSearchParams(location.search).get("mock") === "1";

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
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

function setStatus(text, isError = false) {
  const s = $("status");
  s.textContent = text || "";
  s.classList.toggle("error", isError);
}

// ---------- rendering ----------

function renderAnswer(data) {
  const a = data.answer || {};
  $("answer-text").textContent = a.answer || "No answer.";
  const cited = (a.cited_source_ids || []).join(", ");
  $("cited").textContent = cited ? `Based on: ${cited}` : "";
}

function renderConfidence(data) {
  const c = data.confidence || {};
  const level = (c.level || "Low").toLowerCase();
  const card = $("confidence-card");
  card.classList.remove("lvl-high", "lvl-medium", "lvl-low");
  card.classList.add(`lvl-${level}`);
  $("level").textContent = c.level || "Low";

  const list = $("reasons");
  clear(list);
  (c.reasons || []).forEach((r) => list.appendChild(el("li", null, r)));
  $("action").textContent = c.action || "";
}

function renderExpert(data) {
  const e = data.ask_expert;
  $("expert-card").hidden = !e;
  if (!e) return;
  $("expert-name").textContent = `${e.id} · ${e.role || ""}`;
  $("expert-why").textContent = e.why || "";
}

function renderFindings(data) {
  const a = data.answer || {};
  const list = $("findings");
  clear(list);

  (a.conflicts || []).forEach((c) => {
    const li = el("li", c.resolved ? "finding resolved" : "finding unresolved");
    li.appendChild(el("span", "finding-tag", c.resolved ? "Resolved conflict" : "Unresolved conflict"));
    li.appendChild(el("span", "finding-ids", (c.source_ids || []).join(" vs ")));
    li.appendChild(el("p", "finding-text", c.summary));
    if (c.resolution) li.appendChild(el("p", "finding-sub", c.resolution));
    list.appendChild(li);
  });

  (a.exceptions || []).forEach((x) => {
    const li = el("li", "finding exception");
    li.appendChild(el("span", "finding-tag", "Exception"));
    li.appendChild(el("span", "finding-ids", (x.source_ids || []).join(", ")));
    li.appendChild(el("p", "finding-text", x.summary));
    list.appendChild(li);
  });

  $("findings-card").hidden = list.children.length === 0;
}

function renderSources(data) {
  const wrap = $("sources");
  clear(wrap);
  const winner = data.answer && data.answer.winning_source_id;

  (data.sources || []).forEach((s) => {
    const verdict = s.verdict || "warn";
    const card = el("article", `source v-${verdict}`);

    const head = el("div", "source-head");
    head.appendChild(el("span", `badge b-${verdict}`, VERDICT_ICON[verdict] || "?"));
    const titleBox = el("div", "source-titles");
    titleBox.appendChild(el("h3", "source-title", s.title));
    const meta = [s.id, TYPE_TEXT[s.source_type] || s.source_type, s.owner || "no owner", formatDate(s.last_updated)];
    titleBox.appendChild(el("p", "source-meta", meta.join(" · ")));
    head.appendChild(titleBox);
    const right = el("div", "source-right");
    if (s.id === winner) right.appendChild(el("span", "pill pill-main", "Main source"));
    right.appendChild(el("span", `pill pill-${verdict}`, VERDICT_TEXT[verdict] || verdict));
    head.appendChild(right);
    card.appendChild(head);

    const rules = el("ul", "rules");
    (s.rules || []).forEach((r) => {
      const li = el("li", `rule r-${r.status}`);
      li.appendChild(el("span", "rule-icon", VERDICT_ICON[r.status] || "·"));
      li.appendChild(el("span", "rule-label", r.label));
      rules.appendChild(li);
    });
    card.appendChild(rules);
    wrap.appendChild(card);
  });

  if (!wrap.children.length) wrap.appendChild(el("p", "empty", "No matching sources found."));
}

function renderExcluded(data) {
  const items = data.excluded_sources || [];
  const box = $("excluded");
  box.hidden = items.length === 0;
  $("excluded-summary").textContent = `Excluded sources (${items.length}): shown so nothing is hidden`;
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
  renderAnswer(data);
  renderConfidence(data);
  renderExpert(data);
  renderFindings(data);
  renderSources(data);
  renderExcluded(data);
  $("result").hidden = false;
}

// ---------- data ----------

async function ask(question) {
  const btn = $("ask-btn");
  btn.disabled = true;
  setStatus("Checking sources…");
  try {
    let res;
    if (isMock) {
      res = await fetch("sample_response.json", { cache: "no-store" });
    } else {
      res = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setStatus(data.error || "Something went wrong. Please try again.", true);
      return;
    }
    setStatus("");
    render(data);
  } catch (err) {
    setStatus("Could not reach the server. Is it running?", true);
  } finally {
    btn.disabled = false;
  }
}

async function loadContext() {
  const ctx = $("context");
  try {
    if (isMock) throw new Error("mock");
    const res = await fetch("/api/context");
    const c = await res.json();
    ctx.textContent = `${c.name} · ${c.country} · as of ${formatDate(c.as_of_date)}`;
  } catch {
    ctx.textContent = "Arne Goossens · BE · as of 30 Sep 2026";
  }
}

// ---------- wiring ----------

function init() {
  $("mock-banner").hidden = !isMock;
  const q = $("question");
  const counter = $("counter");
  const updateCounter = () => { counter.textContent = `${q.value.length} / 500`; };

  const chips = $("chips");
  DEMO_QUESTIONS.forEach((text, i) => {
    const b = el("button", "chip", i === 0 ? `★ ${text}` : text);
    b.type = "button";
    b.addEventListener("click", () => { q.value = text; updateCounter(); ask(text); });
    chips.appendChild(b);
  });

  q.addEventListener("input", updateCounter);
  q.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("ask-form").requestSubmit(); }
  });
  $("ask-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = q.value.trim();
    if (!text) { setStatus("Type a question first.", true); return; }
    ask(text);
  });

  loadContext();
  if (isMock) { q.value = DEMO_QUESTIONS[0]; updateCounter(); ask(DEMO_QUESTIONS[0]); }
}

document.addEventListener("DOMContentLoaded", init);
