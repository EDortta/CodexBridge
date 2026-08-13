# Self-hosted git remote (bare repo)

A versioned backup for projects that must not go to a third-party host — using a
server you already own.

## The problem

A project with no remote (`git remote -v` empty) exists only on one disk. If the
backup is Syncthing replicating the `.git/` folder along with everything else,
that is **not a versioned backup**:

- corrupt the repo and the corruption replicates;
- a wrong `git reset --hard` propagates to every replica;
- there is no second history to compare against — replication is not history.

GitHub, even private, is not the obvious answer for every project. A repo
carrying financial data or personal-system documentation is a genuine risk
decision — and it is the kind of decision an operator defers. Deferred, the
project ends up with **no remote at all**, which is worse than either option.

## What a bare repo is

A repository with **no working tree** — just `objects/`, `refs/` and `HEAD`. It
is what GitHub hosts underneath. Because it has no checked-out branch, it can
receive a push to any branch.

That last point is the reason bare matters, and it is worth stating plainly:
**you cannot push to the branch that a non-bare repo currently has checked out.**
Git refuses, because the push would make the working tree disagree with HEAD
without touching the files on disk. So a "remote" that is a normal clone works
until the day you push the branch it happens to be sitting on, then fails
confusingly. Bare has no checked-out branch, so the problem cannot arise.

## When this is the right choice

Use a self-hosted bare repo when:

- the data is sensitive (financial, personal, client) and a third-party host is a
  decision you would rather not make;
- the project is personal — one operator, no review flow;
- you already run a server with SSH key access (VPS, homelab, the box the app
  runs on) — so this costs three commands and no new account.

Do **not** use it when you need:

- collaboration (several people pushing, needing access control);
- CI/CD;
- pull requests and code review.

Those are the things you are paying GitHub/GitLab for; a bare repo has none of
them. A bare repo is a **backup with history**, not a forge.

## Usage

```bash
# once, install the helper on your PATH
./scripts/git-bare-remote.sh install     # → ~/.local/bin/gbr

# in any project
gbr status                               # do I have a remote? am I in sync?
gbr scan                                 # run the secret gate alone, push nothing
gbr init <user@host> /srv/git/<projeto>.git
```

`gbr init` is **idempotent**: run it twice and nothing breaks (it reuses an
existing bare repo and an already-correct remote). It refuses, rather than
guesses, when:

- the remote path exists and is **not** a bare repo (exit 5);
- the remote name already exists pointing somewhere **else** (exit 5) — silently
  repointing it would redirect your pushes;
- the path is relative, contains `..`, or carries shell metacharacters (exit 6).

Under the hood the core is small:

```bash
# on the server, once
git init --bare /srv/git/<projeto>.git

# on the operator's machine
git remote add origin <user>@<host>:/srv/git/<projeto>.git
git push -u origin main
```

The value is not those three lines. It is everything around them.

## The safety gate (why this is a kit facility)

**A remote is irreversible in practice: once the history leaves the machine, it
has left.** So `gbr init` checks three things before the first push, and each one
requires the operator to type `yes`:

1. **Secrets in the history — not in the working tree.** `.gitignore` protects
   nothing that was already committed yesterday, and *deleting the file in a new
   commit does not help*: the old blob is still in the history you are about to
   push. The scan therefore runs over every commit (`git log --all`, `git
   rev-list --all`), looking for secret-shaped **filenames** (`.env`,
   `*.credentials*`, private keys, keystores, `.netrc`, `.pgpass`, service
   accounts) and secret-shaped **content** (PEM private keys, AWS/GitHub/Slack/
   OpenAI/Google token formats). A finding does not block — it makes you look and
   confirm. The right fix is `git filter-repo`/BFG **and rotating the secret**,
   because a secret that reached a disk you do not control is burned.

2. **Permissions of the remote directory.** The bare repo is created `700`. If it
   already exists and is group/other-readable, you are told and must confirm — on
   a shared server, "backup" and "readable by every user on the box" are
   different things.

3. **Is the host really yours?** The one question a script cannot answer. Asked
   explicitly, because a typo'd hostname is an exfiltration.

The gate is deliberately narrow. A gate that cries wolf gets waved through, and a
gate that is waved through is worse than no gate at all.

## Autonomy rule (restated, not just in AGENTS.md)

`gbr init` touches a **remote server**. That falls under the kit's standing
prohibition on autonomous action against a remote environment.

- An agent **may** prepare the command, explain it, and run `gbr status` / `gbr
  scan` (both are local and read-only).
- An agent **may not** run `gbr init`. The operator runs it.

The script enforces this itself rather than trusting the rule: `confirm()`
refuses when stdin is not a terminal, so a pipeline or an agent-driven shell
cannot answer the prompts. **There is no `--yes` flag, by design** — such a flag
would be precisely the hole the rule exists to close. (This is the same failure
this kit already recorded once: a `deploy.sh --yes` run automatically after a
commit, pushing to production unauthorized.)

## Out of scope

- **`post-receive` hooks for deploy-on-push.** Deploy is a human-gated step;
  wiring it to a push invites exactly the accident the deploy rule exists to
  prevent.
- **Mirroring to GitHub.** A companion idea, if it ever makes sense.
- **SSH key and server provisioning.** This assumes you already log into the box
  with a key.
