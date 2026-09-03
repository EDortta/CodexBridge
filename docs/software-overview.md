# Visão geral do software

## Metadados

- work_id: WK-20260804-codexbridge-agent-limits
- data: 2026-08-04
- owner: Esteban D.Dortta
- project_context_ready: yes

## Produto

O CodexBridge conecta o ChatGPT a executores remotos que rodam `codex exec` em
repositórios locais, sem expor SSH público e sem aceitar caminhos arbitrários.

O ChatGPT fala apenas com o `gateway`, por um servidor MCP remoto em `HTTPS /mcp`.
O gateway nunca abre conexão para o executor: é o executor que abre uma conexão
reversa `wss` e fica escutando tarefas.

## Stack

- Python >= 3.10
- FastAPI + uvicorn (gateway HTTP/MCP)
- WebSocket (`websockets`) para o canal reverso do agente
- SQLAlchemy 2 + PostgreSQL em produção, SQLite assíncrono em teste/desenvolvimento
- Pydantic 2 / pydantic-settings para contratos e configuração
- prometheus-client para métricas, python-json-logger para logs estruturados
- pytest + pytest-asyncio para testes

## Usuários

- **Operador (Esteban)**: registra projetos e executores, aprova tarefas sensíveis,
  opera gateway e agente.
- **Cliente MCP (ChatGPT)**: submete tarefas por `project_id`, acompanha logs,
  resultado e diff. Nunca informa caminho de sistema de arquivos.
- **Bridge Node** (`devel3`): máquina que tem os repositórios locais e roda o
  executor (`codex-bridge-agent`). O `T610` foi a máquina de desenvolvimento
  original e sobrevive apenas como valor de exemplo; ver `docs/architecture.md`
  e `docs/control-plane.md` para a distinção entre Node (a máquina) e Executor
  (o processo/conexão que ela mantém com o gateway) — ver `docs/glossary.md`.

Autorização no gateway é por principal com `roles` e `scopes`
(`codexbridge.read`, `codexbridge.task.submit`, `codexbridge.task.cancel`,
`codexbridge.admin`). O modo de autenticação do MCP é `oauth` ou bearer estático.

## Módulos

| Caminho | Responsabilidade |
|---|---|
| `gateway/app/main.py` | Aplicação FastAPI, rotas HTTP, `/agent/ws`, OAuth |
| `gateway/app/mcp/` | Servidor MCP remoto e definição das 11 ferramentas |
| `gateway/app/core/` | Config, logging, registry de projetos/executores, users, OAuth, rate limit |
| `gateway/app/services/` | `agent_hub` (despacho e sessões), `store` (persistência), `audit`, `metrics` |
| `gateway/app/models/entities.py` | Tabelas de tarefa, eventos, auditoria |
| `agent/codex_bridge_agent/` | Executor reverso: `service`, `codex_runner`, `git_tools`, `config` |
| `shared/` | `protocol` (contratos), `policy` (níveis de política), `security` |
| `deploy/` | systemd, nginx e proxy de borda Incus |
| `migrations/` | Migrações de schema |
| `tests/` | Testes unitários e de integração |

## Comportamento chave

### Ferramentas MCP expostas

`list_projects`, `list_executors`, `executor_status`, `submit_codex_task`,
`get_task_status`, `get_task_logs`, `get_task_result`, `continue_codex_session`,
`cancel_codex_task`, `approve_codex_task`, `list_recent_tasks`,
`start_development_task` (WK-20260830-chatgpt-entry-provider-and-delivery,
issue #65 — a entrada conversacional: "resolva a issue X do projeto Y"),
`create_reminder`/`cancel_reminder` (issue #71 — Google Calendar do operador,
sem relação com execução de código).

### Isolamento de projeto

- Projetos autorizados são cadastrados por `project_id` em `registry.json` (gateway)
  **e** em `projects.json` (agente); os dois precisam concordar. O procedimento
  completo está em `docs/project-onboarding.md`.
- O ChatGPT informa `project_id`, nunca um caminho.
- O agente resolve `realpath` e compara contra a allowlist local antes de executar.
- A allowlist do agente (`CODEX_BRIDGE_AGENT_ALLOWED_PROJECTS_FILE`) é a última
  barreira: mesmo um gateway comprometido não alcança repositório fora dela.

### Níveis de política

| Modo | Nível |
|---|---|
| `analyze`, `review`, `test` | `read` |
| `edit`, `implement` | `controlled_write` |
| demais | `sensitive` |

Instrução que casa com palavra-chave sensível (`deploy`, `production`, `migration`,
`secret`, `push `, `pull request`, `terraform apply`, `kubectl apply`, `rm -rf`)
é promovida a `sensitive` e exige aprovação explícita.

### Restrições confirmadas do Codex CLI 0.145.0

A implementação usa apenas capacidades verificadas em `2026-07-28`:
`codex exec [PROMPT]`, `--json`, `-C <DIR>`, `-o <FILE>`, `--skip-git-repo-check`,
`--ephemeral`, `codex exec resume`. Nenhuma flag fora dessa lista é presumida.

Verificado adicionalmente em `2026-08-22` contra `codex-cli 0.147.0` (issue #34):
`codex exec -s/--sandbox <read-only|workspace-write|danger-full-access>`.
`codex exec resume` **não** aceita `-s`/`--sandbox` (mesma lacuna já confirmada
para `-C`, issue #33) — `_build_command` nunca emite a flag nesse ramo.
`codex_runner.py` agora sempre passa `-s` explicitamente no dispatch inicial
(nunca em branco): `read-only` por padrão, `workspace-write` apenas quando o
`policy_level` da tarefa já indicava escrita (`edit`/`implement`) — ver
`shared/policy.py:policy_level_for_mode`. Antes disso a escrita dependia de
`trust_level = "trusted"` já estar gravado em `~/.codex/config.toml` no host
do executor, um estado externo e silencioso que fazia tarefas de escrita
"terminarem com sucesso" sem alterar nada.

## Distinção crítica para agentes

O CodexBridge **é uma ferramenta cujo propósito é despachar execução para outros
repositórios em runtime**. Isso é comportamento do produto, executado pelo agente
compilado, sob allowlist, mediante `project_id` vindo do MCP.

Isso **não** estende o escopo de um agente de IA que desenvolve o CodexBridge.
Quem trabalha neste repositório trabalha neste repositório. Os repositórios que o
produto alcança em runtime são dados de configuração, não área de trabalho.

Ver `docs/limits.md`, seção "Fronteira de repositório".
