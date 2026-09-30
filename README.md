# TrustLens

**An explainable confidence model for organisational knowledge.**
Built at the Tectonic Hackathon (30 Sep 2026) for the SD Worx challenge *"Unlock the Knowledge Within – Find it. Understand it. Trust it."*

A payroll consultant asks a question. TrustLens answers it **and shows why they can trust the answer, or why they can't yet**: which sources it used, whether they are current, official, owned by someone still at the company, and relevant for their country; where sources disagree; which exceptions apply; and who to ask.

> **Core principle: the LLM extracts, the code decides.**
> Python rules judge each source from its metadata. The LLM reads the content and reports the answer, conflicts and exceptions as JSON. Python then computes the confidence (High / Medium / Low) and picks the expert, so every "why Medium?" points to a specific rule.

## How to run

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then fill in your values; never commit .env
uvicorn app.main:app --port 8000
```

Open http://localhost:8000.
Open http://localhost:8000/?mock=1 to see the UI with a sample response, without the API or Gemini.

### Gemini (Vertex AI)
```bash
gcloud auth application-default login
gcloud config set project <your-project-id>
```
Set `GOOGLE_CLOUD_PROJECT` in `.env`. Alternatively use a Google AI Studio key (`GOOGLE_API_KEY`, and `GOOGLE_GENAI_USE_VERTEXAI=false`).

## Project structure

```
app/
  config.py      server-side context (demo user Arne, BE, as_of_date) and settings
  loader.py      normalizes documents, chats and emails into one Source shape
  retrieve.py    keyword-overlap retrieval (swappable; embeddings slot in at scale)
  rules.py       trust rules, source verdicts, confidence, expert selection
  llm.py         Gemini call returning structured JSON (swappable model)
  main.py        FastAPI app: POST /api/ask, GET /api/context, static frontend
static/          index.html, app.js, style.css, sample_response.json (mock mode)
data/            synthetic demo dataset (see data/DATASET.md)
docs/BUILD_PLAN.md   frozen contracts, rules, acceptance tests, timeline
```

Pipeline for `POST /api/ask {"question": "..."}`:
retrieve → rules per source → out-of-country sources moved to "excluded" (shown, not hidden) → LLM → validation (unknown source IDs dropped) → confidence + expert (code) → response.

## Data

All data in `data/` is **synthetic and fictional**, created for this hackathon. It contains 12 policy/procedure/client documents, a Teams channel export, 3 emails and an expert directory, with deliberately planted trust problems: an outdated duplicate with a wrong value, an owner who left, a chat that contradicts an official procedure, a client exception that exists only in an email, a knowledge holder about to leave, a mislabelled Germany-only file, and a document with no owner.

## Security

- No secrets in the repo: keys only in `.env` (git-ignored); `.env.example` has placeholders.
- User context (user, country, date) is fixed server-side. The API accepts **only** a `question` (max 500 chars, unknown fields rejected), so there is no user, country or document ID to tamper with (no IDOR by design).
- Frontend renders all dynamic text with `textContent`, never `innerHTML` (LLM output and documents are untrusted).
- Strict Content-Security-Policy, `X-Frame-Options: DENY`, `nosniff`, `no-referrer`.
- CORS limited to localhost. API docs disabled unless `APP_DEBUG=true`.
- Generic error messages to the client; details only in the server log.
- LLM output is validated; hallucinated source IDs are dropped.
- Pinned dependency versions.

## Unfinished / known limitations

- `rules.py`: only `country_match`, `superseded` and `authority` are implemented so far; freshness, status, owner and handover-risk rules and the full confidence logic are in progress.
- `llm.py`: Gemini call in progress; until then the API returns "Answer unavailable" and shows the trust signals only.
- Single fixed demo user (Arne, Belgium). No login.
- Keyword retrieval only, sized for the demo dataset.
- Runs locally; not deployed.
