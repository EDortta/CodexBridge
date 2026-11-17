#!/usr/bin/env bash
# Issue #138 only: prepare and STAGE 4 Git-tracked files. Does not modify live code.
set -Eeuo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
HOST="${FRIDA_HOST:-esteban@frida.inovacaosistemas.com.br}"
PORT="${FRIDA_PORT:-2200}"
[[ "$PORT" =~ ^[0-9]+$ ]] || { echo "Invalid SSH port" >&2; exit 2; }
BRANCH="$(git symbolic-ref --short HEAD)"
[[ "$BRANCH" == "fix/issue-138-oauth-session-ux" ]] || {
  echo "Refusing unexpected branch: $BRANCH" >&2; exit 2;
}
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || {
  echo "Tracked worktree has uncommitted changes; stage requires a committed revision" >&2; exit 2;
}
git rev-parse --verify refs/remotes/origin/development >/dev/null
RELEASE_ID="issue138-$(date -u +%Y%m%dT%H%M%SZ)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
FILES=(
  gateway/app/main.py
  gateway/app/api/routes/auth.py
  gateway/app/core/config.py
  gateway/app/core/oauth.py
)
# Exact baseline is expected to match what frida currently runs; do not overwrite
# diverging Gateway files without explicit review.
printf 'ISSUE_138_PATCH_V1\n' > "$TMP/checksums.txt"
for file in "${FILES[@]}"; do
  git cat-file -e "origin/development:$file"
  git cat-file -e "HEAD:$file"
  # Frida is currently running this exact historical main.py blob, verified
  # by the published read-only baseline evidence (2026-11-17, run 141902).
  # Preserve fail-closed checks for every other module.
  if [[ "$file" == "gateway/app/main.py" ]]; then
    baseline="$(git show "196de250b9dc323f0cd7a1047b22aabed36ffc37:$file" | sha256sum | cut -d' ' -f1)"
    [[ "$baseline" == "9bc3f8a693c14ed77badc0d4b360b7cdd8f55ea0881657996acbe4cd52578086" ]] || {
      echo "Historical main.py baseline is not the verified remote blob" >&2
      exit 2
    }
  else
    baseline="$(git show "origin/development:$file" | sha256sum | cut -d' ' -f1)"
  fi
  candidate="$(git show "HEAD:$file" | sha256sum | cut -d' ' -f1)"
  printf '%s %s %s\n' "$file" "$baseline" "$candidate" >> "$TMP/checksums.txt"
done
git archive --format=tar --prefix=patch/ HEAD "${FILES[@]}" | gzip -n > "$TMP/patch.tar.gz"
sha256sum "$TMP/patch.tar.gz" | cut -d' ' -f1 > "$TMP/patch.sha256"
printf 'commit=%s\nbase=%s\n' "$(git rev-parse HEAD)" "$(git rev-parse origin/development)" > "$TMP/source.txt"
# Confirm target is healthy and staging exists; staging does not restart anything.
ssh -o BatchMode=yes -o ConnectTimeout=8 -p "$PORT" "$HOST" '
  set -eu
  test -d /opt/codex-bridge
  test -f /etc/codex-bridge/env
  systemctl is-active --quiet codex-bridge-gateway
  curl -fsS --max-time 5 http://127.0.0.1:18080/health >/dev/null
  umask 077
  mkdir -p "$HOME/codexbridge-staging"
'
ssh -o BatchMode=yes -p "$PORT" "$HOST" "mkdir -m 700 -p ~/codexbridge-staging/$RELEASE_ID"
for name in checksums.txt patch.tar.gz patch.sha256 source.txt; do
  scp -q -P "$PORT" "$TMP/$name" "$HOST:codexbridge-staging/$RELEASE_ID/$name"
done
# Apply script is staged, never executed by the staging command.
sha256sum scripts/apply-frida-issue-138.sh | cut -d' ' -f1 > "$TMP/apply.sha256"
scp -q -P "$PORT" scripts/apply-frida-issue-138.sh "$HOST:codexbridge-staging/$RELEASE_ID/apply-frida-issue-138.sh"
scp -q -P "$PORT" "$TMP/apply.sha256" "$HOST:codexbridge-staging/$RELEASE_ID/apply.sha256"
ssh -o BatchMode=yes -p "$PORT" "$HOST" "cd ~/codexbridge-staging/$RELEASE_ID && test \"\$(sha256sum patch.tar.gz | cut -d' ' -f1)\" = \"\$(cat patch.sha256)\" && test \"\$(sha256sum apply-frida-issue-138.sh | cut -d' ' -f1)\" = \"\$(cat apply.sha256)\""
printf 'STAGED_ONLY=%s\n' "$RELEASE_ID"
printf 'SOURCE_COMMIT=%s\n' "$(git rev-parse HEAD)"
printf 'APPLY_NOT_EXECUTED=1\n'
