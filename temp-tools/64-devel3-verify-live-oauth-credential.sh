#!/usr/bin/env bash
set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
OUT="temp-tools/results/${STAMP}-verify-live-oauth-credential.txt"
mkdir -p temp-tools/results

if [ -f temp-tools/lib/result-publisher.sh ]; then
  source temp-tools/lib/result-publisher.sh
fi

exec > >(tee "$OUT") 2>&1

LOGIN="${1:-esteban}"

finish_fallback() {
  rc=$?
  trap - EXIT
  set +e
  if [ -f "$OUT" ]; then
    {
      echo
      echo "== script exit =="
      echo "exit_code=$rc"
      echo "utc=$(date -u +%FT%TZ)"
    } >>"$OUT"
    git add "$OUT" >/dev/null 2>&1 || true
    if ! git diff --cached --quiet -- "$OUT" 2>/dev/null; then
      git commit -m "results: ${STAMP}-verify-live-oauth-credential" >/dev/null 2>&1 || true
      git push origin development >/dev/null 2>&1 || true
    fi
  fi
  exit "$rc"
}
trap finish_fallback EXIT

echo "== Verify live CodexBridge OAuth credential on Frida =="
echo "utc=$(date -u +%FT%TZ)"
echo "login=$LOGIN"
echo "No password or password hash will be printed or committed."
echo

ssh -tt -p 2200 -o StrictHostKeyChecking=accept-new esteban@frida.inovacaosistemas.com.br \
  "sudo env CODEX_LOGIN='$LOGIN' python3 -" <<'PY'
import base64
import getpass
import hashlib
import hmac
import json
import os
from pathlib import Path

path = Path("/etc/codex-bridge/users.json")
login = os.environ["CODEX_LOGIN"].strip()

if not path.is_file():
    print("registry=missing")
    raise SystemExit(2)

try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except Exception as exc:
    print(f"registry=invalid:{type(exc).__name__}")
    raise SystemExit(2)

users = payload.get("users") or []
print(f"registry=ok")
print(f"user_count={len(users)}")

match = None
for user in users:
    if str(user.get("user_id", "")).lower() == login.lower() or str(user.get("email", "")).lower() == login.lower():
        match = user
        break

if match is None:
    print("login_found=no")
    print("known_logins=" + ",".join(
        str(u.get("user_id", "")) for u in users if u.get("user_id")
    ))
    raise SystemExit(3)

print("login_found=yes")
print(f"user_id={match.get('user_id')}")
print(f"email={match.get('email')}")
print(f"enabled={bool(match.get('enabled', True))}")
print("roles=" + ",".join(match.get("roles") or []))

encoded = str(match.get("password_hash") or "")
try:
    algorithm, rounds_s, salt_b64, digest_b64 = encoded.split("$", 3)
    rounds = int(rounds_s)
except Exception:
    print("hash_format=invalid")
    raise SystemExit(4)

print(f"hash_format={algorithm}")
print(f"hash_iterations={rounds}")

if algorithm != "pbkdf2_sha256":
    print("credential_verification=unsupported_hash")
    raise SystemExit(4)

def decode(value: str) -> bytes:
    value += "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(value)

password = getpass.getpass("Password to verify (not echoed): ")
derived = hashlib.pbkdf2_hmac(
    "sha256",
    password.encode("utf-8"),
    decode(salt_b64),
    rounds,
)
ok = hmac.compare_digest(derived, decode(digest_b64))
password = None

print("credential_verification=" + ("ok" if ok else "failed"))
if not bool(match.get("enabled", True)):
    print("oauth_login=blocked_disabled_user")
    raise SystemExit(5)
if not ok:
    print("oauth_login=would_reject")
    raise SystemExit(6)

print("oauth_login=would_accept")
print("CODEXBRIDGE_LIVE_CREDENTIAL_VALID")
PY
