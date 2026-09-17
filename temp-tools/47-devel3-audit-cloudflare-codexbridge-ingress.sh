#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
RESULT="temp-tools/results/${STAMP}-cloudflare-codexbridge-ingress.txt"
mkdir -p temp-tools/results
exec > >(tee "$RESULT") 2>&1

HOST="codexbridge.inovacaosistemas.com.br"
ZONE_NAME="inovacaosistemas.com.br"
CF_API="https://api.cloudflare.com/client/v4"
FRIDA_SSH=(ssh -o BatchMode=yes -o ConnectTimeout=8 -p 2200 esteban@frida.inovacaosistemas.com.br)
T610_SSH=(ssh -o BatchMode=yes -o ConnectTimeout=8 -p 22 esteban@codexbridge.inovacaosistemas.com.br)

cat <<EOF
== Audit Cloudflare / CodexBridge ingress ==
utc=$(date -u +%FT%TZ)
host=${HOST}
zone=${ZONE_NAME}

Purpose:
- determine whether ${HOST} is proxied by Cloudflare or served as DNS-only;
- detect any Cloudflare Tunnel route for ${HOST};
- inspect whether cloudflared is running/configured on devel3, Frida, or T610;
- compare public 443 and 8443 behavior without changing any routing.

No Cloudflare credential values are printed.
EOF

section() { printf '\n== %s ==\n' "$*"; }

section "Public DNS and HTTP edge fingerprints"
echo "-- DNS A/AAAA/CNAME --"
for t in A AAAA CNAME; do
  echo "[$t]"
  dig +short "$HOST" "$t" || true
done

echo "-- who answers 443/8443 --"
for origin in "https://${HOST}" "https://${HOST}:8443"; do
  echo "[$origin]"
  curl -ksS -o /dev/null -D - --max-time 10 "$origin/health" | sed -n '1,20p' || true
  echo
 done

# Cloudflare-proxied HTTP responses normally carry headers such as cf-ray/server: cloudflare.
for origin in "https://${HOST}" "https://${HOST}:8443"; do
  hdr="$(mktemp)"
  if curl -ksS -o /dev/null -D "$hdr" --max-time 10 "$origin/health"; then
    if grep -Eqi '^(server:[[:space:]]*cloudflare|cf-ray:|cf-cache-status:)' "$hdr"; then
      echo "edge_fingerprint ${origin}=cloudflare"
    else
      echo "edge_fingerprint ${origin}=not_cloudflare_http_proxy"
    fi
  else
    echo "edge_fingerprint ${origin}=unreachable"
  fi
  rm -f "$hdr"
done

section "Locate Cloudflare credentials"
# User-provided expected locations plus a few harmless variants.
CANDIDATES=(
  "$REPO_ROOT/.credentials/cloudflare-edortta.json"
  "$REPO_ROOT/.credentials/cloudflare-lumina"
  "$REPO_ROOT/.credentials/cloudflare-lumina.json"
  "$HOME/.credentials/cloudflare-edortta.json"
  "$HOME/.credentials/cloudflare-lumina"
  "$HOME/.credentials/cloudflare-lumina.json"
  "$HOME/.config/credentials/personal/cloudflare-edortta.json"
  "$HOME/.config/credentials/personal/cloudflare-lumina"
  "$HOME/.config/credentials/personal/cloudflare-lumina.json"
)

mapfile -t CF_FILES < <(
  for p in "${CANDIDATES[@]}"; do
    if [[ -f "$p" ]]; then printf '%s\n' "$p"; fi
    if [[ -d "$p" ]]; then find "$p" -maxdepth 1 -type f -print 2>/dev/null; fi
  done | awk '!seen[$0]++'
)

if ((${#CF_FILES[@]} == 0)); then
  echo "credentials_found=0"
else
  echo "credentials_found=${#CF_FILES[@]}"
  for f in "${CF_FILES[@]}"; do
    echo "credential_file=$(basename "$f")"
  done
fi

# Emit one Authorization mode + headers from a JSON or key=value credential file.
# Secret values stay in shell variables and are never echoed.
build_cf_auth() {
  local f="$1"
  CF_AUTH_MODE=""
  CF_TOKEN=""
  CF_EMAIL=""
  CF_KEY=""

  if jq -e . "$f" >/dev/null 2>&1; then
    CF_TOKEN="$(jq -r '[.. | objects | .api_token?, .apiToken?, .token?, .bearer_token?, .bearer?] | map(select(type=="string" and length>10)) | .[0] // empty' "$f" 2>/dev/null || true)"
    CF_EMAIL="$(jq -r '[.. | objects | .email?, .account_email?] | map(select(type=="string" and contains("@"))) | .[0] // empty' "$f" 2>/dev/null || true)"
    CF_KEY="$(jq -r '[.. | objects | .global_api_key?, .globalApiKey?, .api_key?, .apiKey?] | map(select(type=="string" and length>10)) | .[0] // empty' "$f" 2>/dev/null || true)"
  else
    CF_TOKEN="$(sed -nE 's/^[[:space:]]*(CLOUDFLARE_API_TOKEN|CF_API_TOKEN|API_TOKEN|TOKEN)[[:space:]]*=[[:space:]]*["'"']?([^"'"']+).*/\2/p' "$f" | head -1 || true)"
    CF_EMAIL="$(sed -nE 's/^[[:space:]]*(CLOUDFLARE_EMAIL|CF_EMAIL|EMAIL)[[:space:]]*=[[:space:]]*["'"']?([^"'"']+).*/\2/p' "$f" | head -1 || true)"
    CF_KEY="$(sed -nE 's/^[[:space:]]*(CLOUDFLARE_API_KEY|CF_API_KEY|GLOBAL_API_KEY|API_KEY)[[:space:]]*=[[:space:]]*["'"']?([^"'"']+).*/\2/p' "$f" | head -1 || true)"
  fi

  if [[ -n "$CF_TOKEN" ]]; then
    CF_AUTH_MODE="bearer"
    return 0
  fi
  if [[ -n "$CF_EMAIL" && -n "$CF_KEY" ]]; then
    CF_AUTH_MODE="global_key"
    return 0
  fi
  return 1
}

cf_get() {
  local url="$1"
  if [[ "$CF_AUTH_MODE" == "bearer" ]]; then
    curl -fsS --max-time 15 -H "Authorization: Bearer ${CF_TOKEN}" -H 'Content-Type: application/json' "$url"
  else
    curl -fsS --max-time 15 -H "X-Auth-Email: ${CF_EMAIL}" -H "X-Auth-Key: ${CF_KEY}" -H 'Content-Type: application/json' "$url"
  fi
}

section "Cloudflare API: zone and DNS record"
CF_OK=0
for f in "${CF_FILES[@]:-}"; do
  [[ -n "${f:-}" ]] || continue
  echo "-- trying $(basename "$f") --"
  if ! build_cf_auth "$f"; then
    echo "auth_material=unrecognized"
    continue
  fi
  echo "auth_mode=${CF_AUTH_MODE}"
  if ! zones="$(cf_get "${CF_API}/zones?name=${ZONE_NAME}&status=active" 2>/dev/null)"; then
    echo "zone_query=failed_or_not_permitted"
    continue
  fi
  if ! jq -e '.success == true' >/dev/null <<<"$zones"; then
    echo "zone_query=api_error"
    jq -c '{success,errors}' <<<"$zones" 2>/dev/null || true
    continue
  fi
  ZONE_ID="$(jq -r '.result[0].id // empty' <<<"$zones")"
  if [[ -z "$ZONE_ID" ]]; then
    echo "zone_query=no_matching_zone"
    continue
  fi
  echo "zone_query=ok"
  echo "zone_name=$(jq -r '.result[0].name' <<<"$zones")"
  echo "zone_status=$(jq -r '.result[0].status' <<<"$zones")"

  if records="$(cf_get "${CF_API}/zones/${ZONE_ID}/dns_records?name=${HOST}" 2>/dev/null)"; then
    echo "dns_query=ok"
    jq -r '.result[]? | "dns_record type=\(.type) name=\(.name) content=\(.content) proxied=\(.proxied // false) ttl=\(.ttl)"' <<<"$records"
    if jq -e '.result[]? | select(.proxied == true)' >/dev/null <<<"$records"; then
      echo "cloudflare_dns_proxy_for_host=yes"
    else
      echo "cloudflare_dns_proxy_for_host=no"
    fi
    if jq -e '.result[]? | select(.type=="CNAME" and (.content|endswith("cfargotunnel.com")))' >/dev/null <<<"$records"; then
      echo "cloudflare_tunnel_dns_target=yes"
    else
      echo "cloudflare_tunnel_dns_target=no"
    fi
  else
    echo "dns_query=failed_or_not_permitted"
  fi

  # Account/tunnel APIs need broader permissions than DNS. Failure is informative, not fatal.
  section "Cloudflare API: accounts and tunnels using $(basename "$f")"
  if accounts="$(cf_get "${CF_API}/accounts?per_page=50" 2>/dev/null)" && jq -e '.success == true' >/dev/null <<<"$accounts"; then
    echo "accounts_query=ok count=$(jq '.result|length' <<<"$accounts")"
    while IFS=$'\t' read -r account_id account_name; do
      [[ -n "$account_id" ]] || continue
      echo "account=${account_name}"
      if tunnels="$(cf_get "${CF_API}/accounts/${account_id}/cfd_tunnel?is_deleted=false&per_page=100" 2>/dev/null)" && jq -e '.success == true' >/dev/null <<<"$tunnels"; then
        echo "tunnels_query=ok count=$(jq '.result|length' <<<"$tunnels")"
        while IFS=$'\t' read -r tid tname tstatus; do
          [[ -n "$tid" ]] || continue
          echo "tunnel name=${tname} status=${tstatus} id=${tid}"
          if cfg="$(cf_get "${CF_API}/accounts/${account_id}/cfd_tunnel/${tid}/configurations" 2>/dev/null)" && jq -e '.success == true' >/dev/null <<<"$cfg"; then
            if jq -e --arg h "$HOST" '.result.config.ingress[]? | select(.hostname == $h)' >/dev/null <<<"$cfg"; then
              echo "TUNNEL_MATCH hostname=${HOST} tunnel=${tname} id=${tid}"
              jq -r --arg h "$HOST" '.result.config.ingress[]? | select(.hostname == $h) | "tunnel_ingress hostname=\(.hostname) service=\(.service)"' <<<"$cfg"
            fi
          else
            echo "tunnel_config_query=${tname}:not_permitted_or_unavailable"
          fi
        done < <(jq -r '.result[]? | [.id,.name,(.status // "unknown")] | @tsv' <<<"$tunnels")
      else
        echo "tunnels_query=not_permitted_or_unavailable"
      fi
    done < <(jq -r '.result[]? | [.id,.name] | @tsv' <<<"$accounts")
  else
    echo "accounts_query=not_permitted_or_unavailable"
  fi

  CF_OK=1
  break
 done

if ((CF_OK == 0)); then
  echo "cloudflare_api_audit=inconclusive_no_working_credentials"
fi

inspect_cloudflared_local() {
  local label="$1"
  echo "-- ${label}: cloudflared process/service/config --"
  command -v cloudflared >/dev/null 2>&1 && cloudflared --version || echo "cloudflared_binary=absent"
  pgrep -af cloudflared 2>/dev/null | sed -E 's/(--token[= ]+)[^ ]+/\1[REDACTED]/g' || true
  systemctl is-active cloudflared 2>/dev/null || true
  systemctl status cloudflared --no-pager -n 8 2>/dev/null | sed -E 's/(--token[= ]+)[^ ]+/\1[REDACTED]/g' || true
  for c in /etc/cloudflared/config.yml /etc/cloudflared/config.yaml "$HOME/.cloudflared/config.yml" "$HOME/.cloudflared/config.yaml"; do
    if [[ -r "$c" ]]; then
      echo "config_file=$c"
      grep -E '^[[:space:]]*(tunnel:|hostname:|service:|url:)' "$c" 2>/dev/null | sed -E 's/(token:).*/\1 [REDACTED]/I' || true
    fi
  done
}

section "devel3 cloudflared state"
inspect_cloudflared_local devel3

section "Frida cloudflared state"
if "${FRIDA_SSH[@]}" 'echo frida_ssh=ok; command -v cloudflared >/dev/null 2>&1 && cloudflared --version || echo cloudflared_binary=absent; pgrep -af cloudflared 2>/dev/null | sed -E "s/(--token[= ]+)[^ ]+/\1[REDACTED]/g" || true; systemctl is-active cloudflared 2>/dev/null || true; for c in /etc/cloudflared/config.yml /etc/cloudflared/config.yaml ~/.cloudflared/config.yml ~/.cloudflared/config.yaml; do if [ -r "$c" ]; then echo config_file=$c; grep -E "^[[:space:]]*(tunnel:|hostname:|service:|url:)" "$c" || true; fi; done' 2>&1; then
  :
else
  echo "frida_ssh=failed"
fi

section "T610 cloudflared state via public :22"
if "${T610_SSH[@]}" 'echo t610_ssh=ok; hostname; command -v cloudflared >/dev/null 2>&1 && cloudflared --version || echo cloudflared_binary=absent; pgrep -af cloudflared 2>/dev/null | sed -E "s/(--token[= ]+)[^ ]+/\1[REDACTED]/g" || true; systemctl is-active cloudflared 2>/dev/null || true; for c in /etc/cloudflared/config.yml /etc/cloudflared/config.yaml ~/.cloudflared/config.yml ~/.cloudflared/config.yaml; do if [ -r "$c" ]; then echo config_file=$c; grep -E "^[[:space:]]*(tunnel:|hostname:|service:|url:)" "$c" || true; fi; done' 2>&1; then
  :
else
  echo "t610_ssh=failed_or_offline"
fi

section "Reachability summary"
for port in 22 2200 443 8443; do
  if timeout 4 bash -c "</dev/tcp/${HOST}/${port}" 2>/dev/null; then
    echo "tcp ${HOST}:${port}=open"
  else
    echo "tcp ${HOST}:${port}=closed_or_filtered"
  fi
done

cat <<'EOF'

Interpretation hints:
- `proxied=true` or HTTP headers such as `cf-ray` => Cloudflare reverse proxy is in the request path.
- CNAME to `*.cfargotunnel.com` or `TUNNEL_MATCH` => Cloudflare Tunnel is configured for this hostname.
- DNS-only A record plus no tunnel match => traffic is going directly to the public origin/NAT, not being healed by Cloudflare.
- If 443 depends on T610 while 8443 reaches Frida, moving the canonical public CodexBridge ingress to Frida is architecturally reasonable because Frida hosts the gateway and Bridge Nodes connect outbound by WebSocket.

CODEXBRIDGE_CLOUDFLARE_INGRESS_AUDIT_COMPLETE
EOF

git add "$RESULT"
if ! git diff --cached --quiet; then
  git commit -m "results: audit Cloudflare CodexBridge ingress"
  git push origin development
fi
