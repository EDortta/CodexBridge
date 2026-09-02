## Objective

Let a new CodexBridge installation join the fleet, and leave it, without editing
a file on the gateway host and without restarting anything — and give the
credential that admits it a real lifecycle: issued, rotated, revoked, audited.

Today the fleet has one node. The operator's stated direction is many, on
different machines, holding different or complementary projects. The cost of the
second, third and tenth machine is what this epic removes.

## What is broken today, precisely

Verified in the code, not assumed:

- `store.upsert_registry` has **exactly one caller**: the gateway's startup event
  (`gateway/app/main.py`). `/etc/codex-bridge/registry.json` is therefore read
  **once, at boot**.
- The `/agent/ws` handshake requires the executor row to exist already; a node
  that is not in that file is closed with `4404` before anything else happens.
- So admitting a machine means: edit JSON on `frida`, invent a machine token by
  hand, **restart the gateway**. Admitting a *project* on top of that costs five
  edits across two hosts and a restart of both (`docs/project-onboarding.md`).
- The machine token is a static string living in cleartext in that file. There is
  no rotation path. "Revoking" a node means deleting its line and restarting —
  and an already-open websocket is not affected by editing a file.

`docs/project-onboarding.md` already names the consequence: the desynchronisation
between the two hosts' allowlists is *"a falha operacional mais provável do
sistema"*. Every machine added by hand is another chance to hit it.

## Explicitly NOT in this epic

This epic is deliberately narrow, because the neighbouring ground already has an
owner and a second north star would compete with it:

| Concern | Owner |
|---|---|
| Project discovery within configured roots | #73 Stage 3 |
| Project adoption, workspace bindings | #73 Stage 3 |
| Capability authorization of a node over a project | #73 Stage 4 |
| Fleet visibility, node health, engines | #73 Stage 2 (PR #75) |
| How the token travels on the handshake | #15 — done |
| Secret broker so a node never sees raw project secrets | #55 — names the need, specifies no mechanism |

The boundary is a sentence: **#73 decides what an admitted node may do; this epic
decides whether it is admitted at all.**

## Product model

A node has an admission state, separate from its health (#73 Stage 2 derives
health at read time; this is persisted policy):

- `invited` — the operator issued an invite; no node has used it yet.
- `enrolled` — a node presented a valid invite and holds a machine credential.
- `suspended` — credential still exists, connections refused; reversible.
- `revoked` — credential destroyed; terminal.

**The invite and the machine token are different credentials.** The invite is
single-use, short-lived, and carried out of band to the new machine once. The
machine token is long-lived, issued by the gateway at successful enrollment, and
never travels again. Reusing one secret for both would mean the thing typed into
a terminal (and pasted into a chat, and left in shell history) is also the thing
that authenticates every subsequent connection.

## Security invariants

- **A node with no valid invite creates nothing.** Not even a `pending` row. A
  pending-on-first-contact design hands an unauthenticated caller a write
  primitive and a way to enumerate; the operator's decision must precede
  contact, not follow it.
- **A valid invite auto-enrolls.** The approval already happened when the invite
  was issued; asking for a second confirmation adds a step without adding a
  decision.
- **Enrollment grants nothing.** An enrolled node may connect and be seen. What
  it may *do* to any project is still empty until #73 Stage 4 grants it — the
  same rule `0009_control_plane.sql` already follows by being born empty.
- **Credentials are stored hashed and compared with `secure_compare`**, never
  logged in any branch (the standing rule from #15).
- **Revocation must close live connections**, not merely refuse future ones.
  Revocation that leaves the socket open is theatre.
- Every transition — invite issued, invite used, token rotated, node suspended,
  revoked — is an audit row naming the human.

## The hard constraint, named up front

`registry.json` is authoritative today and is re-applied over the database at
**every boot**. The moment enrollment writes to the database, that re-apply
becomes a resurrection risk: a node revoked at runtime comes back at the next
restart because the file still lists it.

So this epic cannot add enrollment without first settling what the file *is*.
The intended answer is that the file becomes a **seed** for an empty database,
not a continuously-authoritative source — with reconciliation rules that can
never re-create a revoked node. This is the same shape as the `projects.path`
decision recorded in `0009_control_plane.sql`: the old representation stays
until the new one is proven, and the switch is deliberate rather than silent.

## Suggested delivery stages

### Stage 1 — Credential lifecycle
Machine tokens move to hashed storage with issuance, rotation and revocation, and
revocation drops any live socket for that node. No new admission path yet; the
file still admits. Nothing observable changes for a running fleet.

### Stage 2 — The file becomes a seed
Reconciliation rules on boot: the file may create what is absent, may never
resurrect what was revoked, and may never overwrite a credential issued at
runtime. After this stage a restart is safe with runtime-managed nodes present.

### Stage 3 — Enrollment
Invite issuance (API, plus a thin CLI over it), the node's first contact carrying
an invite, auto-enrollment, and the machine's local credential store. A new
machine joins with one invite from the operator and one command on the machine.

### Stage 4 — Deprovisioning and the operator surface
Suspend, revoke, rotate and list, over the same API the eventual Control panel
will render. The CLI stays a client of it, never a second writer.

## Definition of Done

- A second development machine joins the fleet with no file edited on `frida` and
  no restart of anything.
- Its credential can be rotated and revoked from the API, and revocation is
  visible on the wire immediately.
- A gateway restart with runtime-enrolled nodes present changes nothing.
- Every admission transition appears in the audit log with the human who caused it.
- An enrolled node still cannot touch a single project until #73 Stage 4 says so.

## Open questions for the operator

1. **Is the invite bearer-only, or bound to a machine identity?** Bearer is
   simpler and matches how the operator will actually move it (copy, paste, once).
   Binding it to a declared hostname or public key resists interception but adds a
   step on a machine that has nothing yet.
2. **Offline behaviour.** If the gateway is unreachable, does an already-enrolled
   node keep working on already-dispatched work, and for how long? This is
   liveness policy, and it interacts with #73 Stage 2's health derivation.
3. **Where does the invite travel?** Out of band, by definition — but naming the
   channel decides whether short expiry is comfortable or annoying.
4. **Does deprovisioning imply anything about the node's local checkouts?** This
   epic assumes not: revoking access is not deleting work.
