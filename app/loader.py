"""Loader: normalizes documents, chats and emails into one Source shape (contract 3.1).

Source = {id, title, source_type, country, owner, last_updated, status,
          supersedes, superseded_by, content}

Owner status (active / leaving / left / colleague / external / none) is NOT part of the Source
contract. Use owner_status(owner, experts) for it.
"""
import json
import re
from pathlib import Path

from app.config import DATA_DIR

SOURCE_FIELDS = (
    "id", "title", "source_type", "country", "owner", "last_updated",
    "status", "supersedes", "superseded_by", "content",
)

# Authority order, highest first (contract 3.1).
SOURCE_TYPES = ("policy", "procedure", "client_note", "email", "chat")

# Explicit mapping for the 12 demo documents.
DOC_SOURCE_TYPE = {
    "DOC-001": "policy",
    "DOC-002": "policy",
    "DOC-003": "procedure",
    "DOC-004": "policy",
    "DOC-005": "policy",
    "DOC-006": "policy",
    "DOC-007": "procedure",
    "DOC-008": "procedure",
    "DOC-009": "procedure",
    "DOC-010": "client_note",
    "DOC-011": "policy",
    "DOC-012": "policy",
}
# Fallback for any document added later, by its `domain` field.
DOMAIN_SOURCE_TYPE = {
    "payroll": "policy",
    "compliance": "policy",
    "operations": "procedure",
    "process": "procedure",
    "client": "client_note",
}

CHAT_COUNTRY = "BE"   # channel is #payroll-be-helpdesk
EMAIL_COUNTRY = "BE"


def _parse_front_matter(text: str) -> tuple[dict, str]:
    """Front matter lines are `key: <json value>` between two `---` lines."""
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not match:
        return {}, text
    meta = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        raw = raw.strip()
        try:
            meta[key.strip()] = json.loads(raw)
        except json.JSONDecodeError:
            meta[key.strip()] = raw.strip('"')
    return meta, match.group(2)


def _clean_body(body: str) -> str:
    """Drop the synthetic-data banner so it doesn't pollute retrieval."""
    lines = [ln for ln in body.splitlines() if not ln.startswith("> SYNTHETIC")]
    return "\n".join(lines).strip()


def _source(**kwargs) -> dict:
    src = {field: kwargs.get(field) for field in SOURCE_FIELDS}
    src["status"] = src["status"] or "unknown"      # never guess an empty status
    src["owner"] = src["owner"] or None              # "" -> None (no owner)
    src["supersedes"] = src["supersedes"] or None
    return src


def load_documents(data_dir: Path = DATA_DIR) -> list[dict]:
    sources = []
    for path in sorted((data_dir / "documents").glob("*.md")):
        meta, body = _parse_front_matter(path.read_text(encoding="utf-8"))
        doc_id = meta.get("id")
        if not doc_id:
            continue
        source_type = DOC_SOURCE_TYPE.get(doc_id) or DOMAIN_SOURCE_TYPE.get(meta.get("domain"), "policy")
        sources.append(_source(
            id=doc_id,
            title=meta.get("title") or path.stem,
            source_type=source_type,
            country=meta.get("country") or "ALL",
            owner=meta.get("owner"),
            last_updated=meta.get("last_updated"),
            status=meta.get("status"),
            supersedes=meta.get("supersedes"),
            content=_clean_body(body),
        ))
    return sources


def load_chats(data_dir: Path = DATA_DIR) -> list[dict]:
    sources = []
    for path in sorted((data_dir / "chats").glob("*.json")):
        export = json.loads(path.read_text(encoding="utf-8"))
        channel = export.get("channel", "Teams")
        for msg in export.get("messages", []):
            date = (msg.get("ts") or "")[:10]
            sources.append(_source(
                id=msg["id"],
                title=f"Teams {channel}: {msg['author']}, {date}",
                source_type="chat",
                country=CHAT_COUNTRY,
                owner=msg.get("author"),
                last_updated=date,
                status="informal",
                content=msg.get("text", ""),
            ))
    return sources


def load_emails(data_dir: Path = DATA_DIR) -> list[dict]:
    sources = []
    for path in sorted((data_dir / "emails").glob("*.json")):
        for mail in json.loads(path.read_text(encoding="utf-8")):
            sources.append(_source(
                id=mail["id"],
                title=f"Email: {mail.get('subject', '')}",
                source_type="email",
                country=EMAIL_COUNTRY,
                owner=mail.get("from"),
                last_updated=mail.get("date"),
                status="informal",
                content=f"From: {mail.get('from')}\nTo: {', '.join(mail.get('to', []))}\n"
                        f"Subject: {mail.get('subject', '')}\n\n{mail.get('body', '')}",
            ))
    return sources


def _derive_superseded_by(sources: list[dict]) -> None:
    by_id = {s["id"]: s for s in sources}
    for src in sources:
        target = by_id.get(src["supersedes"]) if src["supersedes"] else None
        if target:
            target["superseded_by"] = src["id"]


def load_sources(data_dir: Path = DATA_DIR) -> list[dict]:
    sources = load_documents(data_dir) + load_chats(data_dir) + load_emails(data_dir)
    ids = [s["id"] for s in sources]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"Duplicate source IDs: {sorted(duplicates)}")
    _derive_superseded_by(sources)
    return sources


def load_experts(data_dir: Path = DATA_DIR) -> dict[str, dict]:
    experts = json.loads((data_dir / "experts.json").read_text(encoding="utf-8"))
    return {e["id"]: e for e in experts}


def owner_status(owner: str | None, experts: dict[str, dict]) -> dict:
    """Returns {"state": active|leaving|left|colleague|external|none, "date": "YYYY-MM-DD"|None}."""
    if not owner:
        return {"state": "none", "date": None}
    expert = experts.get(owner)
    if not expert:
        # "first.last" = internal colleague not in the expert directory (e.g. arne.goossens).
        # An address with "@" = someone outside SD Worx (e.g. the client's HR manager).
        return {"state": "external" if "@" in owner else "colleague", "date": None}
    raw = (expert.get("status") or "").lower()
    date_match = re.search(r"\d{4}-\d{2}(-\d{2})?", raw)
    date = date_match.group(0) if date_match else None
    if raw.startswith("leaving"):
        return {"state": "leaving", "date": date}
    if raw.startswith("left"):
        return {"state": "left", "date": date}
    return {"state": "active", "date": None}


if __name__ == "__main__":
    srcs = load_sources()
    exps = load_experts()
    for s in srcs:
        o = owner_status(s["owner"], exps)
        print(f"{s['id']:8} {s['source_type']:12} {s['country']:4} {s['status']:9} "
              f"{str(s['owner']):32} {o['state']:9} sup_by={s['superseded_by']}")
    print(f"\n{len(srcs)} sources, {len(exps)} experts")
