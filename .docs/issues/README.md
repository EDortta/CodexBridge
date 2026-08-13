# Local Issues Structure

Use epic folders under `docs/issues`.

Required structure per epic:
- `NNN-<epic-slug>-[<status>]/README.md`
- `NNN-<epic-slug>-[<status>]/epic.md`
- `NNN-<epic-slug>-[<status>]/issues/NNN-<task-slug>-[<status>].md`

Required metadata in epic/task docs:
- `work_id`: `WK-YYYYMMDD-<short-slug>`
- `date`: `YYYY-MM-DD`
- `related_commit`: planned or final commit reference

Recommended templates:
- `.docs/issues/templates/README.template.md`
- `.docs/issues/templates/epic.template.md`
- `.docs/issues/templates/task.template.md`
- `.docs/issues/templates/privacy-checklist.template.md`

Session-close related files:
- `handoff.md`
- `docs/napkin-lessons.md`
- `.docs/workflows/session-close.md`

Allowed status values:
- `[draft]`
- `[ready]`
- `[started]`
- `[blocked]`
- `[review]`
- `[finished]`
- `[cancelled]`

Status changes must be performed by rename.
