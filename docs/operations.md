# Operação

## Verificações básicas

* `curl -sk https://codexbridge.inovacaosistemas.com.br:8443/health` — o processo
  está de pé. **Não toca em dependência nenhuma**, então continua `ok` com o banco
  fora do ar; serve para dizer "reiniciar não ajuda", nunca "está tudo bem".
* `curl -sk https://codexbridge.inovacaosistemas.com.br:8443/ready` — consegue
  servir. `200` com `status: ready`, `503` com o envelope de erro e o array
  `checks` nomeando a dependência que caiu. **É este que responde "o banco está
  vivo?"**, e é o que faltava: o `/healthz` abaixo, por desenho, devolve 200
  durante uma queda total do banco.
* `curl -sk https://codexbridge.inovacaosistemas.com.br:8443/api/version` — que
  versão de contrato e quais capacidades este build serve.
* `curl -sk https://codexbridge.inovacaosistemas.com.br:8443/healthz` — probe de
  infraestrutura pré-existente, mantido para os checks já apontados para ele.
* `curl -sk https://codexbridge.inovacaosistemas.com.br:8443/.well-known/oauth-authorization-server`
* `systemctl status codex-bridge-gateway`
* `systemctl status codex-bridge-agent`

## Gateway não sobe depois de atualizar

Se o log traz `SchemaOutOfDate`, o banco está atrás do código e o startup
recusou servir de propósito. Rode as migrations (`docs/installation.md`, passo 9)
e suba de novo. Como a unit tem `Restart=always`, o sintoma é reinício a cada 5
segundos, não uma falha única.

**Subir limpo não prova que as migrations rodaram.** `SchemaOutOfDate` só é
levantado por coluna faltando (`REQUIRED_COLUMNS`) ou coluna proibida presente
(`FORBIDDEN_COLUMNS`). Migration que só cria **tabela** — 0006, 0007, 0008 —
passa em silêncio: o `create_all` roda antes do `check_schema` e cria a tabela,
e o gateway serve sem os índices e defaults do `.sql` e sem linha em
`schema_migrations`. Depois de qualquer atualização, confira
`select filename from schema_migrations order by filename;` contra `ls migrations/`.

## Download de artefato responde 404 para tudo

Sintoma: `GET /api/v1/artifacts` lista normalmente, o mint devolve `201`, e todo
`GET /api/v1/artifacts/{id}/download` responde `404 not_found` com
`The stored content for this artifact is not available.` — sem citar caminho
nenhum, de propósito.

Quase sempre é `CODEX_BRIDGE_ARTIFACTS_ROOT` não definido ou apontando para
outro lugar que não onde os bytes foram escritos. `.env.example` traz a linha
comentada, e o padrão resolve contra o diretório de trabalho do processo
(`/opt/codex-bridge` na unit), não contra o checkout. Confirme no log do gateway:
a recusa emite `artifact_content_unavailable` com `artifact_id`, `reason`
(`no_regular_file` ou `escapes_root`) e o mesmo `correlation_id` que o cliente
viu como `requestId`.

`escapes_root` é outra coisa: o caminho guardado deixou de resolver dentro da
raiz — symlink, ou a raiz mudou de lugar. Nesse caso não mexa na raiz sem olhar
o que o symlink aponta.

## Fluxo operacional

1. Confirmar `list_executors`.
2. Confirmar `list_projects`.
3. Enviar `submit_codex_task`.
4. Acompanhar com `get_task_status` e `get_task_logs`.
5. Coletar `get_task_result`.

## Quando o executor estiver offline

* tarefas com `run_when_available=false` falham na submissão;
* tarefas com `run_when_available=true` ficam em `waiting_executor`;
* `cancel_codex_task` cancela em qualquer estado cancelável (fila, aprovação pendente, execução, pausa/retomada/reinício pendentes), marcando a tarefa `cancelled` de imediato; o `task.cancel` só é entregue ao agente na hora se ele estiver conectado, senão é reenviado na reconexão — limitado a `cancel_replay_max_age_seconds` (padrão 24h) desde o cancelamento; passado esse prazo não há novo reenvio;
* no retorno do agente, o gateway reavalia e redispara a próxima tarefa elegível.

## Ambiente atual levantado em 2026-07-28

* `frida` responde por `ssh -p 2200 esteban@frida.inovacaosistemas.com.br`
* a ponte reversa documentada fica em `/home/esteban/scripts/reverse-tunnel.sh`
* `mosquitto` já ocupa `*:8080` no `frida`
* `devel3` é o executor correto quando a tarefa precisa dos repositórios locais
