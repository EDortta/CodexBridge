# Desenvolvimento

Como preparar o ambiente, rodar os testes e subir gateway e agente localmente.

## Preparar o ambiente

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
```

Requer Python >= 3.10. A instalação editável expõe os três pacotes do projeto
(`gateway`, `agent`, `shared`) no caminho de import.

Não há configuração de linter nem de type-checker no repositório: `pyproject.toml`
declara apenas `build-system`, dependências e a configuração do `pytest`. Menções
genéricas a "rodar lint" não têm alvo aqui.

## Rodar os testes

```bash
pytest
```

`testpaths = ["tests"]` e `asyncio_mode = "auto"` já estão em `pyproject.toml`, então
não é preciso passar caminho nem marcar corrotina.

Estado verificado em `2026-08-04`: **17 testes, todos passando, ~2s**. Duas
`DeprecationWarning` do FastAPI sobre `@app.on_event`, que continua em uso em
`gateway/app/main.py` — é ruído conhecido, não falha.

Cobertura por arquivo:

| Arquivo | Alvo |
|---|---|
| `tests/unit/test_policy.py` | níveis de política e palavras sensíveis |
| `tests/unit/test_security.py` | sanitização, comparação segura, allowlist de env |
| `tests/unit/test_users.py` | registro de usuários, escopos, papéis |
| `tests/unit/test_agent_service.py` | despacho no agente |
| `tests/unit/test_main_import.py` | a aplicação importa sem efeito colateral |
| `tests/integration/test_store_and_mcp.py` | persistência e chamada MCP ponta a ponta |

Nenhum teste cobre hoje: fluxo OAuth, rate limiting, reconexão do WebSocket,
`CodexRunner.run_task` com processo real.

## Rodar o gateway localmente

O padrão de desenvolvimento não precisa de PostgreSQL nem de arquivo de ambiente:
`Settings` (`gateway/app/core/config.py`) já cai em SQLite e nos arquivos de
`examples/`.

```bash
uvicorn gateway.app.main:app --reload --port 8080
```

Padrões relevantes quando não há `.env`:

| Configuração | Padrão de desenvolvimento |
|---|---|
| `database_url` | `sqlite+aiosqlite:///./codex_bridge.db` |
| `registry_file` | `examples/registry.json` |
| `user_registry_file` | `/etc/codex-bridge/users.json` — **não** `examples/users.json` |
| `mcp_auth_mode` | `bearer` (o token é `change-me`) |
| `rate_limit` | 120 requisições / 60s, em `/mcp` e em toda rota `/api` |
| `audit_event_retention_days` | 90 (varredura no startup) |

O padrão de `user_registry_file` não aponta para o exemplo de propósito: o
`admin` de `examples/users.json` tem o texto claro da senha comitado neste
repositório, e `POST /api/v1/auth/sign-in` o alcançaria com um único POST não
autenticado. Em desenvolvimento, aponte a variável para uma cópia sua:

```
export CODEX_BRIDGE_USER_REGISTRY_FILE=$PWD/.local/users.json
```

A conta do exemplo é recusada mesmo quando o arquivo é apontado explicitamente
(motivo `published_example_credential`) — troque o hash, receita em
`docs/installation.md`.

Verificar: `curl -s localhost:8080/healthz`.

Para exercitar OAuth localmente é preciso `CODEX_BRIDGE_MCP_AUTH_MODE=oauth` e um
`CODEX_BRIDGE_PUBLIC_BASE_URL` alcançável — o fluxo de autorização redireciona.

## Rodar o agente localmente

```bash
python -m agent.codex_bridge_agent
```

Precisa de um gateway no ar em `CODEX_BRIDGE_AGENT_GATEWAY_WS_URL` (padrão
`ws://127.0.0.1:8080/agent/ws`) e do `machine_token` batendo com o do
`registry.json`. O padrão de `allowed_projects_file` é `examples/agent-projects.json`,
que aponta para `/srv/projects/codexbridge-demo` — caminho que provavelmente não
existe na sua máquina.

Para um ciclo completo local, aponte o projeto de exemplo para um repositório git
descartável criado no scratchpad da sessão. **Nunca aponte a allowlist de teste
para um repositório real.**

## Política de sandbox do `codex exec` (issue #34, decidido em 2026-08-22)

Decisão tomada pelo operador: `CodexRunner.run_task` agora sempre passa `-s`
explicitamente — nunca herda o default silencioso do CLI. `read-only` é o
padrão para uma tarefa que não pede escrita (`sandbox` não informado, ou
`PolicyLevel.READ` — modos `analyze`/`review`/`test`); `workspace-write` é
emitido quando `AgentService._handle_dispatch` calcula, a partir do
`policy_level` da própria tarefa (`edit`/`implement` → `CONTROLLED_WRITE`,
ou `SENSITIVE` já aprovado), que a tarefa pretende escrever — ver
`shared/policy.py:policy_level_for_mode` e
`agent/codex_bridge_agent/service.py:_sandbox_for`. `AgentSettings.
allow_workspace_write=False` é o trava adicional no nível da máquina: um
operador pode travar um executor específico em somente-leitura
independentemente do que qualquer tarefa peça.

Antes disso, o nível de escrita do Codex dentro do projeto alvo era **o
default do CLI**, herdado e não declarado — na prática dependia de
`trust_level = "trusted"` já estar gravado em `~/.codex/config.toml` no host
do executor, um estado externo, silencioso e não relacionado a nada que o
CodexBridge decide. Uma tarefa de escrita apontada a um projeto recém
registrado terminava com sucesso (`exit 0`, `TaskState.COMPLETED`) sem
alterar nada — ver `docs/napkin-lessons.md`, entrada de 2026-08-21, e
`tests/integration/test_codex_runner_real_process.py`, que agora prova as
duas pontas (leitura bloqueia escrita; `workspace-write` explícito escreve de
verdade) contra o CLI real.

## Antes de entregar

Conforme `docs/limits.md`:

1. `pytest` verde.
2. Diff revisado quanto a escopo, duplicação, contrato e segredos.
3. Mudança em `oauth.py`, `users.py`, `shared/security.py`, `shared/policy.py` ou
   nas allowlists exige revisão de segurança declarada na entrega.
4. Nada de deploy: é passo separado, com aprovação humana explícita.
