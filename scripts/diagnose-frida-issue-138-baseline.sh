#!/usr/bin/env bash
# Read-only identification of frida's OAuth source files against local Git history.
# Does not access private configuration, databases, tokens or process environments.
set -Eeuo pipefail
cd "$(dirname "$0")/.."
HOST="${FRIDA_HOST:-esteban@frida.inovacaosistemas.com.br}"
PORT="${FRIDA_PORT:-2200}"
[[ "$PORT" =~ ^[0-9]+$ ]] || { echo "Invalid port" >&2; exit 2; }
FILES=(
  gateway/app/main.py
  gateway/app/api/routes/auth.py
  gateway/app/core/config.py
  gateway/app/core/oauth.py
)
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
ssh -o BatchMode=yes -o ConnectTimeout=8 -p "$PORT" "$HOST" \
  'set -eu; cd /opt/codex-bridge; for p in gateway/app/main.py gateway/app/api/routes/auth.py gateway/app/core/config.py gateway/app/core/oauth.py; do if test -f "$p" && test ! -L "$p"; then sha256sum "$p"; else printf "MISSING  %s\\n" "$p"; fi; done' > "$TMP"
printf 'REMOTE_BASELINE_DIAGNOSTIC=read_only\n'
printf 'CURRENT_HEAD=%s\n' "$(git rev-parse --short=12 HEAD)"
printf 'DEVELOPMENT_HEAD=%s\n' "$(git rev-parse --short=12 origin/development)"
for file in "${FILES[@]}"; do
  remote_sha="$(awk -v f="$file" '$2 == f { print $1 }' "$TMP")"
  base_sha="$(git show "origin/development:$file" | sha256sum | cut -d' ' -f1)"
  candidate_sha="$(git show "HEAD:$file" | sha256sum | cut -d' ' -f1)"
  printf '\nFILE=%s\n' "$file"
  printf 'REMOTE_SHA256=%s\nDEVELOPMENT_SHA256=%s\nPATCH_SHA256=%s\n' \
    "$remote_sha" "$base_sha" "$candidate_sha"
  if [[ "$remote_sha" == "$base_sha" ]]; then
    printf 'STATUS=matches_development\n'
    continue
  fi
  if [[ "$remote_sha" == "$candidate_sha" ]]; then
    printf 'STATUS=already_matches_patch\n'
    continue
  fi
  matched=""
  # Find a byte-identical version in the local history. Using Git objects
  # avoids downloading files from the server or printing any file contents.
  while IFS= read -r commit; do
    sha="$(git show "$commit:$file" 2>/dev/null | sha256sum | cut -d' ' -f1)"
    if [[ "$sha" == "$remote_sha" ]]; then
      matched="$commit"
      break
    fi
  done < <(git log --all --format=%H -- "$file" | head -n 150)
  if [[ -n "$matched" ]]; then
    printf 'STATUS=historical_git_version\nMATCHED_COMMIT=%s\n' "$matched"
  else
    printf 'STATUS=unknown_version_or_not_in_recent_local_history\n'
  fi
done
printf '\nLIVE_FILES_UNCHANGED=1\n'
