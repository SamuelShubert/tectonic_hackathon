# TrustLens

**An explainable confidence model for organisational knowledge.** Built for the SD Worx challenge at the Tectonic Hackathon (30 September 2026): *Find it. Understand it. Trust it.*

A payroll consultant asks a question. TrustLens answers it *and* shows a trust receipt: which sources are current, owned, official and for the right country; where sources conflict; which client exceptions exist; who to ask; and a High / Medium / Low confidence with the reasons and a next action.

> All data in `data/` is **synthetic and fictional**. It is not legal or payroll advice.

## Core principle: the LLM extracts, the code decides

| Layer | What it does | Deterministic? |
|---|---|---|
| Rules (`engine/rules.py`) | Checks metadata: country, supersession, freshness, status, owner, handover risk, authority | Yes |
| LLM (`engine/llm.py`) | Reads content: writes the answer, reports conflicts and exceptions as JSON | No, so its output is validated |
| Confidence (`engine/confidence.py`) | Turns rules + LLM findings into High / Medium / Low, reasons, action and the person to ask | Yes |

The LLM never chooses the confidence level or the person to ask. If it picks a superseded document as the winner, the rules fail that source and confidence drops to Low.

TrustLens is **model-agnostic**. It works with Gemini (API key or Vertex AI) or any OpenAI-compatible provider. The demo runs on `openai/gpt-oss-120b` via Groq.

## Run it (Windows)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env
python -m pytest -q
uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-server-header
```

On macOS/Linux use `source .venv/bin/activate` and `cp`.

Then open:
- **http://127.0.0.1:8000**: the live app
- **http://127.0.0.1:8000/?mock=1**: the UI rendered from `static/sample_response.json` (the Brouwerij Van de Leie example), no LLM needed

### Choosing the LLM (in `.env`)

The engine uses the first option that is configured:

1. `GEMINI_API_KEY`: Google AI Studio key
2. `LLM_API_KEY` + `LLM_BASE_URL` + `LLM_MODEL`: any OpenAI-compatible provider, for example Groq (`https://api.groq.com/openai/v1`, `openai/gpt-oss-120b`) or OpenRouter
3. `GOOGLE_CLOUD_PROJECT`: Vertex AI with Application Default Credentials (`gcloud auth application-default login`)
4. Nothing set: **offline mode**. There is no generated answer, but every trust signal, exclusion and expert suggestion still works.

## Clients, documents and demo questions

TrustLens works per **client company**. Pick a client with the switcher (search by name, city, sector or joint committee), or stay on **All clients** for general questions. The engine then uses the general sources plus **only that client's** sources. Another client's files are never retrieved, sent to the LLM or shown.

Every document can be opened as a PDF (the "Open document" link on a source, or the client's document list). The PDFs are generated from `data/documents` by `python scripts/build_pdfs.py`.

All three companies are fictional:

| Client | Profile | Question | Expected |
|---|---|---|---|
| **Brouwerij Van de Leie NV** | Brewery, Kortrijk, PC 118 | When do I pay double holiday pay for Brouwerij Van de Leie? | April: an exception found only in an email and a draft note, and its owner leaves on 15 Oct. **Medium** |
| **Vandaele Logistics NV** | Transport, Antwerp, PC 140.03 | What is the meal voucher value per working day at Vandaele Logistics? | EUR 8.00 from the current client file; the 2024 file (EUR 7.00) is superseded. **High** |
| **Nordlicht Software BV** | Software, Ghent, PC 200 | What home-working allowance does Nordlicht Software pay per month? | The client file says EUR 150, but a newer Teams message says EUR 175. **Low**, unresolved |

General questions (All clients):

| Question | Expected |
|---|---|
| What percentage is Belgian double holiday pay and when is it paid? | 92%, May/June. **High** |
| When is the end-of-year premium paid for PC 200 clients this year? | Unresolved conflict between the procedure and a newer Teams chat. **Low** |
| What is the payroll cutoff in December in Belgium? | 15 December (an untracked old copy says 18). **High** |
| How long is sick pay continued at 100% for a Belgian employee? | First 30 days (the German policy is excluded). **High** |

All of these give the expected confidence level with `gpt-oss-120b`. The free Groq tier limits tokens per minute, so wait about 15 seconds between questions.

## Project layout

```
app/        FastAPI entry point + HTTP security middleware (thin, no logic)
engine/     the trust engine (no web framework dependency)
  models.py       strict, immutable data models
  config.py       env settings + rules.yaml loading (safe_load, validated)
  loader.py       loads documents, chats and emails into one Source shape
  rules.py        Layer 1: metadata rules
  retrieval.py    keyword retrieval (swappable)
  llm.py          Layer 2: LLM adapters (Gemini, Vertex, OpenAI-compatible), prompt, output validation
  confidence.py   deterministic confidence + expert routing
  pipeline.py     TrustEngine.ask(): runs the flow
config/rules.yaml business thresholds (change without touching code)
data/       synthetic dataset: documents, chats, emails, experts, companies.json, pdf/
scripts/    build_pdfs.py: renders data/documents to data/pdf (reportlab, dev only)
static/     frontend: plain HTML/CSS/JS, no framework, no CDN
tests/      acceptance tests (demo questions) + security tests
```

## Security measures

- **No client-controlled context.** The API accepts only `{"question": "...", "company": "..."}`. User, country and date are server config, and extra fields are rejected.
- **Client isolation (authorization).** The company ID is checked server-side against the user's portfolio (`data/companies.json`). Unknown and forbidden companies get the same 403, so IDs can't be probed. Other clients' sources are filtered out before retrieval, so they never reach the LLM or the response.
- **Document access.** `GET /api/sources/{id}/pdf` accepts only `DOC-nnn`, looks the file up in a map built at startup (never a path from the request), and re-checks country and client access. Every refusal is the same 404.
- **Loader hardening.** Path containment, symlinks skipped, file size limits, `yaml.safe_load` only, every record schema-validated, and duplicate IDs abort startup.
- **LLM boundary.** Sources are wrapped in delimiters and delimiter-like text is neutralised (prompt injection). Output is JSON-validated and length-capped, and unknown source IDs are dropped (hallucination guard). Failures degrade to "no answer" without leaking error details.
- **HTTP.** Strict CSP (`default-src 'self'`, no inline scripts or styles), `X-Frame-Options: DENY`, `nosniff`, `no-referrer`, a 4 KB body limit, a per-client rate limit (protects LLM credits), generic error messages, no input echo, API docs off by default, no CORS, and binding to localhost.
- **Frontend.** All dynamic text is set with `textContent`, never `innerHTML`. Icons are inline SVG with no external libraries.
- **Secrets.** Keys live only in `.env` (git-ignored), never in `repr()` or logs. `LLM_BASE_URL` must be `https`. Question text is never logged.
- **Dependencies.** Pinned in `requirements.txt`.

## What is unfinished

- Retrieval is keyword-based (IDF-weighted). Embeddings or SD Worx enterprise search would replace `KeywordRetriever`.
- Company portfolios are static JSON. Production would read them from the CRM, per signed-in user.
- PDFs are generated from Markdown; production would link to the originals in SharePoint.
- Emails and Teams chats are simulated with JSON files. Production would read Microsoft 365 via the Graph API with the user's own permissions.
- There is a single fixed demo user. Production needs real authentication (SSO) with per-user country access, enforced server-side.
- The rate limiter is in-memory and per-process. Production needs a shared store and a proxy-aware client IP.
- The "capture this exception" action is a suggestion only. It doesn't write to the client file.
- The hackathon GCP project blocks every Vertex AI model by organisation policy (`vertexai.allowedModels` = deny all), so the demo uses Groq. The Vertex code path is implemented but untested end to end.
- Free LLM tiers are rate-limited. Questions asked too quickly get "Answer unavailable" until the limit resets.
- The UI is light mode only.

## Credits

Engine and tests initially written by Agnius Liobikas. Frontend, integration, LLM adapters and the final version by Samuel Shubert.
