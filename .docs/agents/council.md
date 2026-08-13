# Council: Adversarial Review of Approved Work

How to run a council of agents against work that has **already been approved**,
and what its output is allowed to be.
Global/common rules remain canonical in `/AGENTS.md`.

`./reviewer.md` covers *review of a diff* — it runs before approval and returns
BLOCKER / NEEDS IMPROVEMENT / APPROVED.
`./governance-precedence.md` covers *roles that disagree* — it resolves a
conflict into one direction.
This file covers *the thing nobody disagreed about*, which is a different failure
mode and needs a different instrument.

If this file conflicts with `/AGENTS.md`, follow `/AGENTS.md`.

---

## 0. What this file is actually for (read this first)

A reviewer asks "is this change correct?". Everyone answers yes. The change ships
and is wrong anyway.

That is not a review failure. It is the **consensus failure**, and it has a shape:

> The reviewer and the programmer share the same mental model of the change.
> A mistake *inside* that model is invisible to both — not because either was
> careless, but because they are looking through the same lens.

A council is not a second reviewer. A second reviewer with the same lens finds
what the first found. **The council's only value is that its members are looking
for something the reviewer was not looking for**, and each member is told what
that something is.

Three consequences run through every rule below:

1. **The council produces findings, never decisions.** The moment it decides, it
   is doing `./governance-precedence.md`'s job, badly and without the human.
2. **A finding is evidence, not agreement.** Counting how many members flagged
   something is a proxy for evidence. This file uses evidence.
3. **It runs on approved work, or it is just review again.**

---

## 1. The boundary with `./governance-precedence.md`

These two files look adjacent and are not. Read the table before assuming which
one you are in:

|  | `./governance-precedence.md` | this file |
|---|---|---|
| **input** | two recommendations that **conflict** | an artifact that **everyone approved** |
| **problem** | the roles disagree | **nobody disagrees** — that is the problem |
| **output** | one **direction** + documented trade-off | **findings** — never a direction |
| **mechanism** | precedence (security/correctness wins) + human escalation | evidence |

- [MANDATORY] The council **produces findings, never decisions**. It has no
  precedence rule because it arbitrates nothing.
- [MANDATORY] If two members disagree **with each other**, the council does not
  resolve it. One of two things is true: either the finding does not survive §2,
  or it **has become** a role conflict — in which case it **leaves the council and
  enters `./governance-precedence.md`**. That is a one-way door, and naming it is
  the whole point of this section.
- [MANDATORY] The council **never modifies code**. It reports. The fix belongs to
  `./programmer.md`, under `./design-standards.md` §1 — which means it ships with
  a test that fails without it.
- [PROHIBITED] **Voting.** A finding that 3 of 3 members report and nobody can
  reproduce is worth zero. A finding that 1 member reports with a failing test is
  worth everything. Agreement is a proxy for evidence; this file uses evidence.
  (Same thesis as `./design-standards.md` §0.)

Precedence: for **decisions**, `./governance-precedence.md` wins. For
**findings**, this file governs. `/AGENTS.md` wins over both.

---

## 2. What counts as a surviving finding

- [MANDATORY] A finding survives **if and only if** it names all four:
  1. **a concrete trigger** — the input, state, or sequence. Not "this could be a
     problem";
  2. **the observable wrong outcome** — what the user, the operator, or the next
     reader would actually see;
  3. **where** — `file:line`, or the rule it violates (`./design-standards.md` §N,
     `./security-standards.md` §N);
  4. **one of:** a **failing test** (best), a **reproduction** (command + output),
     or an honest **`not reproduced: <what I could not run>`** — the literal
     wording of `./design-standards.md` §1.
- [MANDATORY] Without (4) it is **not a finding — it is a question.** Questions do
  not block. **But they are written down**, in the same record. A question that
  keeps coming back across rounds is how the next council gets its lens.
- [MANDATORY] Every surviving finding closes with either a test that fails without
  the fix (`./design-standards.md` §1) or a written risk acceptance
  (`../workflows/delivery-loop.md` §9). "Fixed" without one of those is a claim, and §1 forbids it.
- [PROHIBITED] Reporting a finding whose evidence is that a model found it
  convincing. The council's members are agents; **an agent's confidence is not
  evidence**, and this file is the last place that should forget it.
- [IMPROVEMENT] A finding that a member cannot state in the four parts is usually
  a smell it noticed and could not localize. Write it as a question against the
  file, not as a vague finding. The next round starts there.

---

## 3. Members and lenses

- [MANDATORY] Every member is given a **lens** — a specific thing to look for that
  `./reviewer.md` does not ask about. A member with no lens is a second reviewer
  and finds what the first found.
- [MANDATORY] Lenses must **differ from each other**. Three members with one lens
  is one member with extra cost.

Default council: **three members.** See Provenance for why that number is
precedent and not evidence.

| lens | the question it asks | anchor |
|---|---|---|
| **The sweep skeptic** | what did the mechanical pass miss? | 2026-07-01: a rename sweep by prefix missed bare directory args (`cp -r AI-Agents/docs`) and `./`-prefixed links; skeptics caught 3 stragglers |
| **The claim auditor** | which statement in the delivery has no artifact behind it? | 2026-07-16: an issue claimed "tested by unit"; the repository had no test at all |
| **The second caller** | what is the next call site / next tool / next deploy order this does not cover? | 2026-07-16: the installer has **two** copy paths; adding the new script to only one left a clean install without it |

Optional lenses, selected by the questions in §5:

- **The adversarial user** — what does a hostile input reach?
  (`./security-standards.md`)
- **The operator at 17:00** — does this close cleanly, or does it strand a dirty
  session? (`/AGENTS.md` §8c)
- **The migrator** — what happens to data/artifacts already processed under the
  old behaviour? (`./design-standards.md` §4)

---

## 4. When a council runs

**The moment is the delivery commit** — the commit that closes the work and precedes
handing it back to the operator. Not the first commit of a session, and not the push:
push may never happen, may happen weeks later, and there is no pre-push hook to hang
anything on. The delivery commit always happens, it is the agent's own act, and it
falls one step after `./reviewer.md` returned non-BLOCKER — which is the ordering the
`[PROHIBITED]` below requires.

- [MANDATORY] **Two rounds, then the operator.** Round 1 reports; `./programmer.md`
  closes each surviving finding under §2. Round 2 checks the fixes. If a finding is
  still open after round 2, **stop** — take it to the operator with the findings
  written out. Do not run a third round. Same escalation shape as
  `./governance-precedence.md`, which reaches for a human on round 2 rather than
  orbiting.
- [MANDATORY] **A finding that contradicts an established project rule leaves the
  council.** The agent does not weigh the two and pick. That is the one-way door in
  §1: it becomes a role conflict, goes to `./governance-precedence.md`, and the
  operator decides.

**These triggers are provisional.** They are hypotheses derived from one round —
see Provenance. The registration rule below is what will eventually correct them.

- [MANDATORY] After a **mechanical sweep** (rename/move/codemod across many
  files). This is the exact shape of the precedent.
- [MANDATORY] After a change to a **kit-owned or shared contract** that propagates
  to other repositories — blast radius greater than one repo.
- [MANDATORY] When the delivery **adds** a `not validated:` claim — in its
  `Tests` section, or anywhere in the entry when it has no such section. Scope
  matters twice here, and getting it wrong cost this gate three
  false positives: "adds" means the staged diff's own lines, because `handoff.md`
  is append-only and reading it whole makes every past entry part of today's
  delivery; and the section keeps prose that *mentions* the marker from being
  read as a claim, which quoting cannot do — a genuine claim is often written
  `not validated:` in backticks too. The earlier wording said "on a runtime
  path"; no gate ever implemented that, and a trigger cannot judge what a claim
  is *about*. The words are gone rather than left promising a distinction the
  tool does not make.
- [MANDATORY] Before a release/tag that **changes a gate**.
- [DEFAULT] Whenever the operator asks.
- [PROHIBITED] Running a council **instead of** `./reviewer.md`. The council runs
  **after** review returns non-BLOCKER, against the **approved** artifact. That
  ordering is the only thing that makes it adversarial rather than a second
  review.
- [MANDATORY] **Every round is recorded** — in `docs/napkin-lessons.md` and the
  active `RESUME.md`: how many findings were raised, how many survived §2, how
  many became tests, and how many questions were left open. Without the record,
  the triggers and the member count in this file never get to be anything but
  guesses.
- [MANDATORY] The same round is recorded **machine-readably** for the gate:
  `governancekit --root <project> council --record <round.json>`. The record is
  bound to a digest of the staged diff, so a round from yesterday cannot clear
  today's commit and an amendment invalidates the round that approved the previous
  content. `--waive "<reason>"` exists for the legitimate exception and **requires
  a reason**: an escape with no reason is a silent escape.

---

## 5. The questions that select the council

The council is shaped by what the project **is**. That is not a new questionnaire:
`docs/software-overview.md` already ends in a **Target Project Checklist** of six
lines. Read each line adversarially and it becomes the question.

| line of the checklist | the question | what it selects |
|---|---|---|
| product purpose and users | who is hurt first when this is wrong — user, operator, or a downstream system? | whether **the adversarial user** is mandatory |
| technology stack and major modules | how many stack/module boundaries does a change here cross? | council size — one lens per boundary crossed, with a ceiling |
| runtime/deployment model | may client and server ship in any order? is there a step a human runs? | **the migrator**; `./design-standards.md` §4 |
| important business rules | which rule, broken silently, would take longest to notice? | what **the second caller** aims at |
| external services and data stores | what leaves the process, and what arrives untrusted? | **the adversarial user** |
| known risky areas or non-obvious behavior | where has this project **already regressed once**? | the skeptics' seed — read `docs/napkin-lessons.md` |

- [MANDATORY] If `docs/software-overview.md` is not ready
  (`project_context_ready: yes`), **the council cannot be selected** — every
  question above reads from it. Say so and stop; do not guess the answers.
  (`/AGENTS.md` §1b.)

This file owns the *what and why* of these questions. The executable collection —
asking them and rendering the answers into a project's council — is the companion
runtime work in **AI-GovernanceKit** (the "how").

---

## Council checklist

- [ ] The artifact was already approved by `./reviewer.md` — this is not the review
- [ ] Each member has a lens, and no two lenses are the same
- [ ] Every lens asks something `./reviewer.md` does not ask
- [ ] Every surviving finding names trigger, wrong outcome, location, and evidence
- [ ] Findings with no evidence were written as questions, not dropped
- [ ] No finding survived on agreement alone; nothing was voted on
- [ ] Disagreement between members was routed to `./governance-precedence.md`, not settled here
- [ ] Every surviving finding closed with a failing test or a written risk acceptance
- [ ] The round is recorded: findings raised / survived / became tests / questions left

---

## Provenance

This file has **one** precedent, and it is important to be exact about how thin
that is.

On 2026-07-01, during `WK-20260701-dotdocs-kit-layout`, three adversarial skeptics
were run against work that was already implemented and self-verified. They
returned **6 findings, all fixed and retested** (`handoff.md`,
`docs/issues/002-dotdocs-kit-layout-[finished]/RESUME.md`). The round was never
documented: no workflow, no contract, no spec. It was mentioned afterwards only as
evidence that the work was sound. This file exists because that instrument worked
and then vanished.

**Three is the only number that has ever run here.** It is precedent, not evidence
that three is right (n=1). Member count, the three default lenses, and every
trigger in §4 are **hypotheses**. That is why recording each round is `[MANDATORY]`
in §4 — the record is the only thing that can ever replace the guess.

The lenses are not invented. Each one is a regression this ecosystem actually had:

- **the sweep skeptic** — `[2026-07-01]` a path sweep by prefix missed bare
  directory args in shell examples and `./`-prefixed links that a
  negative-lookbehind guard skipped; the skeptics caught 3 stragglers in
  tutorials. The napkin lesson from that day already says *"verify with an
  independent reviewer"* — this file is that sentence, made into a contract.
- **the claim auditor** — `[2026-07-16]` an issue claimed its logic was "tested by
  unit (start/end/underflow/guard)" and the repository contained no test at all.
  The false claim had retired the risk in every subsequent reader's mind.
- **the second caller** — `[2026-07-16]` the kit's installer has **two** copy paths
  (upgrade and fresh install); adding a new script to only the first left a clean
  install without it. The install test caught it. Same shape as
  `./design-standards.md` §3: the protection did not cover what it claimed to
  cover.

The rule that *the council never decides* (§1) is not from a council incident. It
comes from `./governance-precedence.md` already existing: an instrument that
produces directions is already in this kit, it escalates to a human on round 2,
and a second one that quietly arbitrates by majority would route around that
escalation. The prohibition on voting is `./design-standards.md` §0 applied to
this file: agreement is a level-3 comfort with no level-1 rule behind it.

**Enforcement status:** gated at the delivery commit, since `[2026-08-06]`.

The previous cut of this section said the honest thing and was right about itself:

> By this kit's own §0 — *a rule with nothing executable behind it is decoration* —
> **a council that nothing convenes is decoration.** Nothing in this file convenes
> it. […] Giving this file teeth […] is a future decision, and it should be made
> from those records, not from this paragraph.

It deferred the gate until the records existed. That was a closed loop: the records
only exist if councils run, and nothing ran one. **Five weeks, zero rounds.** The
loop was broken from outside — the operator asked for the gate at the commit, not at
the push — and the deferral was retired rather than satisfied.

What convenes it now:

- `../workflows/git-delivery.md` §7 names this file at the delivery commit. It **names**, and does not
  restate, so it cannot fall out of date when the rules here change.
- `governancekit doctor` carries a **non-advisory** `council gate` check, and the
  `pre-commit` hook the kit installs already refuses on exactly that. The check is
  silent whenever nothing is staged: a gate that fired outside a commit would be
  noise in every other flow.
- The record is bound to a digest of the staged diff, so it clears one commit and
  not the next.

Still honest about what it does **not** reach: the triggers remain provisional; the
release/tag trigger is out of a pre-commit hook's reach and is printed as such rather
than dropped; and *mechanical sweep* is detected by a file-count threshold, which is a
guess the tool labels as a heuristic every time it reports it.

`not validated:` whether these five triggers are the right five. That is what the
records are for, and now they will exist.
