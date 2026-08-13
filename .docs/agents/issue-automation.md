# Issue Automation Agent

Role-specific contract for the issue-automation agent.
Global/common rules remain canonical in `/AGENTS.md`.

Use when request is to create and link Jira + GitHub issues.

### Tooling Preference

[MANDATORY] Prefer `jkctl.py` for issue/PR workflows when it exists in the target repository.
[DEFAULT] Use direct `gh`/Jira APIs only when `jkctl.py` is unavailable or lacks the required operation.

### Deterministic Trigger

Treat as explicit automation intent:
- "create issues about ..."
- "open issues for ..."
- "create Jira/GitHub issues ..."
- "generate issues from this context ..."
- equivalent intent for one or more issues

### Target Project Confirmation (Mandatory)

[MANDATORY] Before creating any issue(s), explicitly ask whether the workflow is `undercover` or explicitly `public`.
[MANDATORY] This choice applies to the full requested issue set unless the human explicitly provides per-subset mode mapping.
[MANDATORY] In `undercover` mode, do not ask for target repository/Jira project and do not call Jira/GitHub issue APIs.
[MANDATORY] In `public` mode, follow target repository/project confirmation rules below.
[MANDATORY] Before creating any issue, explicitly ask which target project/repository must receive the issues.
[MANDATORY] Do not assume `current repository` by default for issue creation.
[MANDATORY] Accept execution only after human confirmation of target context.
[MANDATORY] If the user requests multiple issues, confirm whether all issues use the same target project or provide per-issue mapping.
[PROHIBITED] Running issue creation without explicit target project confirmation in the same conversation flow.
[PROHIBITED] Running Jira/GitHub issue creation/linking commands when workflow mode is `undercover`.

### Mandatory Execution Order

Public mode:
1. Confirm target project/repository for each issue (or shared target for all)
2. Generate local issue artifacts using epic-folder structure in `docs/issues/`
3. Resolve Jira parent if request implies container/area/initiative
4. Create Jira issue(s) with structured ADF description
5. Create GitHub issue(s) in confirmed target repository
6. Cross-link Jira and GitHub
7. Return fixed structured summary

Undercover mode:
1. Generate epic/issue document(s) under `docs/undercover-issues/<epic-folder>/` and `docs/undercover-issues/<epic-folder>/issues/` as applicable
2. Apply ordered naming and filename status contract
3. Create local epic/issue relationships in file metadata/body
4. Return fixed structured summary without Jira/GitHub links

### Issue Document Rules

Local issue structure:
- `docs/issues/NNN-<epic-slug>-[<status>]/README.md`
- `docs/issues/NNN-<epic-slug>-[<status>]/epic.md`
- `docs/issues/NNN-<epic-slug>-[<status>]/issues/NNN-<task-slug>-[<status>].md`

Each document must include:
- Title
- Objective
- Context
- In scope
- Out of scope
- ARO
- Test plan
- Security considerations
- DoD

[MANDATORY] Markdown docs are source artifacts.
[MANDATORY] Jira description must be ADF structured content (not raw markdown).
[DEFAULT] GitHub issue body may use markdown.

Undercover mode documents:
- One folder per epic in `docs/undercover-issues/`: `NNN-<epic-slug>-[<status>]`
- Epic file inside each epic folder: `epic.md`
- Issue files under each epic folder `issues/`: `NNN-<issue-slug>-[<status>].md`
- Status must use approved set: `[draft] [ready] [started] [blocked] [review] [finished] [cancelled]`
- Issue files must include local parent relation when applicable (example: `parent_epic: <NNN-or-none>`)

### Parent Resolution Rule (Jira)

When request implies parent container (e.g., "under <epic/area>"):

[MANDATORY] Parent must be set.
[DEFAULT] Prefer matching non-done Epic.
If multiple candidates, choose deterministically:
1. non-done first
2. best summary match
3. most recently created

If parent cannot be resolved, fail objectively and request only missing parent info.

### Defaults

If not provided:
- `jira_project_key`: require explicit user confirmation (no implicit default)
- `jira_issue_type`: `Task`
- `assignee`: creator user on each target platform (Jira/GitHub)
- `github_repo`: only after explicit human confirmation of target project/repo
- `labels`: deterministic by intent

### Default Labeling

[DEFAULT] Use:
- `bug` for defect correction
- `enhancement` for behavior improvement or new capability
- `chore` for maintenance-only work with no product behavior change

### Required Automation Output

Return:
- `created_docs`
- `issues_created`:
  - `title`
  - `jira_parent_key` (when applicable)
  - `jira_key`
  - `jira_url`
  - `github_issue_number`
  - `github_issue_url`
  - `branch_suggestion`
- `defaults_used`
- `failures`
