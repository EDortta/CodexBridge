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
   `delivery_result` (branch, commit, push sim/não), além dos já existentes.
2. **Uma ChatGPT Task agendada**: criar uma tarefa agendada (ex: a cada 15
   min) pedindo para chamar `list_recent_tasks` com
   `states: ["completed", "failed"]` e comparar com a última checagem — é
   exatamente o filtro que torna "o que terminou desde que perguntei" uma
   chamada só, em vez de listar tudo e filtrar na conversa.

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
