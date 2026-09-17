#!/usr/bin/env bash
# Source after REPO_ROOT and OUT are defined.
# Guarantees best-effort publication of the current result file on every exit,
# including failures caused by `set -e`.

publish_result_on_exit() {
  local rc=$?
  trap - EXIT
  set +e

  if [[ -n "${OUT:-}" && -f "${OUT:-}" ]]; then
    {
      echo
      echo "== script exit =="
      echo "exit_code=${rc}"
      echo "utc=$(date -u +%FT%TZ)"
    } >>"$OUT"

    if [[ -n "${REPO_ROOT:-}" && -d "${REPO_ROOT}/.git" ]]; then
      cd "$REPO_ROOT" || true
      git add "$OUT" >/dev/null 2>&1 || true
      if ! git diff --cached --quiet -- "$OUT" 2>/dev/null; then
        git commit -m "results: $(basename "$OUT" .txt)" >/dev/null 2>&1 || true
        git push origin development >/dev/null 2>&1 || true
      fi
    fi
  fi

  exit "$rc"
}

trap publish_result_on_exit EXIT
