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

São 11 ferramentas. `approve_codex_task` é a que libera tarefa parada em
`awaiting_approval` pela política de sensibilidade, e exige principal com escopo
`codexbridge.task.approve` ou `can_approve_sensitive`.

## Canal reverso do agente

Endpoint: `wss://codexbridge.inovacaosistemas.com.br:8443/agent/ws?executor_id=<ID>&token=...`

Mensagens (`AgentMessageType` em `shared/protocol.py`):

* `hello`
* `hello_ack`
* `heartbeat`
* `task.dispatch`
* `task.ack`
* `task.log`
* `task.result`
* `task.cancel`
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

