# TrustLens

**An explainable confidence model for organisational knowledge.** Built for the SD Worx challenge at the Tectonic Hackathon (30 September 2026).

A payroll consultant asks a question. TrustLens answers it *and* shows why they can or can't rely on that answer: which sources are current, owned, official and for the right country; where sources conflict; which client exceptions exist; and who to ask when documents are not enough.

> All data in `data/` is **synthetic and fictional**. It is not legal or payroll advice.

## Core principle: the LLM extracts, the code decides

| Layer | What it does | Deterministic? |
|---|---|---|
| Rules (`engine/rules.py`) | Checks metadata: country, supersession, freshness, status, owner, handover risk, authority | Yes |
| LLM (`engine/llm.py`) | Reads content: writes the answer, reports conflicts and exceptions as JSON | No, so its output is validated |
| Confidence (`engine/confidence.py`) | Turns rules + LLM findings into High / Medium / Low, reasons, action, expert | Yes |

The LLM never chooses the confidence level or the person to ask. If it picks a superseded document as the winner, the rules fail that source and confidence drops to Low.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # add GEMINI_API_KEY, or leave empty for offline mode
python -m pytest -q             # 31 tests, no network needed
uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-server-header
```

```bash
curl -s -X POST localhost:8000/api/ask -H 'content-type: application/json' \
  -d '{"question": "When do I pay double holiday pay for Brouwerij Van de Leie?"}'
```

Without an API key the engine runs in **offline mode**: no generated answer, but every trust signal, exclusion and expert suggestion still works.

## Project layout

```
app/        FastAPI entry point + HTTP security middleware (thin, no logic)
engine/     The trust engine (no web framework dependency)
  models.py       strict, immutable data models
  config.py       env settings + rules.yaml loading (safe_load, validated)
  loader.py       loads documents/chats/emails into one Source shape
  rules.py        Layer 1: metadata rules
  retrieval.py    keyword retrieval (swappable)
  llm.py          Layer 2: Gemini adapter, prompt, output validation (swappable)
  confidence.py   deterministic confidence + expert routing
  pipeline.py     TrustEngine.ask(): orchestrates the flow
config/rules.yaml business thresholds (change without touching code)
data/       synthetic dataset
tests/      acceptance tests (demo questions) + security tests
```

## Security measures

- **No client-controlled context.** The API accepts only `{"question": "..."}`. User, country and date are server config. Extra fields are rejected, so there's no IDOR surface.
- **No client-supplied documents.** Sources load once, server-side, from a fixed directory into read-only structures.
- **Loader hardening.** Path containment, symlinks skipped, file size limits, `yaml.safe_load` only, every record schema-validated, duplicate IDs abort startup.
- **LLM boundary.** Sources are delimited and delimiter-like text is neutralised (prompt injection). Output is JSON-validated, length-capped, and unknown source IDs are dropped (hallucination guard). Failures degrade to "no answer" without leaking error details.
- **HTTP.** CSP without inline scripts, `X-Frame-Options: DENY`, `nosniff`, no-referrer, body size limit (4 KB), per-client rate limit (protects LLM credits), generic error messages, no input echo, API docs off by default, no CORS, binds to localhost.
- **Secrets.** API key only via `.env` (gitignored). It's excluded from `repr()` and never logged. Question text is never logged either.
- **Dependencies.** Pinned. `pip-audit -r requirements.txt` reports no known vulnerabilities at the time of writing.

## What is unfinished

- Retrieval is keyword-based (IDF-weighted). Embeddings or SD Worx enterprise search would replace `KeywordRetriever`.
- Single fixed demo user. Production needs real authentication (SSO) with per-user country access, enforced server-side.
- The rate limiter is in-memory and per-process. Production needs a shared store and a proxy-aware client IP.
- The "capture this exception" action is a suggestion only. It doesn't write to the client file.
- Document types are mapped by ID in `rules.yaml` because the source metadata has no type field.
