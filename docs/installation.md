# Instalação

## Gateway no Frida

1. Criar usuário:
   `sudo useradd --system --create-home --home-dir /var/lib/codex-bridge codexbridge`
2. Copiar o projeto para `/opt/codex-bridge`.
3. Instalar dependências no `venv`:
   `python3 -m venv /opt/codex-bridge/.venv && /opt/codex-bridge/.venv/bin/pip install /opt/codex-bridge`
4. Criar `/etc/codex-bridge/env` a partir de `.env.example`.
   No `frida`, prefira `CODEX_BRIDGE_BIND_HOST=127.0.0.1` e `CODEX_BRIDGE_BIND_PORT=18080`, porque `*:8080` já está ocupado por `mosquitto`.
   Para uso com ChatGPT, defina `CODEX_BRIDGE_MCP_AUTH_MODE=oauth`, `CODEX_BRIDGE_PUBLIC_BASE_URL=https://codexbridge.inovacaosistemas.com.br:8443` e `CODEX_BRIDGE_USER_REGISTRY_FILE=/etc/codex-bridge/users.json`.
5. Ajustar `/etc/codex-bridge/registry.json`.
6. Criar `/etc/codex-bridge/users.json` a partir de `examples/users.json` e trocar a senha inicial.
7. Instalar `deploy/systemd/codex-bridge-gateway.service`.
8. Ajustar `deploy/nginx/frida-codex-bridge.conf`.
   Esse arquivo é uma **allowlist de `location` sem catch-all**: rota que não
   estiver nomeada nele responde 404 na porta da frente, por melhor que funcione
   na aplicação. Publicar rota nova são sempre duas edições — o router e este
   arquivo. `tests/contract/test_proxy_routes.py` reprova quando as duas
   discordam.
9. **Aplicar as migrations antes de subir o serviço.**
   O `sudo -u` **não** lê `/etc/codex-bridge/env` — esse arquivo só é carregado
   pelo systemd (`EnvironmentFile=`). Sem carregá-lo à mão, o script cai no
   default `sqlite:///./codex_bridge.db`, cria um SQLite no diretório atual,
   reporta sucesso e **não toca no Postgres** — de modo que o serviço continua
   batendo em `SchemaOutOfDate`. Carregue o env explicitamente:
   ```
   set -a; . /etc/codex-bridge/env; set +a
   echo "alvo: $CODEX_BRIDGE_DATABASE_URL"   # confira antes de aplicar
   sudo -u codexbridge --preserve-env=CODEX_BRIDGE_DATABASE_URL \
       /opt/codex-bridge/.venv/bin/python \
       /opt/codex-bridge/scripts/apply_migrations.py --dry-run
   sudo -u codexbridge --preserve-env=CODEX_BRIDGE_DATABASE_URL \
       /opt/codex-bridge/.venv/bin/python \
       /opt/codex-bridge/scripts/apply_migrations.py
   ```
   O startup **não migra sozinho** — aplicar mudança de schema em banco vivo é
   decisão do operador, não efeito colateral de um deploy. Em compensação, o
   startup **recusa subir** quando o schema está atrasado, nomeando o objeto que
   falta e este comando. Como a unit tem `Restart=always`, pular este passo
   transforma um `systemctl restart` de rotina em crash loop de 5 em 5 segundos.

   Banco criado antes deste script existir (todos os atuais) precisa de um passo
   de adoção uma única vez, porque `0001_init.sql` é Postgres-only e sequer
   parseia em SQLite:
   ```
   … apply_migrations.py --mark-applied 0001_init.sql
   ```
10. Habilitar:
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

No ambiente atual, o endpoint público do bridge é `https://codexbridge.inovacaosistemas.com.br:8443`. O agente deve usar `wss://codexbridge.inovacaosistemas.com.br:8443/agent/ws`.
