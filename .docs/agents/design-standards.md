# Design Standards

Concrete, verifiable design rules for any code created or changed in a project
that uses this kit — agents and humans alike. This is the **minimum** bar.

`./programmer.md` covers *how to work an issue* (phases, gates, output).
`./security-standards.md` covers *what must be true* about safety.
This file covers *what must be true about the shape of the code*, so that the
next change does not break the last one.

If this file conflicts with `/AGENTS.md`, follow `/AGENTS.md`.

---

## 0. What this file is actually for (read this first)

The goal is **not** to be SOLID. The goal is that a product built with this kit
does not regress. SOLID is a means; and on its own it is not enough.

The chain is short and worth stating plainly:

> A regression is **behaviour that changed without anyone noticing**.
> Only two things notice: a **test** or a **checked contract**.
> Everything else — every principle in this file — earns its place by making
> those two cheap enough to actually exist.

So the order of leverage is:

1. **A test that pins the behaviour.** Nothing substitutes for it.
2. **A contract that fails loudly when broken** (types, schema, migration).
3. **Design that makes 1 and 2 cheap** — this is where SOLID lives.
4. **Design that makes a mistake impossible** — better than catching it.

A rule from level 3 with no level-1 rule behind it is decoration. That is why
every section below ends in something executable, not in an adjective.

**The failure mode this file exists to stop** is not ugly code. It is this:

- code that *cannot* be tested, so it is not tested, so it regresses silently;
- a safety check placed at one caller, so the next caller silently lacks it;
- a claim of test coverage that no test file backs.

All three are recorded in Provenance. All three happened in this kit's own
ecosystem, with clean-looking code.

---

## 1. Tests pin behaviour, or the behaviour is not delivered

- [MANDATORY] **Never claim a test that does not exist.** Before writing "tested
  by unit tests" in an issue, commit, or handoff, name the file and show the
  run. A false coverage claim is worse than no coverage: it retires the risk in
  the reader's mind while leaving it in the code.
- [MANDATORY] **A bug fix ships with a test that fails without the fix.** If the
  test passes on the unfixed code, it is not testing the fix. Write it, watch it
  fail, then fix.
- [MANDATORY] **The test names the failure, not the function.**
  `test_managed_chrome_children_are_spared` beats `test_kill_stale_chrome_2`. Six
  months later the name is the only thing that explains why the test may not be
  deleted.
- [MANDATORY] **Before refactoring untested code, pin it first** (characterization
  test): write tests that describe what it does *today* — bugs included — then
  refactor. Without them a "safe refactor" is a rewrite with extra steps.
- [MANDATORY] When a test is impossible without a browser/network/real host, say
  so **explicitly** and name what was and was not validated. "Compiles" is not
  validation. An honest `not validated: X` is worth more than a passing test that
  proves the mock matches the mock.
- [IMPROVEMENT] Test the **decision**, not the plumbing. Extract the judgement
  into a pure function and test that; leave the untestable I/O thin enough to
  read.

## 2. Seams — the real reason Dependency Inversion is in this file

Dependency Inversion is not here for purity. It is here because **without a seam
you cannot write the test**, and without the test you get a regression. That is
the whole argument.

Interface Segregation lives here for the same reason, one step further in: **an
interface that is too wide only sends its bill to the test.** You find out how
wide it is when you write the fake.

- [MANDATORY] A class that owns a policy must not also hard-code **where the data
  lives**. Storage, clock, network and randomness arrive through a parameter (an
  interface, a callable, a default argument), not through an import buried in a
  method.
- [MANDATORY] The default must be **explicit**, not absent: `Registry(store=None)`
  → `NullStore()`, named, so "persists nothing" is a decision on the page and not
  an accident.
- [MANDATORY] External systems get an interface **owned by your side**, not their
  client library's shape. When the vendor changes, one adapter changes.
- [PROHIBITED] `datetime.now()` / `random()` / `os.getenv()` called deep inside
  business logic. They make the behaviour untestable and time-dependent; pass
  them in.
- [IMPROVEMENT] The interface a consumer depends on is the one the consumer uses.
  **Measure it in the test:** if the fake must implement methods the code under
  test never calls, the interface is wider than the need — split it
  (`Reader`/`Writer`) or narrow the parameter to a callable. Count the stubs that
  are never called; if the number is not zero, write down why.
- [IMPROVEMENT] If a test needs more than ~3 mocks to run, that is the design
  talking, not the test. Collapse the collaborators before adding the third mock.

## 3. Put the invariant where it cannot be forgotten

This is the rule with the worst regression history and the least textbook
coverage. It generalizes to: **a safety check belongs next to the dangerous
action, not next to the caller that happens to know about it today.**

- [MANDATORY] A guard that protects a dangerous operation lives **inside** that
  operation. If four call sites must remember to check `in_flight` before
  killing a process, the fifth one will not, and it will be the one in
  production.
- [MANDATORY] A cross-cutting promise ("the cache never breaks the request",
  "this never raises") is applied at **every** entry point of the module, not the
  one that happened to be reviewed. Asymmetric robustness — a safe writer next to
  an unsafe reader — reads as safe and is not.
- [MANDATORY] When a rule names its scope (an issue that says "guard
  `/image/generate` **or** `/conversations/*/send`"), implement the **whole**
  scope or write down which part you skipped and why. Half a guard is a guard
  with an exception nobody documented.
- [IMPROVEMENT] Prefer making the invalid state unrepresentable over checking for
  it: a constructor that refuses bad input beats a validator someone must call.

## 4. Contracts change additively, or they change loudly

- [MANDATORY] A new request field is **optional with a default** that reproduces
  the old behaviour. A new response field is **additive**. An old client that
  never heard of the field keeps working, in any deploy order.
- [MANDATORY] Removing or renaming a field, changing a status code, or narrowing
  an accepted value is a **contract change**: declare it (`backward compatible:
  no`) and name the downstream consumers, by name.
- [MANDATORY] **Deploy order is a design constraint, not an ops detail.** State
  which of client/server may ship first. "Safe in any order" is a claim to be
  earned (a new field ignored by the old side), not assumed.
- [MANDATORY] **Identity comes from the authenticated caller, never from the
  request body.** A `project_path` the client sends is a suggestion; a
  `project.id` the API key resolved to is a fact. Any endpoint scoping by a
  client-supplied identifier is a privilege escalation with extra steps.
- [IMPROVEMENT] Version the *behaviour*, not just the schema. When a pipeline's
  output can change (a new OCR, a new prompt), carry an explicit
  `PIPELINE_VERSION` in the cache key / stored artifact. Without it, improving
  the pipeline stays invisible for everything already processed — a silent
  failure, the worst kind.

## 5. One reason to change (SRP, stated so it can be checked)

"Does one thing" is unfalsifiable. Use the testable form:

- [MANDATORY] A module has **one reason to change**. If converting a document and
  remembering the conversion live in one file, a cache-policy change and an OCR
  change both edit it, and each risks the other. Split them.
- [MANDATORY] A route/controller does not know the transport of its dependencies.
  If the HTTP handler imports `httpx`, the boundary leaked: the driver owns the
  call, the route owns identity and error translation.
- [IMPROVEMENT] Name the reason out loud in the module docstring ("this converts;
  the neighbour remembers"). If you cannot write that sentence, the split is
  wrong.

## 6. Fail-safe, and know which way "safe" points

Liskov lives here, because the shape it takes in the real world is not the
textbook's. It is not a subclass overriding a method. It is **a value that passes
as the type without honouring the type's promise** — and the incident is already
in this section.

- [MANDATORY] Decide the direction **explicitly** and write it down:
  - **auth, secrets, exposure → fail-closed.** No token, no service.
  - **caches, telemetry, optimizations → fail-open.** A broken cache degrades to
    a miss; it never fails the request it exists to speed up.
  Getting this backwards is a real outage in either direction.
- [MANDATORY] Persisted state is written **atomically** (temp + rename). A crash
  mid-write must leave the previous good file, never a truncated one that reads
  as "empty" on the next boot and quietly discards everything.
- [MANDATORY] A corrupt state file **logs and starts empty**; it never crashes the
  boot. An empty registry is recoverable; a crash loop is not.
- [MANDATORY] Deserialization **validates required fields**. Beware defaults: a
  dataclass whose every field has one will happily turn `{"nonsense": true}` into
  a valid-looking object with a fresh random id — a ghost that never resolves for
  whoever holds the real id.
- [MANDATORY] An implementation must not weaken what callers of the base rely on:
  it does not accept input the base rejects, does not return `None` where the base
  promises a value, does not raise a type the base's callers do not catch. If it
  must, **it is not that type** — give it another name.
  The executable form: **the interface's own suite runs green against every
  implementation, unchanged** (`pytest.fixture(params=[...])`,
  `describe.each([...])`). Adding an implementation without registering it in the
  fixture **breaks the test** — that is the point.
- [PROHIBITED] An override that turns a documented failure into a silent success,
  or the reverse. If `save()` raises on a full disk in the base and the in-memory
  subtype never raises, every test written against the subtype proves nothing
  about the base's error path — that is §1, the mock proving the mock matches the
  mock.
- [IMPROVEMENT] Counters that gate safety never go negative (an underflow reads as
  "off" forever after), and are cleared in `finally` so a failed operation does
  not pin them on.

## 7. Delete the code you replaced

This is Open/Closed seen from the side that hurts. The extension point existed —
`chrome_op_guard()` — and four endpoints hand-rolled `try/finally` anyway. The
symptom you can actually record is not "closed for extension". It is **an
extension point with no adopters**.

- [MANDATORY] When you add the general mechanism, **convert the call sites** —
  and delete the old one. A context manager that exists while four endpoints
  hand-roll `try/finally` is not an abstraction; it is a fifth thing to keep in
  sync, and it is dead code that reads as live.
- [MANDATORY] **The proof that a general mechanism is general is the second call
  site converted**, not the mechanism's own unit test. An extension point with
  **zero** adopters is dead code that reads as live; with **one**, it is not an
  abstraction yet — it is a function.
- [MANDATORY] **Adding the N+1 case must not require editing the N that exist.**
  If a new endpoint/provider/format forces you to touch all the previous ones, the
  variation sits in the wrong place: put it behind the seam (§2) and **register**
  the new case. The executable form: the diff that adds case N+1 touches (a new
  file + one registration line + its test). If it touches the others, write down
  why.
- [MANDATORY] Supporting refactor is declared, not smuggled: name it in the
  output, keep it in the same commit as the reason for it.
- [PROHIBITED] Adding a parameter or flag to an existing function to serve a new
  caller when the callers no longer share a path. An `if mode == "x"` in the
  middle of a shared function **is** the modification that Open/Closed names.
- [PROHIBITED] Leaving both the old and the new path "just in case". Say which
  one is live.

---

## Review checklist (design)

- [ ] Every behaviour change has a test that fails without the change
- [ ] No coverage claimed that no test file backs; `not validated: X` stated honestly
- [ ] Untested code was pinned (characterization) before being refactored
- [ ] Storage/clock/network/randomness injected, not imported inside the logic
- [ ] The "does nothing" default is a named class/value, not an absence
- [ ] Guards live inside the dangerous operation, not at the caller
- [ ] A module's promise ("never raises") holds at **every** entry point
- [ ] The issue's whole named scope implemented, or the gap written down
- [ ] New fields optional/additive; deploy order stated and earned
- [ ] Scoping derived from the authenticated identity, never from the body
- [ ] Behaviour-changing pipelines carry an explicit version in their key
- [ ] Each touched module still has one reason to change
- [ ] Fail direction chosen on purpose: closed for auth, open for caches
- [ ] Persisted state written atomically; corrupt state boots empty
- [ ] Deserialization rejects entries missing required fields
- [ ] Every implementation passes the interface's own suite, unchanged
- [ ] No implementation weakens what callers of the base rely on
- [ ] Replaced code deleted, not left beside its replacement
- [ ] A new general mechanism shipped with its call sites converted — zero adopters is dead code
- [ ] Adding the N+1 case did not edit the N existing ones, or the diff says why

---

## Provenance

Distilled from real regressions in this kit's own ecosystem (AI-Gateway, AI-hub),
found and fixed on 2026-07-16 while sweeping the open issues. Every rule above
maps to something that actually broke or was about to:

- **§1** — an issue's resolution claimed "in-flight counter tested by unit
  (start/end/underflow/guard)". The repository contained **no test at all**: no
  suite, no pytest, no `tests/`. The claim had retired the risk in every
  subsequent reader's mind. Separately, the Gateway's `document_to_markdown` —
  its document→markdown entry point — had zero tests, so an internal signature
  change was unverifiable until tests were written for it.
- **§2** — `WatcherRegistry` hard-coded its storage to an in-memory dict. It was
  not that persistence was *hard*; it was that there was **no seam to test it
  through**. Introducing `WatcherStore` (+ `NullWatcherStore`,
  `JsonFileWatcherStore`) made the behaviour testable and the persistence
  arrived with it.
- **§3** — the watchdog's in-flight guard was placed at one call site, while the
  `SIGKILL` lived in `_kill_stale_chrome()`. Any other path to the reaper had no
  protection. Worse, the reaper spared only the **parent** Chrome pid — and the
  process the incident log shows being killed mid-generation
  (`pid=3568219 age=376s cpu=37.9%`) was a **renderer child**: old, hot and
  hidden, i.e. all three kill criteria. The guard hid the symptom; the root cause
  was a protection that did not cover what it claimed to protect. The same issue
  named `/conversations/*/send` in its scope; only `/image/generate` was
  implemented, and nobody wrote down that the other half was skipped.
- **§4** — the `force`/`cached` fields (Gateway issue 003) were designed additive
  precisely so no deploy order could break the consumer; and the Hub-proxy
  delete endpoint takes **no** client-supplied path, because the daemon's own
  `DELETE /conversations/by-project/{path}` would otherwise let any project
  unregister another's conversations by naming its path. `PIPELINE_VERSION` came
  from asking what happens to already-cached documents when OCR improves.
- **§6** — the markdown cache's `store()` was written fail-safe and its
  `lookup()` was not: a read error would have failed the very request the cache
  exists to accelerate. A test caught it. Also caught by test: a corrupt
  `watchers.json` entry deserialized into a *valid-looking* watcher, because
  every `ConversationWatcher` field has a default.
- **§7** — `chrome_op_guard()` existed and was dead: four endpoints hand-rolled
  `mark_start`/`try`/`finally` instead. The abstraction was written, never
  adopted, and drifted.

The three SOLID letters that were missing (O, L, I) were added on 2026-07-17 into
the sections that already anchored them, rather than as sections of their own —
Provenance is per section, and one incident cited under two numbers reads as two
incidents. What each one is actually standing on differs, and that is worth being
exact about:

- **§6 / Liskov** — the section states Liskov **in the shape the incident actually
  had**: a corrupt `watchers.json` entry deserializing into a valid-looking
  `ConversationWatcher` with a fresh id. It passed as the type and did not honour
  what callers of the type assume, which is that the id resolves. The textbook
  shape — a subclass overriding and weakening a contract — is **preventive here**:
  no incident on record. The "interface's suite against every implementation" rule
  comes from the `WatcherStore` pair in §2, where two implementations already
  coexist; it has never been run that way.
- **§7 / Open-Closed** — "the second call site is the proof" and "N+1 does not edit
  N" are two generalizations of the **same** incident: the four hand-rolled
  `try/finally` blocks were literally four copies of the variation
  `chrome_op_guard()` was supposed to absorb. The flag-parameter prohibition is
  **preventive** — no incident on record.
- **§2 / Interface Segregation** — **preventive, no incident.** The >3-mocks line
  was already in the file with no rule behind it, and the 2026-07-16 sweep traced
  no regression to an interface that was too wide. It is `[IMPROVEMENT]`, not
  `[MANDATORY]`, precisely because §0 applies to this file too: a level-3 rule with
  no level-1 rule behind it is decoration. If it never catches anything, it is a
  candidate for removal.

Older, from the same kit's history: an unauthorized autonomous `deploy.sh --yes`
after a commit (→ the commit-only rule), and a branch named with quotes in the
ref that corrupted tooling (→ the ASCII branch guard). Both are the same shape as
§3: the rule existed; the place that could break it did not enforce it.

**Enforcement status:** review-gated. Unlike `security-standards.md`, most of
this cannot be grepped — "one reason to change" has no regex. The two rules that
*are* mechanical are the highest-value ones and should become gates:

- **a coverage claim with no test file** (§1) — scan the diff/handoff for
  "tested"/"testado" wording against the presence of changed test files;
- **a repository with source but no test target at all** (§1) — `doctor` can
  warn.

Of the three letters added on 2026-07-17, **Liskov is the only mechanizable one
today**: "the interface's suite runs against every implementation" is a code
artifact, not an opinion. Open/Closed ("the N+1 diff touches a new file and one
registration line") is mechanizable in principle and not implemented. Interface
Segregation is review-only.

Until then, `./reviewer.md` carries them.
