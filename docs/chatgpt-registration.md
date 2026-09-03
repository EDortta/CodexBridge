# Registrar no ChatGPT

Confirmado com documentação oficial consultada em `2026-07-28`:

* o ChatGPT Developer mode aceita apps criados a partir de MCP remoto;
* a URL pública deve incluir o endpoint MCP, por exemplo `https://codexbridge.inovacaosistemas.com.br:8443/mcp`;
* para este projeto, o modo correto é `OAuth`.

## Passos

1. No ChatGPT web, abrir `Settings -> Security and login`.
2. Ativar `Developer mode`.
3. Abrir `ChatGPT Plugins`.
4. Criar um app em modo desenvolvedor apontando para `https://codexbridge.inovacaosistemas.com.br:8443/mcp`.
5. Escolher `OAuth` como autenticação.
6. Concluir o login na tela do `gateway`.
7. Revisar ferramentas descobertas.
8. Em nova conversa, habilitar o app na composição.

## Iniciar trabalho por conversa

Depois de habilitado, `"resolva a issue 57 do projeto jk-structure com o
claude, branch feature/uc-57, pode dar push"` já é suficiente: o modelo chama
`start_development_task` com `project`, `issue`, `engine`, `branch` e
`allow_push` inferidos da frase. Ele resolve o projeto (id, nome ou prefixo
único), escolhe o executor sozinho quando não indicado, e devolve `task_id`
mais uma estimativa de duração baseada no histórico real
(`eta_seconds`/`eta_basis`).

## Acompanhar conclusão por polling (metade do aviso de conclusão)

O gateway **não empurra nada para dentro do ChatGPT** — não há canal de push
de um servidor MCP para o app. Duas formas de saber que uma tarefa terminou:

1. **Perguntar na mesma conversa**: `get_task_status` com o `task_id`
   devolvido — ganhou os campos `engine`, `issue_ref`, `delivery` e
   `delivery_result` (branch, commit, push sim/não), além de
   `eta_seconds`/`eta_basis`/`eta_sample_size` (WK-20260903-gh67-70-read-gaps),
   além dos já existentes.
2. **Uma ChatGPT Task agendada** que faz a mesma pergunta periodicamente sem o
   operador precisar abrir a conversa — receita completa abaixo.

### Configurando a ChatGPT Task agendada

`list_recent_tasks` aceita `states` (issue #70) exatamente para este caso:
"o que terminou desde a última vez que perguntei" vira uma chamada só, em vez
de listar tudo e filtrar na conversa. Desde WK-20260903-gh67-70-read-gaps cada
item devolvido também carrega `issue_ref`, `delivery` (`branch`, `commit`,
`pushed`, `outcome`, `reason` — `null` quando a tarefa não teve entrega) e
`eta_seconds`/`eta_basis`/`eta_sample_size` — os mesmos campos que
`start_development_task` já devolvia na submissão, agora também no polling.

1. Com o app do CodexBridge já habilitado (ver `## Passos` acima), numa
   conversa nova pedir diretamente em linguagem natural, por exemplo: *"a
   cada 15 minutos, chame `list_recent_tasks` com
   `states: ["completed", "failed", "cancelled", "expired", "lost"]` e
   `limit: 50`; para cada tarefa que ainda não apareceu numa execução
   anterior, me avise citando `task_id`, `project_id`, `engine`, `state`,
   `issue_ref` e, quando presente, `delivery.branch`/`delivery.pushed`/`delivery.outcome`"*.
   O ChatGPT reconhece o pedido recorrente e propõe o agendamento para
   confirmação — confirmando, a Task fica salva. (Alternativa equivalente:
   abrir `Scheduled` na barra lateral e criar a Task por lá.)
   Os cinco estados acima são exatamente os terminais que `notify.py`
   (abaixo) também cobre por e-mail; um subconjunto menor
   (`["completed", "failed"]`, como no exemplo mínimo da seção acima)
   também é válido se o operador só quer saber dos dois desfechos mais
   comuns.
2. Gerenciar Tasks já criadas (pausar, editar, apagar): `Settings ->
   Notifications -> Manage tasks`, ou "..." numa conversa que tenha uma Task
   ativa -> `See scheduled tasks`.
3. A Task roda no relógio do ChatGPT, não no gateway (finding F12 do
   concílio: não existe scheduler no lado do CodexBridge para isto) — cada
   execução é uma chamada MCP nova, autenticada com a mesma sessão OAuth do
   app.
4. "Desde a última execução" fica por conta do próprio texto da Task (passo
   1) comparando com o que ela relatou da vez anterior — `list_recent_tasks`
   não guarda um cursor de leitura por chamador, só ordena por
   `created_at desc` e filtra por `states`.

O e-mail de conclusão (a outra metade — funciona com o app fechado) já está
implementado (`gateway/app/services/notify.py`, issue #70): quando uma
tarefa chega a um estado terminal, o gateway manda um e-mail com identidade
visual própria (`gateway/app/services/email_templates.py`) para o
destinatário fixo em `CODEX_BRIDGE_NOTIFICATION_TO`. Fica desligado por
padrão — exige `CODEX_BRIDGE_NOTIFICATION_EMAIL_CONFIG_FILE` **e**
`CODEX_BRIDGE_NOTIFICATION_TO` configurados no `frida`; sem os dois, é um
no-op silencioso, nunca um erro. Cobre `TASK_RESULT` (concluída/falhou),
`task.cancelled` e o cancelamento por reconexão órfã (issue #17) — só a
varredura de recuperação no startup (`recover_tasks_after_startup`, que
resolve tarefas expiradas ou perdidas após uma queda do gateway) ainda não
dispara e-mail, um resíduo declarado do finding F27 do concílio. Ver
`docs/threat-model.md` e o work item
`WK-20260830-chatgpt-entry-provider-and-delivery`.

## Próximo documento

Para rollout multiusuário com OAuth, ver [chatgpt-oauth-rollout.md](./chatgpt-oauth-rollout.md).
