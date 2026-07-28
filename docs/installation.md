# Instalação

## Gateway no Frida

1. Criar usuário:
   `sudo useradd --system --create-home --home-dir /var/lib/codex-bridge codexbridge`
2. Copiar o projeto para `/opt/codex-bridge`.
3. Instalar dependências no `venv`:
   `python3 -m venv /opt/codex-bridge/.venv && /opt/codex-bridge/.venv/bin/pip install /opt/codex-bridge`
4. Criar `/etc/codex-bridge/env` a partir de `.env.example`.
   No `frida`, prefira `CODEX_BRIDGE_BIND_HOST=127.0.0.1` e `CODEX_BRIDGE_BIND_PORT=18080`, porque `*:8080` já está ocupado por `mosquitto`.
5. Ajustar `/etc/codex-bridge/registry.json`.
6. Instalar `deploy/systemd/codex-bridge-gateway.service`.
7. Ajustar `deploy/nginx/frida-codex-bridge.conf`.
8. Habilitar:
   `sudo systemctl enable --now codex-bridge-gateway`

## Agente no Devel3

1. Criar usuário:
   `sudo useradd --system --create-home --home-dir /var/lib/codex-bridge-agent codexbridge`
2. Copiar o projeto para `/opt/codex-bridge`.
3. Garantir `codex` autenticado para esse usuário.
4. Criar `/etc/codex-bridge-agent/env`.
5. Criar `/etc/codex-bridge-agent/projects.json`.
6. Instalar `deploy/systemd/codex-bridge-agent.service`.
7. Habilitar:
   `sudo systemctl enable --now codex-bridge-agent`

## DNS e hostname

Prefira um subdomínio dedicado para o gateway, por exemplo `codexbridge.inovacaosistemas.com.br`, apontando para o mesmo IP público já usado pelo `frida`.
