# Sending Email

What an agent must establish **before** sending email, and why none of it can be
carried in from another project.

`../agents/credentials-operations.md` covers *configuring providers during project
adoption*; this file covers the one capability an agent may need mid-task.

Load this file only when a task requires sending email.
If this file conflicts with `/AGENTS.md`, follow `/AGENTS.md`.

---

## Sending Email

Email transport, sender identity and recipient lists are **project-specific**. Never
carry them over from another project, from a previous session, or from memory.

Before sending anything:

1. **Read the project's own email documentation** — named in `docs/required-reading.md`,
   including its *Fontes locais — fora do checkout* table — to find which transport it
   uses and where its recipient list lives. If the project documents none, **ask the
   operator** instead of guessing.
2. **Resolve every recipient from that list**, including recurring CC rules.
3. **Never hardcode or commit credentials.**

**The harness-provided user email is not a recipient.** It identifies the owner of the
logged-in account, which is not necessarily the operator you are talking to, and is
never a destination by default. Never resolve "send it to me" from it.

Email cannot be recalled. When the recipient is ambiguous, **ask before sending**.

---

## Checklist

- [ ] The transport came from **this** project's documentation, not from another project
      and not from memory
- [ ] Every recipient was resolved from the project's recipient list, CC rules included
- [ ] No recipient was inferred from the harness user email
- [ ] No credential was hardcoded, committed, or quoted in a log, prompt, or message
- [ ] Where the recipient was ambiguous, the operator was asked rather than guessed

---

## Provenance

Until `[2026-08-10]` this file did the opposite of what it now requires: it prescribed
**one project's mechanism** — a fixed helper and a fixed credential file under one
operator's `~/.config/email/` (`send.py`, `credentials.conf`), and a single SMTP account
slot (`SMTP_ACCOUNT`, since retired) — as though it were universal.

Two spellings here are deliberate, and both were council findings. The slot is written
without its double braces, or a legacy `identity.json` that still declares it would
substitute the operator's address into the very paragraph that forbids it. The two file
names are written **bare, under a directory path**, rather than as full `~/`-rooted
paths:
`governancekit doctor` scans contracts for cited local paths and asks the project to
index them, and it cannot tell a citation from a counter-example — so the full paths, in
a file installed everywhere, made every project in the park index another operator's
transport. That is the disease, arriving through the prescription for it.

The file is installed into every project
in the park, and projects do not share a transport: some have a local helper, others
version one inside the repository with its own credentials. A contract that names one
of them makes an agent apply project A's mechanism while working in project B.

What the section never said is the only thing an agent actually needs: **where the
project's recipient list lives**, and that *"send it to me"* does not resolve itself.

`[2026-08-07]` — in a project installed with this contract, an agent resolved "send it
to me" from the harness `userEmail` field, which reports the **logged-in account**, not
the operator. The material went to the wrong person. The correct recipient list existed,
in two places, and no required-reading document pointed at either. Email has no undo.

Two consequences shape the rules above:

- The obligations are stated **without a transport**, so the contract stays true in a
  project whose transport this kit has never seen.
- Step 1 points at the **project's own index** rather than at a path, which is what
  makes the rule survive the next project.

The transport this repository itself uses is where the rule says it should be: in
`docs/required-reading.md`, under *Fontes locais — fora do checkout*, recorded as path
and purpose and never as content.

`not validated:` whether pointing at the required-reading index is enough on a project
whose index is thin. The failure that produced this file was a *missing* pointer, not a
*followed* one, so the fix is aimed at the pointer — but nothing here proves an agent
reads the index at the moment it needs it rather than at the Start Gate. That is the
same decay `docs/issues/006-contract-vs-tool-reconciliation-[draft]/issues/B1-B3-action-gates-and-enforcement.md`
describes, and it is open there, not here.
