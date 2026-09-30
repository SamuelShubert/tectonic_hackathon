# TrustLens

**An explainable confidence model for organisational knowledge.** Built for the SD Worx challenge at the Tectonic Hackathon (30 September 2026).

A payroll consultant asks a question. TrustLens answers it and shows a **trust receipt**: which sources are current, official and for the right country and client, where they conflict, who to ask, and a **High / Medium / Low** confidence with reasons and a next action.

> All data is **synthetic and fictional**. Not legal or payroll advice.

## How it works: the LLM extracts, the code decides

- **Rules** (`engine/rules.py`) check each source's metadata: country, supersession, freshness, status, owner, handover risk, authority.
- **The LLM** (`engine/llm.py`) reads the content and returns the answer, conflicts and exceptions as validated JSON.
- **Confidence** (`engine/confidence.py`) is computed by code, never by the LLM, and so is the expert to ask.

Model-agnostic: Gemini (API key or Vertex AI) or any OpenAI-compatible provider. The demo runs on `openai/gpt-oss-120b` via Groq.

## Run it

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-server-header
```

Open http://127.0.0.1:8000, or http://127.0.0.1:8000/?mock=1 for a sample answer without an LLM. Run the tests with `python -m pytest -q` (42 pass).

In `.env`, set **one** of: `LLM_API_KEY` (Groq/OpenRouter), `GEMINI_API_KEY`, or `GOOGLE_CLOUD_PROJECT` (Vertex). With none set, the app runs offline: trust signals only, no written answer.

## Demo: three fictional clients

Pick a client with the switcher (searchable). TrustLens then uses the general sources plus **only that client's** documents. Every document opens as a PDF.

| Client | Question | Result |
|---|---|---|
| Brouwerij Van de Leie NV (brewery, PC 118) | When do I pay double holiday pay? | April, found only in an email and a draft note; the owner leaves on 15 Oct. **Medium** |
| Vandaele Logistics NV (transport, PC 140.03) | What is the meal voucher value per working day? | EUR 8.00; the old EUR 7.00 file is superseded. **High** |
| Nordlicht Software BV (software, PC 200) | What home-working allowance is paid per month? | The file says EUR 150, a newer chat says EUR 175. **Low** |

Wait about 15 seconds between questions (free-tier rate limit).

## Security

- The API accepts only a question and a company. User, country and date are server-side.
- The company is checked against the user's portfolio (same 403 for unknown and forbidden). Other clients' sources never reach the LLM or the screen.
- PDFs are served by ID only (`DOC-nnn`), never by path, with country and client checks (same 404 for every refusal).
- Prompt-injection guards, validated LLM output, strict CSP, rate limit, body size limit, generic errors, `textContent` only in the UI.
- Keys only in `.env` (git-ignored). Dependencies pinned, with no known vulnerabilities (`pip-audit`).

## Unfinished

- Keyword retrieval instead of embeddings or enterprise search.
- One fixed demo user with a static portfolio; production needs SSO.
- Emails and chats are simulated JSON; production would use Microsoft 365 (Graph API).
- PDFs are generated from Markdown (`python scripts/build_pdfs.py`), not linked to SharePoint originals.
- The in-memory rate limiter doesn't scale beyond one process.
- The hackathon GCP project blocks all Vertex AI models, so the Vertex path is untested.

## Credits

Engine and tests initially written by Agnius Liobikas. Frontend, integration, LLM adapters, clients and PDFs by Samuel Shubert.
