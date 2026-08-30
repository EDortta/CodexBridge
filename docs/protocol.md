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

São 12 ferramentas. `approve_codex_task` é a que libera tarefa parada em
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
