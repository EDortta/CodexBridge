#!/usr/bin/env bash

set -u

base_url="https://codexbridge.inovacaosistemas.com.br"
timestamp="$(date '+%Y-%m-%d_%H-%M-%S')"
log_dir="temp-tools/results"
log_file="$log_dir/$timestamp.curl.test.log"

mkdir -p "$log_dir"

run_curl() {
    local description="$1"
    local url="$2"

    {
        printf '\n===== %s =====\n' "$description"
        printf 'URL: %s\n\n' "$url"

        curl \
            --silent \
            --show-error \
            --include \
            --connect-timeout 10 \
            --max-time 30 \
            "$url" || true

        printf '\n'
    } >> "$log_file" 2>&1
}

run_json() {
    local description="$1"
    local url="$2"

    {
        printf '\n===== %s =====\n' "$description"
        printf 'URL: %s\n\n' "$url"

        response="$(curl \
            --silent \
            --show-error \
            --connect-timeout 10 \
            --max-time 30 \
            "$url")"

        if command -v jq >/dev/null 2>&1; then
            printf '%s\n' "$response" | jq .
        else
            printf '%s\n' "$response"
        fi

        printf '\n'
    } >> "$log_file" 2>&1
}

run_curl \
    "Health check - HTTPS" \
    "$base_url/health"

run_curl \
    "Health check - port 8443" \
    "$base_url:8443/health"

run_json \
    "OAuth authorization server metadata - HTTPS" \
    "$base_url/.well-known/oauth-authorization-server"

run_json \
    "OAuth authorization server metadata - port 8443" \
    "$base_url:8443/.well-known/oauth-authorization-server"

run_json \
    "OAuth protected resource metadata - HTTPS" \
    "$base_url/.well-known/oauth-protected-resource/mcp"

run_json \
    "OAuth protected resource metadata - port 8443" \
    "$base_url:8443/.well-known/oauth-protected-resource/mcp"

printf 'Results written to: %s\n' "$log_file"
