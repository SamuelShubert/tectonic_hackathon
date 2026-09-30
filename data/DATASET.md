# SD Worx Demo Dataset (synthetic)

All content is **fictional**, made for the Tectonic Hackathon. It is safe to commit to a public repo.

## Contents
- `documents/`: 12 policy/procedure/client docs, Markdown with YAML front matter (id, country, version, status, owner, last_updated, source)
- `chats/teams_payroll_be_helpdesk.json`: Teams channel export
- `emails/emails.json`: 3 emails
- `experts.json`: expert directory (incl. someone leaving and someone who left)
- `demo_questions.json`: 6 demo questions with expected answer and planted traps

## Planted trust problems
| Problem | Where |
|---|---|
| Outdated duplicate with a wrong value (85% vs 92%) | DOC-002 vs DOC-001 |
| Owner has left the company | DOC-002 (pieter.claes) |
| Contradiction between an official doc and chat | DOC-003 vs Teams T1 |
| Client exception only in email / draft note | E2, DOC-010 |
| Knowledge holder leaving soon (handover risk) | jens.wouters, E3 |
| Misleading file name / wrong country | DOC-005 (says "general", is DE-only) |
| Stale doc with no owner | DOC-004 |
| Untracked copy with different values | DOC-008 vs DOC-007 |

## Suggested demo story (3 min)
Arne inherits Jens's portfolio (E3). He asks Q2. A plain search gives "May/June". Your tool shows the trust receipt: the default rule, the client exception from email, the fact that Jens is leaving, and a suggested action to capture the exception into the official client file.
