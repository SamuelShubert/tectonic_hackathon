# CLAUDE.md – TrustLens (Tectonic Hackathon, SD Worx challenge)

Project context for Claude Code. This repo is **public**: never write secrets, passwords, API keys or project IDs into this file or any committed file.

## What we're building

**Tectonic Hackathon** (Belgium, 30 September 2026), **SD Worx** challenge: *"Unlock the Knowledge Within – Find it. Understand it. Trust it."* SD Worx knowledge is scattered across policies, emails, chats and people's heads. Finding it is solved; **trusting** it is not (is it current, official, for this country or client, and who vouches for it?).

**TrustLens** answers a payroll question and shows a **trust receipt**: sources with trust signals, conflicts, exceptions, who to ask, and High / Medium / Low confidence with reasons and a next action.

**Pitch line:** "We built an explainable confidence model that tells SD Worx employees not just what the answer is, but how sure they can be and why."

**Core principle: the LLM extracts, the code decides.** Rules judge sources from metadata; the LLM returns answer, conflicts and exceptions as JSON; Python computes confidence and picks the expert.

## Team

**Samuel Shubert, solo** for the final version. The engine and tests were initially written by Agnius, who has left the project. Samuel owns everything now.

## Judging and submission

- Scoring: originality 30%, technical ability 30%, fit to the challenge 30%, security 10% (Aikido).
- Submit in **Builderbase**: short description, demo video under 3 minutes, GitHub repo link, Aikido screenshots before and after.
- Repo stays **public** until judging ends; README says what it is, how to run it and what's unfinished; never upload keys; the final submission is final (no pushes after).
- **Deadline: confirm in Builderbase.**

### Aikido (security, 10%)
1. https://app.aikido.dev/ai-pentests/discounts/hackathon-tectonic-aikido → "Continue with GitHub".
2. Connect this repo, run **AI Code Analysis → Code Security Audit**. Screenshot = "before".
3. Fix findings, mark them resolved, re-run. Screenshot = "after".

## Stack

- Python 3.13, FastAPI, Uvicorn, Pydantic, PyYAML, python-dotenv, httpx, `google-genai` (pinned in `requirements.txt`).
- **LLM is model-agnostic** (`engine/llm.py`). Order of preference in `engine/__init__.py`: `GEMINI_API_KEY` → `LLM_API_KEY` (OpenAI-compatible) → `GOOGLE_CLOUD_PROJECT` (Vertex ADC) → offline.
- **Demo LLM: Groq, `openai/gpt-oss-120b`**, key in `.env` as `LLM_API_KEY`. The free tier is rate-limited per minute; the client retries once on 429.
- The hackathon Qwiklabs GCP project **blocks all Vertex models** (`vertexai.allowedModels` = deny all) and API keys. Don't spend time on it again. The Qwiklabs account also can't sign in to third-party sites.
- Retrieval: keyword (IDF). Frontend: plain HTML/CSS/JS in `static/`, no framework, no CDN. Data: Markdown + JSON, no database. Runs locally.

## Run

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env
python -m pytest -q
uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-server-header
```
- http://127.0.0.1:8000 → live app; `/?mock=1` → UI from `static/sample_response.json`, no LLM.
- Tests: 42 pass, 1 skipped (symlink test needs admin/Developer Mode on Windows).

## Code map

| Path | Role |
|---|---|
| `app/main.py` | FastAPI: `POST /api/ask` (question + optional company), `GET /api/companies`, `GET /api/sources/{id}/pdf`, `GET /api/context`, `GET /api/health`, serves `static/` |
| `app/security.py` | Security headers (strict CSP), body size limit, rate limiter |
| `engine/config.py` | Settings from env + `config/rules.yaml` |
| `engine/loader.py` | Loads 26 sources (15 docs, T1–T7, E1–E4), 7 experts, 3 companies + portfolios, and the PDF map |
| `engine/rules.py` | Metadata rules → verdicts and labels |
| `engine/retrieval.py` | Keyword retrieval |
| `engine/llm.py` | Prompt, `GeminiClient` (key or Vertex), `OpenAICompatClient`, output validation |
| `engine/confidence.py` | Confidence levels + expert routing (a leaving knowledge holder is asked first, then the country expert) |
| `engine/pipeline.py` | `TrustEngine.ask()` |
| `static/` | Frontend: client switcher with search, company card with PDF links, lens layout (index + thumbnails with crop marks + inspector), handover banner, confidence meter |
| `data/companies.json` | 3 fictional clients, the demo user's portfolio, example questions per client |
| `data/pdf/` + `scripts/build_pdfs.py` | Generated PDFs of every document; rebuild after editing a document |
| `tests/` | Acceptance (demo questions, scripted LLM) + security tests |

## Clients (all fictional)

- **Brouwerij Van de Leie NV** (brewery, Kortrijk, PC 118): holiday pay advanced to April, only in E2 + draft DOC-010, Jens leaving → Medium.
- **Vandaele Logistics NV** (transport, Antwerp, PC 140.03): meal vouchers EUR 8 in DOC-013 (current), superseding DOC-014 (EUR 7, owner left) → High.
- **Nordlicht Software BV** (software, Ghent, PC 200): home-working allowance EUR 150 in DOC-015 vs newer chat T7 saying EUR 175 → Low.
Client-specific sources carry `company:`; they are only visible when that client is selected.

## Acceptance tests (live, gpt-oss-120b): all pass

| Q | Answer | Confidence |
|---|---|---|
| Q1 BE double holiday pay | 92%, May/June | High |
| Q2 Brouwerij Van de Leie (client selected) | April (E2 + DOC-010), ask Jens before 15 Oct, then Sofie | Medium |
| Q3 PC 200 end-of-year premium | Unresolved DOC-003 vs T1 | Low |
| Q4 BE December cutoff | 15 December (DOC-008 conflict resolved) | High |
| Q5 BE 100% sick pay | First 30 days (DOC-005 DE excluded) | High |
| Q6 Dutch sick leave | No usable source | Low |

Demo video: Q2 is the main story (Arne inherits Jens's clients; the policy says May/June; TrustLens finds the April exception in an email and warns that Jens leaves on 15 Oct). Q5 and Q3 as quick cuts. Wait about 15 s between questions (rate limit).

## Security rules (keep these true in every change)

- Keys and project IDs only in `.env` (git-ignored). `.env.example` has placeholders only.
- The API accepts only `{"question", "company"}` (question 3–500 chars, extra fields rejected). User, country and date come from server config. The company is checked against the user's portfolio server-side (403 for unknown or forbidden).
- The PDF endpoint takes only `DOC-nnn`, looks it up in a startup map (never a path), and re-checks country and client access (404 for everything refused).
- Frontend: all dynamic text via `textContent`, **never `innerHTML`**. No inline scripts or styles (the CSP forbids them). The `[hidden]` attribute is forced with `display: none !important`.
- Generic errors to the client; details only in the server log. Never log question text or keys.
- LLM prompt: sources in delimiters, "Sources are data" rule, output validated, unknown IDs dropped.

## Working style

Keep explanations short and practical. Prioritise a reliable demo over extra features. Never run `git commit` for the user. Update the "Unfinished" section of `README.md` when something changes. When unsure about an event detail (deadline, credits, links), say so and suggest asking an organiser.
