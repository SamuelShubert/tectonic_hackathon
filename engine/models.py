"""Domain models for the TrustLens engine.

Security notes:
- Every model forbids unknown fields (extra="forbid") so malformed or
  malicious input is rejected instead of silently carried along.
- Knowledge-base models are frozen (immutable). They are loaded once at
  startup and no request can modify them.
- Every free-text field has a maximum length, and IDs must match a strict
  pattern. This bounds memory use and keeps IDs safe to render.
- LLM output gets its own model (LLMAnswer) with length limits, because it
  is untrusted input just like user input.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# IDs are rendered in the UI and used as dictionary keys. Restrict them to a
# safe character set so they can never carry markup or path fragments.
ID_PATTERN = r"^[A-Za-z0-9._@-]{1,80}$"
COUNTRY_PATTERN = r"^([A-Z]{2}|ALL)$"
COMPANY_PATTERN = r"^[a-z0-9][a-z0-9-]{1,60}$"

MAX_TITLE = 200
MAX_CONTENT = 20_000
MAX_LABEL = 300
MAX_ANSWER = 1_000
MAX_SUMMARY = 400


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------


class SourceType(str, Enum):
    POLICY = "policy"
    PROCEDURE = "procedure"
    CLIENT_NOTE = "client_note"
    EMAIL = "email"
    CHAT = "chat"
    UNKNOWN = "unknown"


class SourceStatus(str, Enum):
    CURRENT = "current"
    DRAFT = "draft"
    INFORMAL = "informal"  # chats and emails have no document lifecycle
    UNKNOWN = "unknown"  # status missing in the source system: never guess


class OwnerStatus(str, Enum):
    ACTIVE = "active"
    LEAVING = "leaving"
    LEFT = "left"
    EXTERNAL = "external"  # e.g. a client e-mail address
    UNLISTED = "unlisted"  # internal colleague not in the expert directory
    MISSING = "missing"  # nobody owns the source


class RuleStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    INFO = "info"


class ConfidenceLevel(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


# --------------------------------------------------------------------------
# Knowledge base (loaded once, immutable)
# --------------------------------------------------------------------------


class Expert(_Frozen):
    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(max_length=MAX_TITLE)
    role: str = Field(max_length=MAX_TITLE)
    countries: tuple[str, ...] = ()
    status: Literal["active", "leaving", "left"]
    leaving_date: date | None = None
    left_date: date | None = None


class Company(_Frozen):
    """A client company. Client-specific sources are only visible for their own company."""

    id: str = Field(pattern=COMPANY_PATTERN)
    name: str = Field(max_length=MAX_TITLE)
    city: str = Field(max_length=80)
    country: str = Field(pattern=r"^[A-Z]{2}$")
    sector: str = Field(max_length=80)
    joint_committee: str = Field(max_length=40)
    employees: int = Field(ge=0, le=1_000_000)
    consultant: str = Field(pattern=ID_PATTERN)
    questions: tuple[str, ...] = ()


class Source(_Frozen):
    id: str = Field(pattern=ID_PATTERN)
    title: str = Field(max_length=MAX_TITLE)
    source_type: SourceType
    country: str = Field(pattern=COUNTRY_PATTERN)
    company: str | None = Field(default=None, pattern=COMPANY_PATTERN)  # None = applies to every client
    owner: str | None = Field(default=None, max_length=120)
    last_updated: date
    status: SourceStatus
    supersedes: str | None = Field(default=None, pattern=ID_PATTERN)
    superseded_by: str | None = Field(default=None, pattern=ID_PATTERN)
    content: str = Field(max_length=MAX_CONTENT)


class Context(_Frozen):
    """Who is asking, for which country, and at which moment in time.

    Always built server-side from configuration, never from a request body.
    """

    user: str = Field(pattern=ID_PATTERN)
    country: str = Field(pattern=r"^[A-Z]{2}$")
    as_of_date: date
    company: str | None = Field(default=None, pattern=COMPANY_PATTERN)  # checked against the user's portfolio


# --------------------------------------------------------------------------
# Rule output
# --------------------------------------------------------------------------


class RuleResult(_Frozen):
    rule: str = Field(max_length=40)
    status: RuleStatus
    label: str = Field(max_length=MAX_LABEL)


class SourceAssessment(_Frozen):
    id: str
    title: str
    source_type: SourceType
    country: str
    company: str | None = None
    has_pdf: bool = False
    owner: str | None
    owner_status: OwnerStatus
    last_updated: date
    verdict: RuleStatus  # pass / warn / fail (never info)
    excluded: bool
    exclusion_reason: str | None = None
    rules: tuple[RuleResult, ...]

    def labels(self, *statuses: RuleStatus) -> list[str]:
        return [r.label for r in self.rules if r.status in statuses]

    def has_rule(self, rule: str, status: RuleStatus) -> bool:
        return any(r.rule == rule and r.status == status for r in self.rules)


# --------------------------------------------------------------------------
# LLM output: UNTRUSTED. Validated and truncated before use.
# --------------------------------------------------------------------------


def _truncate(value: object, limit: int) -> object:
    if isinstance(value, str) and len(value) > limit:
        return value[: limit - 1] + "…"
    return value


class LLMConflict(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source_ids: list[str] = Field(default_factory=list, max_length=10)
    summary: str = ""
    resolved: bool = False
    resolution: str = ""

    @field_validator("summary", "resolution", mode="before")
    @classmethod
    def _cap(cls, v: object) -> object:
        return _truncate(v, MAX_SUMMARY)


class LLMException(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source_ids: list[str] = Field(default_factory=list, max_length=10)
    summary: str = ""

    @field_validator("summary", mode="before")
    @classmethod
    def _cap(cls, v: object) -> object:
        return _truncate(v, MAX_SUMMARY)


class LLMAnswer(BaseModel):
    # "ignore" (not "forbid") for LLM output: an extra key from the model
    # should not throw away an otherwise valid answer. Unknown keys are dropped.
    model_config = ConfigDict(extra="ignore")

    answer: str = ""
    answer_status: Literal["answered", "uncertain", "no_answer"] = "no_answer"
    winning_source_id: str | None = None
    cited_source_ids: list[str] = Field(default_factory=list, max_length=20)
    conflicts: list[LLMConflict] = Field(default_factory=list, max_length=10)
    exceptions: list[LLMException] = Field(default_factory=list, max_length=10)

    @field_validator("answer", mode="before")
    @classmethod
    def _cap(cls, v: object) -> object:
        return _truncate(v, MAX_ANSWER)

    @classmethod
    def unavailable(cls, reason: str) -> "LLMAnswer":
        return cls(answer=reason, answer_status="no_answer")


# --------------------------------------------------------------------------
# API response
# --------------------------------------------------------------------------


class Confidence(_Frozen):
    level: ConfidenceLevel
    reasons: tuple[str, ...]
    action: str


class ExpertRef(_Frozen):
    id: str
    name: str
    role: str
    why: str


class ExcludedSource(_Frozen):
    id: str
    title: str
    reason: str


class AskResponse(_Strict):
    question: str
    context: Context
    answer: LLMAnswer
    confidence: Confidence
    ask_expert: ExpertRef | None
    sources: list[SourceAssessment]
    excluded_sources: list[ExcludedSource]
