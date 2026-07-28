# Operação

## Verificações básicas

* `curl -H "Authorization: Bearer ... " https://frida.inovacaosistemas.com.br:8443/healthz`
* `systemctl status codex-bridge-gateway`
* `systemctl status codex-bridge-agent`

## Fluxo operacional

1. Confirmar `list_executors`.
2. Confirmar `list_projects`.
3. Enviar `submit_codex_task`.
4. Acompanhar com `get_task_status` e `get_task_logs`.
5. Coletar `get_task_result`.

## Quando o T610 estiver offline

* tarefas com `run_when_available=false` falham na submissão;
* tarefas com `run_when_available=true` ficam em `waiting_executor`;
* `cancel_codex_task` pode cancelar antes da execução;
* no retorno do agente, o gateway reavalia e redispara a próxima tarefa elegível.

