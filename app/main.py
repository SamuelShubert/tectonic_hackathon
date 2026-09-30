"""TrustLens API. OWNER: Samuel (P1).

POST /api/ask {"question": "..."} -> response contract 3.5
Pipeline: retrieve -> rules per source -> split included/excluded -> LLM -> validate
          -> confidence + expert (code decides, never the LLM).
"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app import config, llm, retrieve, rules
from app.loader import load_experts, load_sources

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("trustlens")

SOURCES = load_sources()
EXPERTS = load_experts()

app = FastAPI(
    title="TrustLens",
    docs_url="/docs" if config.DEBUG else None,
    redoc_url=None,
    openapi_url="/openapi.json" if config.DEBUG else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


# ---------- request model ----------

class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # no user/country/doc id accepted from the client
    question: str = Field(min_length=1, max_length=config.MAX_QUESTION_CHARS)

    @field_validator("question")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("empty question")
        return v


# ---------- errors: generic to the client, details in the server log ----------

@app.exception_handler(RequestValidationError)
async def on_validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={
        "error": f"Invalid request: send only a question of 1 to {config.MAX_QUESTION_CHARS} characters."})


@app.exception_handler(Exception)
async def on_error(request: Request, exc: Exception):
    log.exception("Unhandled error")
    return JSONResponse(status_code=500, content={"error": "Something went wrong. Please try again."})


# ---------- helpers ----------

def _validate_answer(raw, allowed_ids: set[str]) -> dict:
    """Second guard on LLM output: known fields only, drop hallucinated source IDs."""
    if not isinstance(raw, dict):
        return llm.fallback_answer()

    def ids(values):
        return [i for i in (values or []) if isinstance(i, str) and i in allowed_ids]

    status = raw.get("answer_status")
    answer = {
        "answer": str(raw.get("answer") or llm.FALLBACK_TEXT)[:1000],
        "answer_status": status if status in ("answered", "uncertain", "no_answer") else "no_answer",
        "winning_source_id": raw.get("winning_source_id") if raw.get("winning_source_id") in allowed_ids else None,
        "cited_source_ids": ids(raw.get("cited_source_ids")),
        "conflicts": [],
        "exceptions": [],
    }
    for c in raw.get("conflicts") or []:
        if isinstance(c, dict) and len(ids(c.get("source_ids"))) >= 2:
            answer["conflicts"].append({
                "source_ids": ids(c.get("source_ids")),
                "summary": str(c.get("summary") or "")[:300],
                "resolved": bool(c.get("resolved")),
                "resolution": str(c.get("resolution") or "")[:300],
            })
    for e in raw.get("exceptions") or []:
        if isinstance(e, dict) and ids(e.get("source_ids")):
            answer["exceptions"].append({
                "source_ids": ids(e.get("source_ids")),
                "summary": str(e.get("summary") or "")[:300],
            })
    return answer


def _public_expert(expert):
    if not expert:
        return None
    return {k: expert.get(k) for k in ("id", "role", "why")}


# ---------- API ----------

@app.get("/api/context")
def get_context():
    user = EXPERTS.get(config.CONTEXT["user"])
    return {**config.CONTEXT, "name": "Arne Goossens" if not user else user.get("name")}


@app.post("/api/ask")
def ask(req: AskRequest):
    context = dict(config.CONTEXT)
    retrieved = retrieve.retrieve(req.question, SOURCES, k=config.RETRIEVE_K)

    included, excluded = [], []
    for src in retrieved:
        results = rules.evaluate_source(src, context, SOURCES, EXPERTS)
        reason = rules.exclusion_reason(results)
        if reason:
            excluded.append({"id": src["id"], "title": src["title"], "reason": reason})
        else:
            included.append({**src, "verdict": rules.source_verdict(results), "rules": results})

    if included:
        try:
            raw = llm.ask_llm(req.question, included)
        except Exception:
            log.exception("LLM call failed")
            raw = llm.fallback_answer()
    else:
        raw = llm.fallback_answer()
    answer = _validate_answer(raw, {s["id"] for s in included})

    confidence = rules.compute_confidence(answer, included, context)
    expert = rules.select_expert(answer, included, context, EXPERTS, req.question)

    return {
        "question": req.question,
        "context": context,
        "answer": answer,
        "confidence": confidence,
        "ask_expert": _public_expert(expert),
        "sources": [
            {"id": s["id"], "title": s["title"], "source_type": s["source_type"],
             "owner": s["owner"], "last_updated": s["last_updated"],
             "verdict": s["verdict"], "rules": s["rules"]}
            for s in included
        ],
        "excluded_sources": excluded,
    }


# Static frontend last, so /api/* routes win.
app.mount("/", StaticFiles(directory=config.STATIC_DIR, html=True), name="static")
