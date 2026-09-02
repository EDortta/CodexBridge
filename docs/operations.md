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

## CodexBridge Control (issue #73 Stage 5)

Três telas server-rendered: `GET /control` (frota), `GET
/control/nodes/{nodeId}` (detalhe: capacidades/engines, candidatos
descobertos, autorizações) e `GET /control/invite` (hoje só explica por que
não funciona ainda — não há `POST /api/v1/nodes/invite` nem
`scripts/enroll_node.py` neste build; ver `docs/control-plane.md`, seção
"Stage 5"). Servidas pelo próprio processo do gateway, sem deployable novo.

**Ação do operador — nginx.** O vhost `deploy/nginx/frida-codex-bridge.conf`
é uma allowlist de `location`s sem catch-all: sem a entrada `/control`, o
painel simplesmente não responde (404 na borda), mesmo funcionando na
aplicação. O bloco já está no arquivo versionado do repositório desde esta
PR; falta **aplicá-lo em produção** — copiar o trecho abaixo (ou o arquivo
inteiro) para o nginx do `frida` e recarregar:

```nginx
location = /control {
    proxy_pass http://127.0.0.1:18080/control;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
}

location /control/ {
    proxy_pass http://127.0.0.1:18080/control/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
}
```

Depois de copiar: `nginx -t` e `systemctl reload nginx` (ou equivalente) no
`frida`. Nenhum passo deste trabalho aplica isso automaticamente — deploy
autônomo é proibido neste projeto; aplicar em produção é sempre ação humana.

**Credenciais.** Não é um mecanismo novo: o painel pede usuário/senha via o
diálogo nativo de HTTP Basic do próprio browser, verificados contra o mesmo
`users.json` que `/oauth/authorize` já usa. Qualquer conta com o escopo
`codexbridge.admin` (`GET /api/v1/auth/me` confirma) enxerga a frota;
conceder `modify`/`deliver` a um nó, na tela de detalhe, exige além disso
`can_approve_sensitive` ou o papel `admin` — a mesma escada de privilégio da
Stage 4 (`docs/control-plane.md`). Nenhuma conta nova precisa ser criada só
para o painel.

**Nada de migração.** Esta PR não adiciona schema; usa exatamente as tabelas
que a Stage 1-4 já criaram.

## Ambiente atual levantado em 2026-07-28

* `frida` responde por `ssh -p 2200 esteban@frida.inovacaosistemas.com.br`
* a ponte reversa documentada fica em `/home/esteban/scripts/reverse-tunnel.sh`
* `mosquitto` já ocupa `*:8080` no `frida`
* `devel3` é o executor correto quando a tarefa precisa dos repositórios locais
