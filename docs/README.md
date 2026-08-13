# Project Documentation

This folder is **yours**. The AI-Agents / GovernanceKit installer creates it once
and never touches it again — put project-specific documentation here freely and
track it in git.

Kit-managed documentation lives under `.docs/` (plus `AGENTS.md` and the per-tool
rule files) and is overwritten by `governancekit install-agents --upgrade` /
`--docs-only`. Do not edit kit-managed files by hand; record project knowledge here
instead.

List the documents an agent must read before analysing or implementing an issue in
`docs/required-reading.md`.
