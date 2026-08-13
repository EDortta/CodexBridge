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
| `user_registry_file` | `examples/users.json` |
| `mcp_auth_mode` | `bearer` (o token é `change-me`) |
| `rate_limit` | 120 requisições / 60s, só em `/mcp` |

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

## Política de sandbox do `codex exec` — decisão em aberto

`CodexRunner.run_task` monta o comando com `--json`, `-C` e `-o` apenas. Nenhuma
flag de sandbox ou de aprovação é passada, então o nível de escrita que o Codex
tem dentro do projeto alvo é **o default do CLI**, herdado e não declarado.

O `README.md` lista `--skip-git-repo-check` e `--ephemeral` entre as capacidades
verificadas do Codex CLI 0.145.0, e nenhuma das duas é usada.

Num produto cuja função é modificar repositórios de terceiros, isso precisa ser
escolha explícita. A decisão está pendente com o operador; até que seja tomada,
não altere as flags do runner por conta própria.

## Antes de entregar

Conforme `docs/limits.md`:

1. `pytest` verde.
2. Diff revisado quanto a escopo, duplicação, contrato e segredos.
3. Mudança em `oauth.py`, `users.py`, `shared/security.py`, `shared/policy.py` ou
   nas allowlists exige revisão de segurança declarada na entrega.
4. Nada de deploy: é passo separado, com aprovação humana explícita.
