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
* `list_recent_tasks`

## Canal reverso do agente

Endpoint: `wss://frida.inovacaosistemas.com.br:8443/agent/ws?executor_id=T610&token=...`

Mensagens:

* `hello`
* `hello_ack`
* `heartbeat`
* `task.dispatch`
* `task.log`
* `task.result`
* `task.cancel`
* `task.cancelled`

Campos comuns:

* `message_id`
* `executor_id`
* `sent_at`
* `type`
* `payload`

## Idempotência

O gateway persiste `message_id` em `message_receipts`. Mensagens repetidas do agente são descartadas.

