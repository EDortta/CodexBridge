# Cadastro de projeto autorizado

Como autorizar um repositório a receber tarefas do CodexBridge.

Este é o único caminho pelo qual o produto passa a ler e modificar um repositório.
Não existe outro: o ChatGPT nunca informa caminho, apenas `project_id`.

## Regra central: dois arquivos, sempre juntos

A allowlist é dupla e vive em máquinas diferentes.

| Arquivo | Host | Consumido por | Modelo |
|---|---|---|---|
| `/etc/codex-bridge/registry.json` | `frida` | gateway | `Registry` (`gateway/app/core/registry.py`) |
| `/etc/codex-bridge-agent/projects.json` | `devel3` | agente | `AgentProjectConfig` (`agent/codex_bridge_agent/config.py`) |

O `devel3` real, ao contrário do template aspiracional acima, roda o serviço de
usuário (`~/.config/systemd/user/`, não o hardened de `deploy/systemd/`) e a sua
allowlist real hoje está em `~/.config/codex-bridge-agent/allowed-projects.json`
(`CODEX_BRIDGE_AGENT_ALLOWED_PROJECTS_FILE`), mesmo formato, path diferente —
mesmo padrão já registrado em `docs/napkin-lessons.md` para o executor.

**O `project_id` precisa existir nos dois.** Se estiver só no gateway, a tarefa é
aceita, despachada e o agente responde `unknown_project` — a tarefa falha depois de
já ter sido enfileirada. Se estiver só no agente, o gateway rejeita na submissão.

Essa dessincronia é a falha operacional mais provável do sistema. Ao cadastrar,
edite os dois arquivos na mesma janela de manutenção.

Modelos de referência versionados no repositório: `examples/registry.json` e
`examples/agent-projects.json`.

## Passo a passo

1. **Decidir o `project_id`.** Curto, estável, sem espaço. É o identificador que o
   ChatGPT vai usar e que aparece na auditoria.
2. **No `frida`**, acrescentar o objeto em `projects` de `/etc/codex-bridge/registry.json`.
3. **No `frida`**, acrescentar o `project_id` em `allowed_projects` do executor que
   vai atendê-lo, dentro de `executors` no mesmo arquivo.
4. **No `devel3`**, acrescentar o objeto em `projects` de `/etc/codex-bridge-agent/projects.json`,
   com o `path` real no disco do executor.
5. **No `frida`**, se o acesso for por usuário e não por admin, acrescentar o
   `project_id` em `allowed_projects` do usuário em `/etc/codex-bridge/users.json`.
6. Reiniciar gateway e agente. Ambos carregam os arquivos na inicialização.
7. Validar com `list_projects` e uma tarefa em modo `analyze`.

## Cadastro em lote, com aprovação (WK-20260830, Fase C)

Para expandir o acesso a muitos projetos de uma vez (o objetivo declarado é
alcançar todos os repositórios sob `~/Sync/Projects`), dois scripts
somente-leitura/só-diff, sem allowlist automática:

1. `python3 scripts/discover_projects.py --root ~/Sync/Projects --format table`
   — varre a árvore, encontra todo `.git` real (inclusive submódulos de
   monorepo), sugere um `project_id`. **Não escreve em lugar nenhum.** A
   lista candidata pode ter centenas de entradas (achados: 247 em
   `~/Sync/Projects`, atravessando ~40 pastas de topo, várias com dados
   pessoais/financeiros) — revisão humana, linha a linha, é o próprio
   ponto do passo 2 existir.
2. O operador edita essa lista até uma lista aprovada (`aprovados.json`:
   array de `{"project_id", "name", "path"}`).
3. `python3 scripts/register_projects.py --from aprovados.json --registry-file ... --local-allowed-projects-file ... [--executor-id ...] [--user-registry-file ... --user-id ...]`
   — gera o diff exato para cada um dos quatro pontos de allowlist acima,
   nunca aplica. Só adiciona; nunca remove ou modifica uma entrada
   existente (revogar acesso é uma decisão distinta, sempre manual).
4. O operador aplica o diff manualmente, nos arquivos reais, na mesma
   janela de manutenção do passo a passo acima — reinício e validação
   continuam iguais.

## Schema de projeto

```json
{
  "project_id": "codexbridge-demo",
  "name": "CodexBridge Demo",
  "path": "/srv/projects/codexbridge-demo",
  "allowed_modes": ["analyze", "review", "edit", "test", "implement"],
  "max_timeout_seconds": 3600,
  "sensitive_patterns": ["deploy", "migration", "push"],
  "enabled": true
}
```

| Campo | Efeito real hoje |
|---|---|
| `project_id` | Chave de busca nas duas allowlists. Obrigatório. |
| `name` | Rótulo exibido em `list_projects`. |
| `path` | Raiz passada como `-C` ao `codex exec`. Só é lida do arquivo do **agente**. |
| `allowed_modes` | **Aplicado.** Modo fora da lista é rejeitado no gateway. |
| `max_timeout_seconds` | **Aplicado.** Teto do `timeout_seconds` da tarefa. |
| `sensitive_patterns` | **Não aplicado.** Ver "Campos inertes" abaixo. |
| `enabled` | Desligar o projeto sem removê-lo do arquivo. |

`allowed_modes` é o controle de escrita: um projeto cadastrado só com
`["analyze", "review", "test"]` nunca recebe tarefa que modifique arquivo, porque
`edit` e `implement` são recusados na submissão. **Cadastre o mínimo necessário.**

## Schema de executor

Apenas em `registry.json`, no `frida`.

```json
{
  "executor_id": "devel3",
  "display_name": "devel3",
  "machine_token": "<token longo e aleatório>",
  "max_concurrent_tasks": 1,
  "allowed_projects": ["codexbridge-demo"],
  "enabled": true,
  "expected_timezone": "America/Sao_Paulo",
  "expected_online_windows": ["05:05-20:40"]
}
```

| Campo | Efeito real hoje |
|---|---|
| `machine_token` | Autentica o executor no `wss`. Nunca commitar. |
| `allowed_projects` | **Aplicado.** Terceiro nível de allowlist, por executor. |
| `max_concurrent_tasks` | Limite de tarefas simultâneas. |
| `expected_timezone` | **Não aplicado.** |
| `expected_online_windows` | **Não aplicado.** |

## Campos inertes — leia antes de confiar neles

Três campos existem no schema e **não têm nenhum efeito** no código atual:

- **`sensitive_patterns`** (por projeto). A classificação de tarefa sensível usa
  exclusivamente a lista global `SENSITIVE_KEYWORDS` em `shared/policy.py`
  (`deploy`, `production`, `migration`, `secret`, `secrets`, `push `,
  `pull request`, `terraform apply`, `kubectl apply`, `rm -rf`). Preencher
  `sensitive_patterns` com um termo próprio do seu projeto **não** vai bloquear
  nada. Quem precisa de bloqueio adicional hoje tem que ampliar a lista global.
- **`expected_timezone`** e **`expected_online_windows`** (por executor). São
  metadados descritivos; nenhuma decisão de despacho os consulta.

## Camadas de autorização, na ordem em que agem

1. Autenticação do principal no gateway (OAuth ou bearer).
2. Escopo do principal (`codexbridge.task.submit`, etc.).
3. `allowed_projects` do usuário, em `users.json`.
4. `allowed_projects` do executor, em `registry.json`.
5. `allowed_modes` e `max_timeout_seconds` do projeto, em `registry.json`.
6. Política de sensibilidade no gateway.
7. Existência do `project_id` na allowlist do agente.
8. Política de sensibilidade reavaliada no agente.
9. `BASE_PROMPT` prefixado à instrução, dentro do processo `codex`.

As camadas 1 a 6 rodam no `frida`. As 7 a 9 rodam no `devel3` e continuam valendo
mesmo que o gateway esteja comprometido.

**A camada 7 tem uma válvula opt-in** (`CODEX_BRIDGE_AGENT_AUTO_PROJECT_ROOT`,
WK-20260830-chatgpt-entry-provider-and-delivery): quando configurada, um
`project_id` ausente de `allowed_projects_file` ainda é aceito se existir um
repositório git real com esse nome sob a raiz configurada
(`shared/project_discovery.py`, a mesma varredura de `discover_projects.py`).
A fronteira muda de "este `project_id` foi cadastrado à mão" para "este
`project_id` é um repositório real dentro desta árvore de diretórios" — ainda
uma fronteira, só que mais larga. **Não afeta as camadas 1 a 6**: o projeto
ainda precisa existir no `registry.json` do gateway antes de o ChatGPT
conseguir sequer nomeá-lo (ver `docs/threat-model.md`, "Raiz de
auto-descoberta do executor"). Desligada por padrão; cada operador decide se
quer essa fronteira mais larga ou a lista explícita de sempre.

## Remover um projeto

Inverter a ordem: primeiro `"enabled": false` no arquivo do gateway (para a fila
parar de aceitar), depois remover do agente, depois remover do gateway. Tarefas já
em `running` não são interrompidas por edição de arquivo — use `cancel_codex_task`.
