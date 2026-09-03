# Glossary — operator-facing vocabulary

Issue #81. One canonical vocabulary for anything a human operator reads:
control-plane screens (`gateway/app/api/routes/control_ui.py`), MCP tool
names/descriptions (`gateway/app/mcp/tools.py`), approval/decision prompts,
and prose documentation. **Internal implementation names — class, function,
column, enum member, DB table — are not renamed by this document** and may
stay more technical; where an internal name and the canonical term differ,
this glossary says so explicitly instead of pretending they match.

This file was built by reading actual usage (`grep` across `docs/`,
`gateway/`, `agent/`, `shared/`, `tests/`), not by copying issue #81's
proposal unreviewed. Two divergences from that proposal are recorded at the
end, both resolved in favor of what the shipped code and `docs/control-plane.md`
already enforce.

## The vocabulary

### CodexBridge
The product/ecosystem as a whole, when no specific component is meant.

### CodexBridge Gateway (or "the gateway")
The always-reachable central service: FastAPI app, MCP server, persistence,
dispatch to Bridge Nodes. `gateway/app/main.py` is its entry point.

### CodexBridge Control (or "Control")
The server-rendered web control plane (`gateway/app/api/routes/control_ui.py`):
fleet view, per-node detail, discovered-candidate adoption, authorization
grants. Served by the gateway process itself — not a second deployable.

### CodexBridge Mobile
The mobile operator client (separate repository, `CodexBridgeMobile`). Consumes
`docs/api/**`, the same contract Control's write actions call. See "Cross-repository
note" below — this document cannot inspect that repository from this checkout.

### Bridge Node (or "Node")
One registered CodexBridge installation — a machine (e.g. `devel3`, `T610`) plus
its reported capabilities. Backed by the `nodes` table.

**A Node is NOT an Executor.** `docs/control-plane.md`'s own table: *"`nodes` |
uma instalação CodexBridge (máquina + capacidades) | não é a conexão; não é o
executor."* Example: `devel3` is a Node; the live WebSocket session it currently
holds with the gateway is the Executor row for that Node.

### Executor
The authenticated connection/process that carries authorized work to a Bridge
Node and performs machine-local execution there — `codex-bridge-agent`,
running as the `agent/codex_bridge_agent/` package, connected over `wss
.../agent/ws`. Backed by the `executors` table.

`docs/control-plane.md`: *"`executors` | a conexão autenticada que leva
trabalho a um nó | não é a máquina."* `nodes` and `executors` are 1:1 today
(`0009_control_plane.sql` seeds one node per existing executor) but the schema
does not require that to stay true — see "Divergences" below for why this
matters more than it looks.

Prefer `executor service` or `executor on <node>` in operator wording whenever
`executor` alone could be misread as the AI/development agent.

### Engine
The development engine selected to do coding/reasoning work inside a task:
`codex`, `claude`, `cursor-agent`, `gemini`, `opencode`, `aider` (the enum
values `submit_codex_task`/`start_development_task` accept). Reported per Node
in Control's "Capabilities & engines" table (`implemented`/`available`/
`version`/`detail` — three genuinely different facts, see
`docs/control-plane.md` "Três fatos diferentes sob a palavra 'engine'").

An Engine is not a Node and not an Executor: the Executor is the process that
starts and supervises an Engine run; the Engine is what actually reasons about
and edits code.

### Runner
**Internal only — not operator-facing.** `agent/codex_bridge_agent/runners/`
is the code-level abstraction (`Runner` protocol, `RunnerPool`) that drives one
Engine. Already correctly kept out of Control and the MCP surface; this
glossary confirms that separation rather than changing it.

### Agent
Reserved for an AI/development agent (an Engine instance actually reasoning
over code) or an explicitly named software agent. Do not use "agent" as a
casual synonym for Node, Executor or Engine — see "Divergences" below for
where the codebase itself currently does this, and the one fix this PR made.

When ambiguity is possible: say "development agent," or name it (`Codex`,
`Claude Code`).

### Project
The logical CodexBridge project — independent of any one machine or any SCM
provider. Backed by the `projects` table. `docs/control-plane.md`: *"o projeto
lógico | não é um diretório, não é um repositório."*

### Workspace / Workspace Binding
A **Workspace** is a local checkout of a Project on one specific Node. A
**Workspace Binding** is the explicit, recorded association between a Project
and one Workspace on one Node (`workspace_bindings` table, holding
`local_path` — a sensitive field, see "Fields that must never ship" in
`docs/api/README.md`). A Project can have more than one Workspace Binding
(same project, different Nodes, different local paths) — that plurality is
the entire reason `docs/control-plane.md` keeps this its own table instead of
a column on `projects`.

### SCM Association
The recorded link between a Project and one remote repository
(`scm_associations` table; today, GitHub only). `confidence` starts
`declared` (an operator named the repository) and only becomes `confirmed` by
explicit operator action — never automatically, and never by the executor's
own live check succeeding once (`docs/architecture.md`, "Binding de forge").
This is a different fact from a Workspace Binding: a Project can be bound to a
Node's disk without being associated to any remote, and vice versa.

### Discovery
Observation that a Node can see a candidate resource inside its own configured
discovery roots (`discovered_resources` table, state `discovered`/`stale`).
**Discovery grants no operational permission.** `docs/control-plane.md`:
*"a node cannot grant itself project authorization merely by reporting a
discovery."*

### Adoption
The operator/Control action (`POST /api/v1/discovered-resources/{id}/adopt`)
that accepts a discovered candidate into the known Project/Workspace-Binding
model. **Adoption is not authorization by itself** — it can carry an
auto-authorize grant (capped to `read`/`test`) alongside it, but an adoption
with no capabilities granted leaves the Node able to see the Project and
nothing else.

### Authorization / Permission / Capability
What operations a Node may perform against a Project it is bound to
(`project_authorizations` table, `Capability` enum: `read`, `test`, `modify`,
`deliver`). Prefer naming the capability (`read`, `modify`, `deliver`) over
saying "access."

### Mission / Task / Session / Decision — four vocabularies, one entity
This is the pair the issue asks about ("Mission / Task / Run / Execution") and
the audit found something more precise than either side of that pair
proposed: **there is no separate Mission entity, no separate Session entity,
and no separate Decision entity.** All three are the same `TaskModel` row,
exposed under three different names for three different audiences
(`docs/api/README.md`, sections "Sessions," "Decisions," "Missions";
`gateway/app/api/routes/conversations.py`: *"session" and "decision" and
"mission" are the same TaskModel"*):

| Surface | Audience | What it emphasizes |
|---|---|---|
| **Session** (`/api/v1/sessions`) | mobile client, general use | one `codex exec` run: logs, pause/resume/restart |
| **Decision** (`/api/v1/decisions`) | approval flow | the same run, at the moment `awaiting_approval` — request, risk, approve/reject |
| **Mission** (`/api/v1/missions`) | mission-control view | the same run, reframed with `objective`, `stage`, `blocked`/`blockedReason` |
| **Task** (`TaskModel`, MCP tools `submit_codex_task`/`get_task_status`/…) | internal identifier and the original MCP vocabulary | the row itself |

Operator-facing prose should say **Mission** or **Session** depending on which
surface is being described, and should not silently mix them for the same
concrete thing in one paragraph. **Task** remains correct when talking about
the MCP tool surface (`submit_codex_task`) or the internal model — that
vocabulary predates missions/sessions and is not being retired by this issue
(a rename would be a protocol/contract change, explicitly out of scope; see
`docs/api/README.md`'s own "internal one differs on purpose" reasoning for
Session vs Task).

### SCM provider / repository host
GitHub, GitLab, and future source-control hosting integrations, as a category.
**When the provider is known and is currently GitHub, say "GitHub."** This
codebase supports GitHub only today (`ForgeOperationKind`'s four members are
all GitHub issue operations); do not write "SCM operation" where "GitHub
operation" is accurate and clearer.

### External operation
An authorized action that leaves the coding agent's sandbox to affect an
external service — e.g. opening/commenting on/closing a GitHub issue. See
"The coding agent vs. the Executor" below for why this boundary exists and is
security-relevant, not stylistic.

### Forge
**Avoid in operator-facing text.** `forge` survives as an internal
vocabulary — `ForgeOperationModel`, `forge_operations` table,
`ForgeOperationKind`, `gateway/app/services/forge_routing.py`,
`agent/codex_bridge_agent/forge/` — and this document does not rename any of
it (protocol/contract surface, e.g. `decisionType: "forge_operation"` in
`docs/api/README.md`, is a deliberate, versioned exception under classification
2 below, not an oversight).

In operator-facing text, say what actually happens: "GitHub operation,"
"open/comment/close an issue on GitHub," or name the concrete action. Example,
matching the issue's own worked case:

> Bad: "Egress #80 — Forge operation from executor?"
> Better: "GitHub write operations — who is allowed to perform them?"

`gateway/app/api/routes/decisions.py::_forge_decision_request_summary` already
does this correctly and predates this issue — it renders `"Open an issue on
acme/widgets: <title>"`, never the word "forge," for the one surface that
actually shows a human a pending GitHub write. This PR's fix to
`gateway/app/mcp/tools.py` brings the MCP tool descriptions (`create_project_issue`,
`list_project_issues`, `comment_project_issue`, `close_project_issue`,
`bind_project_forge`, `create_epic`) up to that same standard — they
previously said "operação de forge" / "ligado ao forge" without ever defining
"forge," which is exactly acceptance criterion 2 ("Forge is no longer
presented unexplained in active operator-facing material").

## The coding agent vs. the Executor (security-relevant, not stylistic)

This is the ambiguity the issue calls out as capable of causing an incorrect
authorization decision, and it is already correctly implemented — this
section documents the existing design so operator-facing text keeps stating
it correctly.

- The **coding agent** (an Engine instance — Codex, Claude Code — running
  inside a `Runner`) processes instructions and repository content that may be
  untrusted (e.g. the text of a public GitHub issue). Its sandbox
  (`workspace-write`) has **no network access**, verified empirically
  (`tests/integration/test_codex_sandbox_has_no_network.py`,
  `docs/architecture.md` "Por que a operação de forge não é uma extensão do
  runner").
- The **Executor** — the `codex-bridge-agent` process itself, outside any
  coding-agent sandbox — is what performs an approved GitHub operation, as a
  bounded subprocess call (`agent/codex_bridge_agent/forge/gh_tool.py`)
  carrying a credential (`GH_TOKEN`) the coding agent's sandbox never sees.
- Two alternative designs were rejected specifically to preserve this
  boundary (`docs/security.md`, "Caminhos rejeitados para uma operação de
  forge alcançar a rede"): opening network for the whole sandbox, and a
  per-invocation network flag. Both would have made "which text can reach the
  network" a decision instruction text could influence in effect.

Canonical operator-facing phrasing for this distinction, adapted from the
issue's own example:

> The coding agent can modify the local workspace but has no network access.
> When it needs to open, comment on, or close a GitHub issue, it asks the
> CodexBridge Executor, which performs only that specific, approved GitHub
> operation.

## Operator-language rule

Any approval/decision prompt shown to a human must be understandable without
reading source code:

1. Name the concrete actor and action first (who does what, to what).
2. Only then, if needed, name the technical/security concept behind it.
3. Never present an internal codename (`forge`, `TaskMode`, `PolicyLevel`)
   without either translating it or defining it inline the first time it
   appears in that surface.

`gateway/app/api/routes/decisions.py`'s human-readable request summaries and
`docs/control-plane.md`'s "Operator-language rule" precedent (the #73 Control
work) already follow this; this issue extends the same rule to
`gateway/app/mcp/tools.py`'s tool descriptions.

## Required repository review — classification

Per issue #81, every occurrence was classified before any wording changed:

1. **Internal technical identifier** — left as-is (e.g. `ForgeOperationKind`,
   `Runner`, `agent_version` DB column, `executor_id` parameter name).
2. **Protocol/API contract** — left as-is; a rename here is a deliberate,
   versioned compatibility change and out of this issue's scope (e.g.
   `decisionType: "forge_operation"`, `agentVersion` in `NodeAnnouncement`).
3. **Operator-facing vocabulary** — converged where genuinely ambiguous:
   `gateway/app/mcp/tools.py` description strings (Forge wording), one
   `gateway/app/api/routes/control_ui.py` table header ("Agent version" →
   "Executor version"), one `docs/software-overview.md` bullet (see
   Divergences).
4. **Historical record** — left intact; not copied forward as a model for new
   text (e.g. `T610` as a legacy example value, discussed but not renamed in
   `docs/architecture.md`/`docs/software-overview.md`).

## Divergences between issue #81's proposal and what the code actually means

Recorded per the issue's own instruction: *"Where the issue's proposal
collides with what the code actually means, say so and pick the accurate
one."* Both resolved in favor of the shipped, tested behavior over the
proposal text — these are the operator's decision if a different resolution
is wanted.

### 1. "Executor" — proposal said "process/service," the code's own schema says "connection"

Issue #81 proposed: *"Executor: The CodexBridge process/service on a Node that
receives authorized work..."* `docs/control-plane.md` (issue #73, shipped
schema and tests) instead defines it as *"a conexão autenticada que leva
trabalho a um nó ... não é a máquina"* — the authenticated **connection**, not
the machine, and implicitly not simply "the process" either, since the schema
deliberately allows `nodes`/`executors` to stop being 1:1 in the future (a
second connection to the same machine would still be one Node, two Executor
rows).

This glossary keeps `docs/control-plane.md`'s definition as authoritative
because it is backed by a real, tested schema
(`tests/unit/test_discovery_store.py`, `tests/unit/test_effective_task_modes.py`)
and a real distinction (`workspace_bindings`/`project_authorizations` keyed by
`(node_id, project_id)`, not `(executor_id, project_id)`) that the process/
service framing does not capture. Operator-facing text can still say
"executor service" or "the executor on `<node>`" for readability — the
glossary entry above does — without asserting that Executor and Node are the
same identity, which the proposal's wording risks if read literally.

### 2. "Agent" meaning the executor software, inside this codebase's own names

Issue #81 proposed reserving "Agent" strictly for an AI/development agent.
The codebase does not fully honor that split today, and this issue does not
fix the parts that would be a rename: the executor package is
`agent/codex_bridge_agent/`, deployed as the `codex-bridge-agent` service, and
`docs/software-overview.md`'s own module table already calls it *"Executor
reverso"* in the same breath as naming the directory `agent/`. The `hello`
protocol field is `agent_version` (`NodeAnnouncement.agent_version`,
`shared/protocol.py`), read into `NodeModel.agent_version`, and rendered
verbatim in Control before this PR.

Found and fixed in this PR: `docs/software-overview.md`'s "Usuários" section
listed **"Executor" as the machine itself** (*"Executor (`devel3`): máquina
que tem os repositórios locais..."*), directly contradicting both this
glossary and the same document's own "Módulos" table three sections down.
That bullet now reads "Bridge Node" and names the executor as the process the
Node runs, resolving the in-document contradiction.

**Not fixed, and out of this issue's scope:** the package name
`agent/codex_bridge_agent/`, the `codex-bridge-agent` systemd unit name, and
the `agent_version` protocol field. Renaming any of these is a
contract/deployment change (systemd unit names in `deploy/`, an
`AgentEnvelope`/`NodeAnnouncement` field, `.env.example` variable names) —
squarely "Protocol/API contract... change only deliberately/versioned" from
this document's own classification 2, and a decision for the operator, not
this documentation pass.

## Cross-repository note

`docs/control-plane.md` is this repository's own authority for Node/Executor/
Project/Workspace/Discovery/Adoption/Authorization; `docs/api/README.md`
documents the Session/Decision/Mission split those same rows are exposed
through. **CodexBridgeMobile is a separate repository, unreachable from this
checkout** (`docs/limits.md`, "Fronteira de repositório") — this glossary is
the CodexBridge-side half of alignment issue #81 asks for; reconciling it
against Mobile's own terminology is Mobile's own PR to make, reading this file
as the source of truth for the shared vocabulary.
