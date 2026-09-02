# Protocolo interno

## MCP externo

Endpoint: `POST /mcp`

Métodos suportados:

* `initialize`
* `tools/list`
* `tools/call`

Ferramentas expostas:

* `executor_status`
* `list_executors`
* `list_projects`
* `submit_codex_task`
* `get_task_status`
* `get_task_logs`
* `get_task_result`
* `continue_codex_session`
* `cancel_codex_task`
* `approve_codex_task`
* `list_recent_tasks`
* `start_development_task`
* `create_reminder`
* `cancel_reminder`

São 14 ferramentas. `create_reminder`/`cancel_reminder` (issue #71) escrevem
no Google Calendar do operador, não em `tasks` — nada a ver com execução de
código. Exigem escopo `codexbridge.reminders.write` e ficam desligadas com
erro acionável (nunca 500) quando `CODEX_BRIDGE_GOOGLE_CALENDAR_ID` ou
`CODEX_BRIDGE_GOOGLE_CALENDAR_CREDENTIALS_FILE` não estão configuradas —
o resto do gateway continua servindo normalmente. `approve_codex_task` é a que libera tarefa parada em
`awaiting_approval` pela política de sensibilidade, e exige principal com escopo
`codexbridge.task.approve` ou `can_approve_sensitive`.

`start_development_task` (WK-20260830-chatgpt-entry-provider-and-delivery, issue
#65) é a entrada conversacional: resolve `project` (id, nome ou prefixo único),
resolve o executor automaticamente quando omitido, calcula `expires_at` sozinho
e devolve uma estimativa de duração (`eta_seconds`/`eta_basis`/`eta_sample_size`)
baseada no histórico real de tarefas. Aceita `issue` (`docs:NNN`/`NNN` resolvido
**no executor**, `local:<id>` resolvido no gateway, `gh:<n>` recusado —
ingestão de issue do GitHub não tem dono neste sistema) e `engine`
(`codex`/`claude`/`cursor-agent`/`gemini`/`opencode`/`aider`, default `claude`).
`allow_push=true` exige `branch` casando `PUSHABLE_BRANCH_PATTERN` e escopo
`codexbridge.task.approve` — nunca cria a tarefa sem os dois. As quatro
ferramentas com nome `codex` continuam respondendo exatamente como antes
(57a surface inventory): `get_task_status` e `list_recent_tasks` só ganharam
campos aditivos (`engine`, `issue_ref`, `delivery`, `delivery_result`).

## Canal reverso do agente

Endpoint: `wss://codexbridge.inovacaosistemas.com.br:8443/agent/ws?executor_id=<ID>`

O token de máquina vai no header `X-Executor-Token`, **não na URL**. Um handshake
WebSocket é uma requisição HTTP e carrega headers normalmente; a query string vira
linha de log em todo componente do caminho — foi assim que o token apareceu 37
vezes no journal do gateway e 70 nos logs do nginx (#15). O `executor_id` continua
na query: ele nomeia o executor, não é segredo.

```
GET /agent/ws?executor_id=devel3
Upgrade: websocket
X-Executor-Token: <token de máquina>
```

Compatibilidade: a forma antiga `?token=...` **continua aceita por uma release**,
para que gateway e agente possam ser publicados em momentos diferentes. Quando ela
é usada, o gateway emite um `WARNING` de depreciação — sem o valor do token. O
header vence quando os dois estão presentes, para que um agente já corrigido não
seja rebaixado por um parâmetro remanescente em proxy ou unit file.

Códigos de fechamento no handshake:

| Código | Significado |
|---|---|
| `4401` | nenhuma credencial apresentada |
| `4403` | token não confere com o registro |
| `4404` | `executor_id` desconhecido |

Mensagens (`AgentMessageType` em `shared/protocol.py`):

* `hello`
* `hello_ack`
* `heartbeat`
* `task.dispatch`
* `task.ack`
* `task.log`
* `task.result`
* `task.cancel`
* `task.pause`
* `task.resume`
* `task.restart`
* `task.cancelled`
* `forge.operation`
* `forge.operation_result`
* `error`

Não existe mensagem `task.progress`. O progresso é inferido pelo fluxo de
`task.log`, cada uma com `offset` incremental.

Campos comuns:

* `message_id`
* `executor_id`
* `sent_at`
* `type`
* `payload`

## Idempotência

O gateway persiste `message_id` em `message_receipts`. Mensagens repetidas do agente são descartadas.

## Reconexão: replay de controle pendente

`AgentHub.register()` roda a cada `hello` aceito, **antes** de qualquer
`task.dispatch` para esse executor:

1. Marca o executor como conectado.
2. Busca tarefas desse executor em `cancelled` sem `task.cancel_acknowledged`
   registrado — o executor nunca confirmou a parada porque estava
   desconectado quando `task.cancel` foi enviado (issue #17). Reenvia
   `task.cancel` para cada uma.
3. Busca tarefas presas em `pausing`/`resuming`/`restarting` — o `task.ack`
   correspondente nunca chegou porque o executor caiu antes de respondê-lo
   (issue #16). Reenvia `task.pause`/`task.resume`/`task.restart` conforme
   o estado.
4. Só então despacha a próxima tarefa da fila, se houver vaga.

O replay de `task.cancel` é limitado a `cancel_replay_max_age_seconds`
(padrão 24h, `gateway/app/core/config.py`) contado a partir do momento em que
a tarefa virou `cancelled`. O replay de `task.pause`/`task.resume`/
`task.restart` (passo 3) é limitado do mesmo jeito, por
`control_replay_max_age_seconds` (padrão 24h também, configurável
separadamente), contado a partir do último `task.state_changed` da tarefa —
esse limite não existia antes (issue #17 council, "the sweep skeptic"): sem
ele, uma tarefa presa havia um ano era reenviada a cada reconexão, para
sempre. Um executor que reaparece depois do prazo quase certamente já
terminou ou foi reimplantado — o replay existe para fechar a janela normal de
reconexão, não para reenviar controles de dias atrás. Passado o prazo, a
tarefa permanece no estado em que estava, sem novo reenvio.

O executor sempre confirma um `task.cancel`, mesmo para um `task_id` que não
conhece: a tarefa correspondente já pode ter terminado, expirado, ou nunca ter
sido executada nesta máquina (por exemplo, um `cancel_codex_task` que cancelou
uma tarefa ainda `queued`/`waiting_executor` nem chegou a ser despachada).
`CodexRunner.cancel` retorna `False` nesse caso, mas o pós-condição de um
cancel — "não está rodando aqui" — vale de qualquer forma, então
`task.cancelled` é enviado de volta incondicionalmente (issue #17 council,
"the claim auditor" / "the second caller"). Antes disso o agente só
respondia quando havia um processo de verdade para terminar, e o gateway
ficava esperando um `task.cancelled` que um runner reiniciado nunca ia
mandar — prendendo a vaga de concorrência do executor pelo resto do processo
do gateway.

O mesmo problema existia para `task.pause`/`task.resume`/`task.restart`: o
`task.ack` sempre foi enviado, mas com `accepted: false` tanto para "sei da
tarefa e recusei por um motivo real" quanto para "nunca ouvi falar dessa
tarefa" — o gateway não conseguia distinguir os dois casos. O payload do
`task.ack` agora inclui `known` (booleano, ausente = `true` para
compatibilidade com agentes antigos): quando `known` é `false`, o gateway
resolve a tarefa como `cancelled` e libera a vaga de concorrência, em vez de
reverter para o estado que o controle assumia (que pressupõe um processo
vivo em algum lugar, e não há nenhum).

## Operações de forge e o portão humano

Issue #80/#79, `WK-20260902-forge-wiring-and-gate` (PR B3). Uma operação de
forge (abrir/comentar/fechar/listar issue no GitHub via `gh`) não é uma
`task.dispatch`: ela roda fora do sandbox do provedor de codificação, como um
único processo `gh` limitado no próprio executor, e carrega uma credencial
(`GH_TOKEN`) que nunca entra no sandbox de uma sessão de codificação. Por
isso tem envelope próprio (`forge.operation`/`forge.operation_result`) em vez
de virar mais um modo de `task.dispatch` — os dois campos que
`_sandbox_for`/`RunnerPool` entendem (`mode`, `engine`) não descrevem nada
sobre uma operação de forge, e forçar um valor sentinela neles ensinaria
esses módulos a tratar um caso que não é deles.

Persistência é uma tabela própria no gateway, `forge_operations`
(`migrations/0012_forge_operations.sql`), **não** uma linha em `tasks`: as
colunas de `tasks` (`mode`, `instruction`, `engine`, `timeout_seconds`,
`session_id`, `delivery_json`) descrevem uma sessão de agente de código, e
`shared.policy.forge_operation_policy_level` é explícita que a classificação
`SENSITIVE` de uma escrita de forge não tem — e nunca deve ter — um campo de
bypass, ao contrário de `delivery_json`'s push (`push_is_preauthorized`).
Ver a docstring de `ForgeOperationModel`
(`gateway/app/models/entities.py`) e o corpo do commit desta PR para a
justificativa completa dessa decisão, incluindo por que ela não reusa a
superfície `/api/v1/decisions` da issue #6.

Ciclo de vida de uma linha `forge_operations.state`:

1. `awaiting_approval` — nasce assim toda ESCRITA (`issue_open`,
   `issue_comment`, `issue_close`): `forge_operation_policy_level` devolveu
   `SENSITIVE`. `issue_list` (leitura) nasce direto em `approved` — nunca
   passa pelo portão.
2. `approved` — um humano decidiu (`store.decide_forge_operation`, mesmo
   vocabulário `ApprovalDecision` da issue #6: `approved`/`rejected`/
   `revision_requested`), ou a operação era `issue_list`.
3. `dispatched` — `AgentHub.dispatch_forge_operation` enviou o envelope
   `forge.operation` para o executor. Esta função É o portão do lado do
   gateway: recusa (levanta `ValueError`) para qualquer estado que não seja
   `approved`, antes de tocar em `self.connections` ou enviar qualquer
   coisa — não existe caminho por onde um `forge.operation` sai do gateway
   para uma linha ainda `awaiting_approval`.
4. `completed`/`failed` — um `forge.operation_result` voltou
   (`gateway/app/main.py:handle_forge_operation_result`, que chama
   `store.resolve_forge_operation`).

Ou termina sem nunca despachar: `rejected`/`revision_requested`, uma decisão
humana negativa — este protocolo não tem mensagem que reabra uma operação de
forge para edição, a mesma lacuna que `routes/decisions.py` já documenta
para `TaskModel`.

O executor (`AgentService._handle_forge_operation`,
`agent/codex_bridge_agent/service.py`) **não** re-deriva
`forge_operation_policy_level` a partir do envelope, ao contrário do que
`_handle_dispatch` faz com `evaluate_task_policy` para uma task. A diferença
é deliberada: como a política de forge não tem campo de bypass, re-derivá-la
no executor recusaria toda escrita incondicionalmente, mesmo depois de uma
aprovação humana real — apagaria a funcionalidade em vez de defendê-la. O
executor confia que o gateway só manda `forge.operation` para uma linha
`approved`, e defende, de forma independente, só o que um gateway
comprometido ou com bug ainda poderia mentir: o projeto está na allowlist
local deste executor (a mesma resolução de `_handle_dispatch`, reaproveitada)
e a trava de máquina `allow_forge_operations` (default `False`) — as duas
travas são independentes; ambas precisam estar ligadas para `gh` rodar de
verdade.

Nesta PR (B3) o único jeito de criar/aprovar/despachar uma operação de forge
é chamando `store.create_forge_operation`/`store.decide_forge_operation`/
`AgentHub.dispatch_forge_operation` diretamente — não existe rota REST nem
ferramenta MCP ainda (por isso o contrato OpenAPI não muda nesta PR). Expor
isso para o operador via ChatGPT é B4.

## Binding de forge, `gh:N` e as ferramentas MCP (B4)

WK-20260902-forge-binding, issue #79/#80 (PR B4). B3 (acima) deixou a
operação de forge com portão humano mas sem superfície: nenhuma rota REST,
nenhuma ferramenta MCP, `gh:N` sempre recusado. Esta PR fecha os três.

### `project_forge_binding` — o único ponto que decide "ligado" ou não

`gateway/app/services/forge_routing.py`'s `project_forge_binding(session,
project_id) -> ForgeBinding | None` lê `scm_associations` (migration `0009`,
vazia e sem código até esta PR) e é a única função que qualquer chamador —
as ferramentas MCP abaixo, `AgentHub.dispatch_next` para `gh:N` — deveria
consultar para essa pergunta. `None` significa "roteie para as tabelas
locais", não um erro.

O `confidence` da associação começa `declared` (um operador nomeou o
repositório via `bind_project_forge`) e só vira `confirmed` por um
`confirm=true` explícito, na mesma chamada — nunca automaticamente. Ver
`ScmAssociationModel`'s docstring (`gateway/app/models/entities.py`) para a
razão completa.

### O executor confirma o remote real antes de qualquer operação

`agent/codex_bridge_agent/forge/github.py`'s `_confirm_repo_identity_live`
roda `git remote get-url origin` (via `git_tools.run_git`) antes de CADA
operação de forge — leitura ou escrita, `issue_list`/`issue_view` incluídos
— e recusa `repo_identity_mismatch` se o remote real divergir do
`repo_identity` que o gateway declarou no envelope. Sempre ao vivo, nunca
cacheada: uma chamada `git` local não custa rede nenhuma, e elimina a
necessidade de um job de reconciliação para o caso "a pasta perdeu ou
trocou o remote depois que o binding foi declarado".

### `gh:N` deixa de ser recusado incondicionalmente

Novo quinto membro em `ForgeOperationKind`: `ISSUE_VIEW` (`gh issue view
--json title,body`), classificado `READ` como `ISSUE_LIST` —
`shared.policy.forge_operation_policy_level` nunca gate nenhum dos dois.

Fluxo para um `issue_ref` no formato `gh:N`:

1. Na criação da task (`gateway/app/mcp/server.py:start_development_task`),
   `gh:N` não é mais recusado incondicionalmente — só quando
   `project_forge_binding(project_id)` devolve `None`. Ligado, segue para
   dispatch como qualquer outro `issue_ref`, sem tentar resolver o conteúdo
   no gateway (o gateway nunca aprende o path real do projeto,
   `docs/architecture.md`).
2. No dispatch (`AgentHub.dispatch_next`), se `task.issue_ref` começa com
   `"gh:"`, o binding é resolvido e `repo_identity` viaja no payload como
   `forge_repo_identity` — só computado para esse formato, para não pagar
   uma consulta extra em todo dispatch normal.
3. No executor (`AgentService._handle_dispatch`), sem `forge_repo_identity`
   no envelope, a recusa é `issue_source_unsupported`, byte a byte igual à
   de antes desta PR. Com ele, o executor monta um `ForgeOperationRequest`
   `ISSUE_VIEW` e chama `run_forge_operation` — a mesma trava
   `allow_forge_operations`, a mesma confirmação de remote ao vivo, o mesmo
   módulo `forge/github.py` que qualquer outra operação usa.

**Invariante inegociável, testado diretamente**
(`tests/unit/test_agent_service.py::test_gh_issue_body_never_reaches_policy_evaluation`):
o texto devolvido por `gh issue view` só alcança
`instructions.build_task_instruction`'s `issue_text`, dentro do bloco
`--- BEGIN UNTRUSTED ISSUE CONTENT ---` — nunca `SubmitTaskRequest.instruction`
nem `evaluate_task_policy`, que só vê as próprias palavras do operador,
montadas pelo gateway antes de `_handle_dispatch` rodar. Issue de repositório
público é gravável por qualquer um; deixar seu texto influenciar a
classificação de política deixaria um estranho forçar (ou evitar) o portão
de aprovação sensível de uma tarefa deste operador.

### As ferramentas MCP de forge — roteamento é um `if`, não uma escolha do operador

Cinco ferramentas novas em `gateway/app/mcp/server.py`/`tools.py`:

* `bind_project_forge` (escopo `codexbridge.admin`) — declara/confirma a
  associação. É o que liga o roteamento das outras quatro.
* `create_project_issue`, `list_project_issues`, `comment_project_issue`,
  `close_project_issue` — cada uma faz `binding = await
  project_forge_binding(session, project.id)`; `binding is not None` roteia
  para uma operação de forge (`store.create_forge_operation`, mesmo portão
  de toda escrita de forge); `None` roteia para as tabelas locais deste
  gateway (issue #8: `store.create_issue`/`list_issues_page`/`update_issue`).
  O operador chama a mesma ferramenta, com os mesmos argumentos, nos dois
  casos — nunca precisa dizer em qual projeto está.

`comment_project_issue` não tem equivalente local (este gateway não modela
comentário em issue local) e devolve `forge_binding_required` quando o
projeto não está ligado — uma recusa tipada honesta, não uma tentativa de
forçar o conceito onde ele não existe.

Uma leitura de forge (`list_project_issues` ligado) é despachada na mesma
chamada — `hub.dispatch_forge_operation`, o mesmo "nunca no-op silencioso"
que `dispatch_available` já tem para uma task, mas nunca espera decisão
humana (`issue_list` nasce `approved`). Uma escrita de forge de qualquer
uma dessas ferramentas nunca é despachada pela própria ferramenta — nasce
`awaiting_approval` e espera na Central de Decisões, como toda escrita de
forge desde B3.

### A Central de Decisões projeta as duas fontes

`gateway/app/api/routes/decisions.py`'s módulo docstring e
`docs/api/README.md`'s seção "Decisions" têm o desenho completo: uma decisão
de forge tem `id` prefixado (`forge:<uuid>`, nunca colide com um `TaskModel.id`
por construção), `decisionType: "forge_operation"`, e aprovar despacha via
`AgentHub.dispatch_forge_operation` — o mesmo par
`decide_task_approval`/`dispatch_available` que a issue #20 corrigiu para
task, aplicado à tabela de forge para que o mesmo bug não aconteça de novo
num lugar diferente.
