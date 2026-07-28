# Operação

## Verificações básicas

* `curl -sk https://codexbridge.inovacaosistemas.com.br:8443/healthz`
* `curl -sk https://codexbridge.inovacaosistemas.com.br:8443/.well-known/oauth-authorization-server`
* `systemctl status codex-bridge-gateway`
* `systemctl status codex-bridge-agent`

## Fluxo operacional

1. Confirmar `list_executors`.
2. Confirmar `list_projects`.
3. Enviar `submit_codex_task`.
4. Acompanhar com `get_task_status` e `get_task_logs`.
5. Coletar `get_task_result`.

## Quando o executor estiver offline

* tarefas com `run_when_available=false` falham na submissão;
* tarefas com `run_when_available=true` ficam em `waiting_executor`;
* `cancel_codex_task` pode cancelar antes da execução;
* no retorno do agente, o gateway reavalia e redispara a próxima tarefa elegível.

## Ambiente atual levantado em 2026-07-28

* `frida` responde por `ssh -p 2200 esteban@frida.inovacaosistemas.com.br`
* a ponte reversa documentada fica em `/home/esteban/scripts/reverse-tunnel.sh`
* `mosquitto` já ocupa `*:8080` no `frida`
* `devel3` é o executor correto quando a tarefa precisa dos repositórios locais
