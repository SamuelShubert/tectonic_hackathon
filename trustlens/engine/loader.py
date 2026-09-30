"""Load the knowledge base from disk into immutable, validated objects.

Everything is loaded ONCE at startup from a fixed server-side directory.
Requests never supply documents, paths or metadata. That single decision
removes a whole class of business-logic attacks: a client cannot upload a
fake "signed official policy" and have it trusted.

Security notes:
- Path containment: every file is resolved and must stay inside data_dir.
  Symlinks are skipped (a symlink could point to /etc/passwd or to .env).
- Size limits: oversized files are skipped, so one huge file cannot exhaust
  memory.
- YAML front matter is parsed with yaml.safe_load only.
- Every record is validated by a Pydantic model. An invalid record is
  skipped and logged, it never reaches the rules half-parsed.
- Duplicate IDs abort loading: two sources with the same ID would make
  every trust decision about that ID ambiguous.

ADAPTER NOTE (for the team): the field names read from the raw files are
concentrated in the _raw_* functions below. If the real dataset uses
different keys, change them there and nowhere else.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterator, Mapping

import yaml
from pydantic import ValidationError

from .config import RulesConfig
from .models import Expert, Source, SourceStatus, SourceType

log = logging.getLogger(__name__)

MAX_FILE_BYTES = 512 * 1024
MAX_SOURCES = 5_000
_EMPTY_OWNER_VALUES = {"", "none", "null", "n/a", "-", "unknown"}


class DataError(RuntimeError):
    """The knowledge base is inconsistent. The app must not start."""


@dataclass(frozen=True)
class KnowledgeBase:
    sources: Mapping[str, Source]
    experts: Mapping[str, Expert]


# --------------------------------------------------------------------------
# Safe file access
# --------------------------------------------------------------------------


def _safe_files(base: Path, pattern: str) -> Iterator[Path]:
    """Yield regular files matching pattern that are provably inside base."""
    base = base.resolve()
    if not base.is_dir():
        return
    for path in sorted(base.glob(pattern)):
        if path.is_symlink() or not path.is_file():
            log.warning("Skipping non-regular file or symlink: %s", path.name)
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(base):
            log.warning("Skipping file outside data directory: %s", path.name)
            continue
        if resolved.stat().st_size > MAX_FILE_BYTES:
            log.warning("Skipping oversized file: %s", path.name)
            continue
        yield resolved


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """Split '---\\n<yaml>\\n---\\n<body>' into (metadata, body)."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("\n---", 1)
    if len(parts) != 2:
        return {}, text
    meta = yaml.safe_load(parts[0].lstrip("-").strip()) or {}
    if not isinstance(meta, dict):
        raise ValueError("front matter is not a mapping")
    body = parts[1].lstrip("-").lstrip("\n")
    return meta, body


# --------------------------------------------------------------------------
# Normalization helpers
# --------------------------------------------------------------------------


def _owner(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return None if text.lower() in _EMPTY_OWNER_VALUES else text


def _status(value: Any) -> SourceStatus:
    text = str(value or "").strip().lower()
    try:
        return SourceStatus(text)
    except ValueError:
        return SourceStatus.UNKNOWN  # never guess a status


def _as_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip()[:10])


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit]


# --------------------------------------------------------------------------
# Raw record adapters (the only place that knows the raw file formats)
# --------------------------------------------------------------------------


def _raw_documents(data_dir: Path, rules: RulesConfig) -> Iterator[dict[str, Any]]:
    for path in _safe_files(data_dir / "documents", "*.md"):
        try:
            meta, body = _split_front_matter(path.read_text(encoding="utf-8"))
            doc_id = str(meta.get("id", "")).strip()
            yield {
                "id": doc_id,
                "title": str(meta.get("title") or path.stem)[:200],
                "source_type": rules.doc_type_by_id.get(doc_id, SourceType.UNKNOWN),
                "country": str(meta.get("country", "")).strip().upper(),
                "owner": _owner(meta.get("owner")),
                "last_updated": _as_date(meta.get("last_updated")),
                "status": _status(meta.get("status")),
                "supersedes": (str(meta["supersedes"]).strip() if meta.get("supersedes") else None),
                "content": _truncate(body.strip(), 20_000),
            }
        except (ValueError, TypeError, yaml.YAMLError) as exc:
            log.warning("Skipping unreadable document %s: %s", path.name, exc)


def _raw_chats(data_dir: Path) -> Iterator[dict[str, Any]]:
    for path in _safe_files(data_dir / "chats", "*.json"):
        try:
            raw = _read_json(path)
            channel = str(raw.get("channel", path.stem))[:80]
            country = str(raw.get("country", "BE")).upper()
            for msg in raw.get("messages", []):
                yield {
                    "id": str(msg["id"]),
                    "title": f"Teams #{channel} message by {msg.get('author', 'unknown')}"[:200],
                    "source_type": SourceType.CHAT,
                    "country": country,
                    "owner": _owner(msg.get("author")),
                    "last_updated": _as_date(msg["date"]),
                    "status": SourceStatus.INFORMAL,
                    "supersedes": None,
                    "content": _truncate(str(msg.get("text", "")), 20_000),
                }
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            log.warning("Skipping unreadable chat file %s: %s", path.name, exc)


def _raw_emails(data_dir: Path) -> Iterator[dict[str, Any]]:
    for path in _safe_files(data_dir / "emails", "*.json"):
        try:
            for mail in _read_json(path):
                yield {
                    "id": str(mail["id"]),
                    "title": f"Email: {mail.get('subject', '(no subject)')}"[:200],
                    "source_type": SourceType.EMAIL,
                    "country": str(mail.get("country", "BE")).upper(),
                    "owner": _owner(mail.get("from")),
                    "last_updated": _as_date(mail["date"]),
                    "status": SourceStatus.INFORMAL,
                    "supersedes": None,
                    "content": _truncate(str(mail.get("body", "")), 20_000),
                }
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            log.warning("Skipping unreadable email file %s: %s", path.name, exc)


def _raw_experts(data_dir: Path) -> Iterator[dict[str, Any]]:
    for path in _safe_files(data_dir, "experts.json"):
        for raw in _read_json(path):
            yield {
                "id": raw["id"],
                "name": raw.get("name", raw["id"]),
                "role": raw.get("role", ""),
                "countries": tuple(str(c).upper() for c in raw.get("countries", [])),
                "status": raw.get("status", "active"),
                "leaving_date": raw.get("leaving_date"),
                "left_date": raw.get("left_date"),
            }


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------


def load_knowledge_base(data_dir: Path, rules: RulesConfig) -> KnowledgeBase:
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        raise DataError(f"Data directory not found: {data_dir}")

    records: list[dict[str, Any]] = [
        *_raw_documents(data_dir, rules),
        *_raw_chats(data_dir),
        *_raw_emails(data_dir),
    ]
    if len(records) > MAX_SOURCES:
        raise DataError("Too many sources")

    # Derive the reverse supersession link: DOC-001 supersedes DOC-002
    # means DOC-002 is superseded_by DOC-001.
    superseded_by: dict[str, str] = {}
    for rec in records:
        if rec.get("supersedes"):
            superseded_by[rec["supersedes"]] = rec["id"]

    sources: dict[str, Source] = {}
    for rec in records:
        rec["superseded_by"] = superseded_by.get(rec["id"])
        try:
            source = Source.model_validate(rec)
        except ValidationError as exc:
            log.warning("Skipping invalid source %r: %s", rec.get("id"), exc.error_count())
            continue
        if source.id in sources:
            raise DataError(f"Duplicate source id: {source.id}")
        sources[source.id] = source

    experts: dict[str, Expert] = {}
    try:
        for raw in _raw_experts(data_dir):
            expert = Expert.model_validate(raw)
            if expert.id in experts:
                raise DataError(f"Duplicate expert id: {expert.id}")
            experts[expert.id] = expert
    except (ValidationError, KeyError, TypeError, ValueError) as exc:
        raise DataError(f"Invalid experts.json: {exc}") from exc

    if not sources:
        raise DataError("No valid sources loaded")

    log.info("Loaded %d sources and %d experts", len(sources), len(experts))
    # MappingProxyType: read-only views, so nothing can mutate the KB later.
    return KnowledgeBase(sources=MappingProxyType(sources), experts=MappingProxyType(experts))
