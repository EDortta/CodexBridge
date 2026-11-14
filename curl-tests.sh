#!/bin/bash

d=$(date "+%Y-%m-%d %H:%M:%S")

log_file="temp-tools/results/$d.curl.test.log"

curl -i https://codexbridge.inovacaosistemas.com.br/health >> "$log_file"

curl -i https://codexbridge.inovacaosistemas.com.br:8443/health >> "$log_file"

curl -s https://codexbridge.inovacaosistemas.com.br/.well-known/oauth-authorization-server | jq >> "$log_file"

curl -s https://codexbridge.inovacaosistemas.com.br:8443/.well-known/oauth-authorization-server | jq >> "$log_file"

curl -s https://codexbridge.inovacaosistemas.com.br/.well-known/oauth-protected-resource/mcp | jq >> "$log_file"

curl -s https://codexbridge.inovacaosistemas.com.br:8443/.well-known/oauth-protected-resource/mcp | jq >> "$log_file"
