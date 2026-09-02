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

A forma antiga `?token=...` **foi removida** (a release de compatibilidade que
#15 concedeu já passou). Token só na URL agora é o mesmo que token nenhum: o
handshake fecha com `4401`, antes de qualquer consulta ao registro. Um executor
que ainda mande o parâmetro precisa ser atualizado — o agente envia o header
desde a mesma release (`agent/codex_bridge_agent/service.py`).

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

### Payload do `hello`: `NodeAnnouncement`

Até a Stage 2 da #73 o `hello` levava `{"version": "0.1.0"}` e o gateway **não
tinha branch para ele** — a mensagem era persistida como recibo e descartada.
Agora ela carrega um `NodeAnnouncement` (`shared/protocol.py`):

```json
{
  "agent_version": "0.1.0",
  "os": "Linux",
  "arch": "x86_64",
  "engines": [
    {"engine": "codex",  "implemented": true,  "available": true,  "version": "codex-cli 1.4.2"},
    {"engine": "claude", "implemented": true,  "available": false, "detail": "not found on PATH"},
    {"engine": "gemini", "implemented": false, "available": false, "detail": "no runner implemented"}
  ],
  "capabilities": ["read", "test"],
  "max_concurrent_tasks": 1,
  "discovery_root_count": 1
}
```

Sem `node_id`: o nó é aquele para o qual o `executor_id` autenticado aponta. Sem
caminho: `discovery_root_count` é contagem, não as raízes. `capabilities` é o que
a configuração da máquina permitiria, nunca uma concessão sobre projeto — ver
`docs/control-plane.md`.

**Compatibilidade:** um agente de release anterior segue enviando `{"version":
...}`. O gateway lê essa forma como `agent_version` e um payload que não valide
gera `WARNING` e **não derruba a conexão** — um gateway que desliga o agente da
release anterior transforma deploy em interrupção.


Campos comuns:

* `message_id`
* `executor_id`
* `sent_at`
* `type`
* `payload`

## Identidade: o handshake manda, o envelope não

`AgentEnvelope.executor_id` é campo que o **cliente escreve** no corpo da
mensagem; o `executor_id` do `/agent/ws` é o que apresentou token de máquina no
handshake. O laço de recepção compara os dois **antes** de despachar e descarta
o envelope quando divergem, com `WARNING`.

A verificação vive num ponto só, e não em cada branch, por histórico: a #16 já
tinha corrigido isso para `task.ack` isoladamente, e todo tipo de mensagem
acrescentado depois herdou a confiança de novo. Sem a guarda, um nó autenticado
podia anunciar-se **como outro** — forjando as capacidades relatadas de uma
máquina alheia, ou renovando a liveness dela para que um nó morto aparecesse
saudável, que é exatamente a superfície de frota que a Stage 2 existe para
tornar confiável.

Descartar, não redirecionar: reescrever o id reivindicado para o autenticado
aceitaria em silêncio, como declaração do remetente, uma mensagem que ele não
fez sobre si. E descartar não derruba a conexão — derrubar transformaria um
agente com bug em interrupção, e daria a um atacante um jeito de desconectar
um nó.

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
