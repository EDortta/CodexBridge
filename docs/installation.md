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
   Defina também `CODEX_BRIDGE_API_TRUSTED_PROXIES` com os endereços dos proxies
   à frente do gateway — é o que permite ao rate limiting distinguir um chamador
   do outro. **No `frida` o valor é `127.0.0.1`**, medido em 2026-08-10: o
   `nginx` local é o único hop que anexa ao `X-Forwarded-For` (o log registrou o
   IP público do cliente em `$remote_addr`, e o gateway vê o peer `127.0.0.1`),
   de modo que o header chega com uma entrada só. Se a topologia mudar, meça de
   novo em vez de deduzir: com o valor errado, ou todo mundo cai num bucket só,
   ou o cliente escolhe o próprio.
5. Ajustar `/etc/codex-bridge/registry.json`.
6. Criar `/etc/codex-bridge/users.json` a partir de `examples/users.json` e
   **trocar a senha inicial** — o hash que o exemplo traz tem o texto claro
   (`change-me-now`) comitado neste repositório, e `users.authenticate` recusa
   qualquer conta que ainda o carregue (401, motivo
   `published_example_credential` na auditoria). Gerar o novo hash com o custo
   esperado:

   ```
   python3 - <<'EOF'
   import base64, getpass, hashlib, secrets
   ITERATIONS = 600000
   salt = secrets.token_bytes(16)
   digest = hashlib.pbkdf2_hmac("sha256", getpass.getpass("senha: ").encode(), salt, ITERATIONS)
   b64 = lambda raw: base64.urlsafe_b64encode(raw).decode().rstrip("=")
   print("$".join(("pbkdf2_sha256", str(ITERATIONS), b64(salt), b64(digest))))
   EOF
   ```

   O custo pode ser outro: `users.authenticate` lê a contagem de iterações do
   próprio registro para cobrar o mesmo de um usuário inexistente, então o
   oráculo de tempo não reabre. O que muda com um custo menor é só quanto custa
   quebrar a senha offline.

   `CODEX_BRIDGE_USER_REGISTRY_FILE` **precisa apontar para esse arquivo**. Sem
   a variável o padrão é `/etc/codex-bridge/users.json`, e um gateway que não
   tenha o arquivo simplesmente não deixa ninguém entrar — falha fechada, de
   propósito. O padrão antigo apontava para `examples/users.json`, dentro do
   checkout.

   **Ao atualizar uma instalação que nunca definiu essa variável**, ela para de
   autenticar: o padrão antigo resolvia para um arquivo do repositório e o novo
   não. O sintoma é `401 Sign-in failed.` em tudo e `403 user_registry_unavailable`
   no `/mcp` para tokens já emitidos. O startup registra o motivo em nível
   `ERROR`, nomeando o arquivo e a variável:
   ```
   journalctl -u codex-bridge-gateway | grep 'user registry unusable'
   ```
7. Instalar `deploy/systemd/codex-bridge-gateway.service`.
8. Ajustar `deploy/nginx/frida-codex-bridge.conf`.
   **O arquivo instalado no `frida` chama-se `codexbridge-https`** (com um
   `codexbridge-http` para a 80), em `/etc/nginx/sites-available/`. O nome no
   repositório não bate com o nome instalado, então editar um não toca o outro —
   verificado em 2026-08-10, quando o vhost em produção ainda era a versão sem
   `/health`, `/ready` e `/api/`.
   Esse arquivo é uma **allowlist de `location` sem catch-all**: rota que não
   estiver nomeada nele responde 404 na porta da frente, por melhor que funcione
   na aplicação. Publicar rota nova são sempre duas edições — o router e este
   arquivo. `tests/contract/test_proxy_routes.py` reprova quando as duas
   discordam.
9. **Aplicar as migrations antes de subir o serviço.**
   O `sudo -u` **não** lê `/etc/codex-bridge/env` — esse arquivo só é carregado
   pelo systemd (`EnvironmentFile=`). Sem passar o alvo, o script cai no default
   `sqlite:///./codex_bridge.db`, cria um SQLite no diretório atual, reporta
   sucesso e **não toca no banco real**.

   E **não use `. /etc/codex-bridge/env`**: o formato do `EnvironmentFile` aceita
   valor com espaço sem aspas (`CODEX_BRIDGE_OAUTH_DEFAULT_SCOPES=a b c`), que o
   bash tenta executar — verificado no deploy de 2026-08-10, onde o `source`
   falhou com `codexbridge.task.submit: command not found`. Leia a variável
   diretamente:
   ```
   DBURL=$(sudo sed -n 's/^CODEX_BRIDGE_DATABASE_URL=//p' /etc/codex-bridge/env | head -1)
   RUN="sudo -u codexbridge /opt/codex-bridge/.venv/bin/python \
        /opt/codex-bridge/scripts/apply_migrations.py --database-url $DBURL"
   $RUN --dry-run
   $RUN
   ```
   Banco criado antes deste script existir (todos os atuais) precisa de um passo
   de adoção uma única vez, porque `0001_init.sql` é Postgres-only e sequer
   parseia em SQLite:
   ```
   … apply_migrations.py --mark-applied 0001_init.sql
   ```
   `0004_drop_user_email.sql` é o único que **remove** colunas
   (`user_email` das três tabelas de credencial). O código deixou de preenchê-las
   e elas são `not null`, então um gateway atualizado sem essa migração **não
   sobe**: `schema_guard` recusa e nomeia o arquivo. Preferível ao alternativo,
   que seria um erro de integridade no primeiro sign-in. Nenhuma linha é
   perdida — todas já carregam `user_id`.
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
