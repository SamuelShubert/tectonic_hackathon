"""FastAPI entry point. Deliberately thin: all logic lives in the engine.

Run:  uvicorn app.main:app --host 127.0.0.1 --port 8000

Security decisions:
- The API accepts ONE field: the question. User, country and date come from
  server config, so there is no ID to tamper with (no IDOR surface) and no
  way to claim another user's context.
- There is no endpoint that returns a document by ID or path.
- Validation errors and server errors return generic messages. FastAPI's
  default 422 echoes the input back; we don't.
- The question text is never logged (it may contain client personal data).
- /docs and /openapi.json are off unless ENABLE_API_DOCS=true.
- No CORS middleware: the frontend is served from the same origin, so no
  cross-origin access is needed or allowed.
- Binds to 127.0.0.1 by default (see README), not 0.0.0.0.
"""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from app.security import BodySizeLimitMiddleware, RateLimiter, SecurityHeadersMiddleware
from engine import CompanyNotAllowed, InvalidQuestion, TrustEngine, build_engine
from engine.config import Settings, load_settings
from engine.models import COMPANY_PATTERN, AskResponse

log = logging.getLogger("trustlens.api")
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
MAX_BODY_BYTES = 4 * 1024


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # any extra field (user, country...) = rejected
    question: str = Field(min_length=3, max_length=500)
    # Optional client. Validated here for shape, and by the engine against the user's portfolio.
    company: str | None = Field(default=None, pattern=COMPANY_PATTERN)


# Source IDs served as PDF: a strict shape, looked up in a server-side map, never used as a path.
PDF_ID = re.compile(r"^DOC-\d{3}$")


def _error(status: int, message: str, request_id: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": message, "request_id": request_id})


def create_app(engine: TrustEngine | None = None, settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    engine = engine or build_engine(settings)
    limiter = RateLimiter(limit=settings.rate_limit_per_minute)

    docs = settings.enable_api_docs
    app = FastAPI(
        title="TrustLens",
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=MAX_BODY_BYTES)
    app.add_middleware(SecurityHeadersMiddleware)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _error(422, "Invalid request: send {\"question\": \"...\"} (3-500 characters).",
                      uuid.uuid4().hex[:12])

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        request_id = uuid.uuid4().hex[:12]
        log.exception("Unhandled error (request_id=%s)", request_id)  # details stay server-side
        return _error(500, "Internal error", request_id)

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "llm_enabled": settings.llm_enabled}

    @app.get("/api/context")
    def context() -> dict:
        # Read-only view of the server-side demo context, for the page header.
        return {"user": settings.demo_user, "country": settings.demo_country,
                "as_of_date": settings.as_of_date.isoformat()}

    @app.get("/api/companies")
    def companies() -> dict:
        """The companies in the current user's portfolio, with their client documents and example questions."""
        kb, ctx = engine.knowledge_base, engine.context
        result = []
        for company in kb.companies_for(ctx.user):
            consultant = kb.experts.get(company.consultant)
            documents = [
                {"id": s.id, "title": s.title, "has_pdf": s.id in kb.pdf_files}
                for s in sorted(kb.sources.values(), key=lambda s: s.id)
                if s.company == company.id and s.id in kb.pdf_files
            ]
            result.append({
                **company.model_dump(exclude={"consultant"}),
                "consultant": consultant.name if consultant else company.consultant.replace(".", " ").title(),
                "documents": documents,
            })
        return {"general_questions": list(kb.general_questions), "companies": result}

    @app.get("/api/sources/{source_id}/pdf", include_in_schema=False)
    def source_pdf(source_id: str):
        """Open one document as PDF.

        Authorization is enforced here, not in the UI: the document must exist, apply to the
        user's country (or all countries), and belong to no client or to a client in the
        user's portfolio. Every refusal is the same 404, so IDs can't be probed.
        """
        kb, ctx = engine.knowledge_base, engine.context
        source = kb.sources.get(source_id) if PDF_ID.fullmatch(source_id) else None
        pdf = kb.pdf_files.get(source_id) if source else None
        allowed = (
            source is not None and pdf is not None
            and source.country in (ctx.country, "ALL")
            and kb.can_access(ctx.user, source.company)
        )
        if not allowed:
            return JSONResponse(status_code=404, content={"detail": "Document not found"})
        # Served from memory (loaded at startup): no file is opened for a request.
        return Response(content=pdf, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{source.id}.pdf"'})

    @app.post("/api/ask", response_model=AskResponse)
    def ask(body: AskRequest, request: Request):
        request_id = uuid.uuid4().hex[:12]
        client = request.client.host if request.client else "unknown"
        if not limiter.allow(client):
            return _error(429, "Too many requests, try again in a minute.", request_id)
        try:
            response = engine.ask(body.question, company=body.company)
        except InvalidQuestion as exc:
            return _error(422, str(exc), request_id)
        except CompanyNotAllowed:
            log.warning("ask request_id=%s denied: company not in portfolio", request_id)
            return _error(403, "You don't have access to that company.", request_id)
        log.info("ask request_id=%s chars=%d confidence=%s",
                 request_id, len(body.question), response.confidence.level.value)
        return response

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

        @app.get("/", include_in_schema=False)
        def index():
            index_file = STATIC_DIR / "index.html"
            if index_file.is_file():
                return FileResponse(index_file)
            return JSONResponse({"detail": "Frontend not built yet"}, status_code=404)

    return app


def _build_default_app() -> FastAPI:
    load_dotenv()  # reads .env if present; real env vars take precedence
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return create_app()


app = _build_default_app()
