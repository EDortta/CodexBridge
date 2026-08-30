Parent: #63
Related: #68 (POST /api/v1/missions)

## Objective
Expose `GET /api/v1/missions/{id}/delivery`, returning branch, head commit, changed-file list, and diff **statistics only** — never diff content. Today `_session_dto` and `_mission_dto` (`gateway/app/api/routes/sessions.py`, `gateway/app/api/routes/missions.py`) both deliberately omit the stored result blob, while `CodexBridgeMobile`'s `mission.dart` domain model already declares `tests`, `files`, and `artifacts` fields that no server has ever populated. This issue is what finally makes those fields true.

## Scope
- New route in `gateway/app/api/routes/missions.py`.
- Reads `tasks.delivery_result_json` (introduced in #66) and the existing `result_json`'s test-output fields.

## Requirements
- Returns `{branch, base_branch, head_commit, commit_subject, files_changed, insertions, deletions, changed_files: [path], pushed, delivery_outcome, tests: {...}}`.
- **Diff content is never returned** — only `--shortstat`-equivalent counters and the changed-file path list. This repository already redacts absolute paths in session logs (`redact()`); the same redaction applies here, since a resolved issue's content is untrusted text (see #65's provenance-separation requirement) and this endpoint must not become a channel for exfiltrating it.
- A mission whose delivery step never ran, or whose `delivery_result_json` is null, returns an explicit `{"available": false, "reason": "..."}` shape rather than a 404 or an empty object indistinguishable from "nothing changed."

## ARO
- **F26** (artifact transport has no owner, per the council review): this issue deliberately stays narrow — file *names* and *counts*, not file *contents* or downloadable artifacts. Anything resembling artifact download/preview is explicitly out of scope here and belongs to a future issue owned by #26's finding, not this one.
- Redaction correctness is a real risk: the same `redact()` helper used for session logs must be applied to `changed_files` paths, or an absolute filesystem path could leak the executor's directory layout to a mobile client.

## Test plan
- Extend `tests/integration/test_missions.py`: delivery evidence present after a task with `delivery_result_json` set; `available: false` shape for a task with none; changed-file paths pass through redaction; diff content is never present anywhere in the response body (assert its absence, not just its correct rendering).
- `tests/contract/test_openapi_document.py`: new path documented.

## Definition of Done
- `Mission.files` and `Mission.tests` on the Flutter client can be populated from a real server response for the first time.
- No response from this endpoint ever contains diff content or an unredacted absolute path.
