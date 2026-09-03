# RESUME — WK-20260902-merge-thirteen-prs (epic #73)

- work_id: WK-20260902-merge-thirteen-prs
- data: 2026-09-02
- branch: `development` (`a40021c`, empurrado). Nada em `main`.

## Next Step (DO THIS FIRST)

Aplicar as migrações `0012`–`0016` (`python3 scripts/apply_migrations.py`) e
acrescentar a `location /control` ao nginx da frida — o bloco pronto está em
`docs/operations.md` e já no `deploy/nginx/frida-codex-bridge.conf` versionado.
O vhost é allowlist sem catch-all: sem essa entrada o painel dá 404 na borda,
mesmo com a app servindo. Ambas são ação do operador; nenhum agente as executa.

Depois disso, a Stage 6 (Missions/Decisions/Audit convergindo no Control) é o
próximo corte de código.

## Current state

Stages 1–4 do épico entregues e mergeadas em `development`:

- **Stage 1** (domínio, `0009`) e **Stage 2** (visibilidade de frota, `/nodes`)
  já estavam.
- **Stage 3** — o node varre `AgentSettings.discovery_roots` e propõe
  candidatos por `DISCOVERY_REPORT`; o painel adota ou nega
  (`/api/v1/discovered-resources/{id}/adopt|deny`). `record_discovery_report`
  escreve **só** `discovered_resources`: "o node propõe, o painel adota" é
  estrutural, não convenção.
- **Stage 4** — `effective_task_modes` faz uma autorização concedida gatear um
  dispatch de verdade. Par sem `workspace_bindings` continua idêntico ao de
  antes, permanentemente. O executor recusa por conta própria um modo que sua
  configuração nunca ofereceu.
- **Stage 5, primeiro corte** — CodexBridge Control: três telas HTML servidas
  pelo próprio gateway.
- **#76 (corte mínimo)** — token hasheado, invite/enroll/revoke, `registry.json`
  vira semente.

Contrato em **1.14.0**, publicado em `contract/1.14.0/`.

## Checks

`.venv/bin/python -m pytest -q`: **1371 passam, 9 skipped, 0 falham** (duas
rodadas). `tests/contract/`: 145 passam.

## NOT validated

Nenhum deploy. Nenhum node real se inscreveu por um gateway vivo; o painel
nunca abriu num navegador real; as migrações nunca rodaram contra MySQL; o
bloco de nginx nunca passou por um nginx de verdade.

## Watch for

- `/control/invite` é a quarta tela e **não funciona**: a build do painel foi
  cortada antes de `POST /api/v1/nodes/invite` existir na linhagem dela. O
  endpoint está em `development` agora, então a tela precisa de uma PR curta
  que a ligue — a página explica isso ao operador em vez de mostrar um
  formulário que não posta para lugar nenhum.
- `Decision.decisionType` ficou fora de `required` no contrato, embora o
  servidor sempre o envie (ver `handoff.md`). Reversível na próxima mudança de
  namespace.
