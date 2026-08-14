# Segurança

## Controles implementados no MVP

* MCP sem ferramenta genérica de shell.
* `project_id` obrigatório; nenhum path vindo do ChatGPT.
* allowlist dupla de executores e projetos.
* resolução por `realpath` no agente.
* `codex exec` e `git` chamados sem shell.
* logs sanitizados.
* tarefas sensíveis desviadas para `awaiting_approval`.
* fila persistente com auditoria append-only.
* WebSocket reverso iniciado pelo executor.
* `systemd` com endurecimento e usuário sem privilégio.
* token de máquina do executor apresentado no header `X-Executor-Token` no
  handshake de `/agent/ws`, e não mais na query string (#15). Credencial em query
  string vira linha de log em todo componente do caminho — journal do gateway,
  `access.log` do nginx (`-rw-r----- www-data adm`), rotacionados, backup e
  pipeline de observabilidade. A forma antiga segue aceita por uma release, com
  `WARNING` de depreciação que **não** imprime o valor; o header vence quando os
  dois estão presentes. Resolução em `gateway/app/core/agent_auth.py`.
* rate limiting por IP em `POST /mcp` (`MemoryRateLimiter`, `gateway/app/main.py`),
  padrão de 120 requisições por janela de 60 segundos, resposta `429` e métrica
  `RATE_LIMIT_REJECTIONS`.
* ciclo de sessão do CodexBridgeMobile (issue #4, `/api/v1/auth/*`): sign-in por
  senha, renovação com **rotação** do refresh token e revogação imediata.
  Detalhes em `docs/api/README.md`; os pontos de segurança:
  - revogação vale para os dois transportes. `store.get_oauth_access_token`
    recusa token expirado **ou revogado**, e é por ele que `/mcp` autentica —
    revogar do celular derruba também o acesso do ChatGPT;
  - refresh é de uso único. Reapresentar um já consumido revoga a concessão
    inteira: replay e roubo são indistinguíveis do lado do servidor, e a leitura
    segura da ambiguidade é roubo;
  - a rotação **não** estende o prazo do refresh. A concessão tem vida absoluta
    (`CODEX_BRIDGE_OAUTH_REFRESH_TOKEN_TTL_SECONDS`, 30 dias por padrão);
  - cada renovação relê `users.json` e faz interseção de escopos, nunca união.
    Conta desabilitada encerra a concessão na próxima renovação, não no próximo
    vencimento;
  - `/api/v1/auth/sign-in` **tem** rate limiting (é rota `/api`, com o
    limitador do router). `POST /oauth/authorize` também passou a ter, declarado
    na própria rota: era o único endpoint de senha sem teto de tentativas, e
    fechar o oráculo de tempo tornou cada tentativa ~190x mais cara de servir.
    O `GET` que renderiza o formulário segue sem limite — não toca credencial;
  - as duas rotas de senha derivam a chave **fora do event loop**
    (`users.authenticate_async`). São centenas de milissegundos de PBKDF2 sem
    nenhum `await`: chamada direta de um `async def`, ela segura o processo
    inteiro — dez tentativas concorrentes levaram `GET /health` de 0,8 ms a
    3,3 s, e um probe de liveness que estoura reinicia um gateway que está
    apenas sendo sondado por contas;
  - usuário inexistente paga a mesma derivação PBKDF2 de um real, para não
    virar oráculo de enumeração por tempo de resposta. O custo é lido **do
    próprio `users.json`**, não de uma constante: com uma constante de 600 000
    sobre um registro gerado a 210 000, a conta real respondia em ~107 ms e a
    inexistente em ~307 ms — o oráculo invertido, não fechado. Um registro com
    **custos mistos** (contas antigas a 210 000, novas a 600 000) tinha o mesmo
    defeito ao contrário: a conta barata respondia em 105 ms contra 301 ms da
    inventada, identificando exatamente quem existe. A verificação real agora é
    **completada até o custo máximo do registro**, então toda tentativa custa o
    mesmo. Vale para os dois chamadores: `gateway/app/main.py` usa
    `users.authenticate`, a mesma operação do sign-in (antes: 1,6 ms para
    usuário inexistente contra 299 ms para real, 185x);
  - todo 401 desta superfície é idêntico (ausente, desconhecido, expirado,
    revogado, **ou de conta desabilitada**) e o registro de auditoria nunca
    guarda credencial, nem o texto que o chamador digitou, nem e-mail — só o
    `user_id` opaco, que já é o `entity_id` da linha;
  - **nenhuma tabela de credencial guarda e-mail.** `oauth_access_tokens`,
    `oauth_refresh_tokens` e `oauth_authorization_codes` perderam a coluna
    `user_email` (`migrations/0004_drop_user_email.sql`): toda linha já carrega
    o `user_id`, que é a chave do `users.json`. `security-standards.md` §2 cita
    e-mail nominalmente e proíbe PII em claro em diretório sincronizado — e o
    `CODEX_BRIDGE_DATABASE_URL` padrão é um SQLite dentro deste checkout, que
    fica sob `~/Sync`. `gateway/app/db/schema_guard.py` recusa subir contra um
    banco que ainda tenha a coluna, para que a falha apareça no boot e não como
    erro de integridade no primeiro sign-in;
  - **gateway sem `users.json` reclama no startup.** O padrão de
    `CODEX_BRIDGE_USER_REGISTRY_FILE` é `/etc/codex-bridge/users.json`, e uma
    instalação que nunca configurou nada sobe limpa e recusa toda credencial com
    a mesma mensagem opaca que um atacante recebe. Não é *fail-fast* (com
    `mcp_auth_mode=bearer` o registro nem é lido, e recusar o boot derrubaria um
    deployment correto), mas o log de erro nomeia o arquivo e a variável;
  - conta desabilitada responde **401, não 403**. A credencial está morta e a
    única recuperação é apresentar outra, que é o que 401 significa; com 403 o
    cliente mostrava erro de permissão e mantinha a sessão morta. Em `/api/v1`,
    `403` vem de `require_action` e de mais nada;
  - o token do sign-in carrega os escopos da conta **interseccionados com
    `CODEX_BRIDGE_OAUTH_DEFAULT_SCOPES`**, o mesmo teto do fluxo do navegador.
    As duas emissões escrevem na mesma tabela que `/mcp` autentica: um segundo
    emissor sem teto é teto nenhum;
  - `audit_events` tem retenção (`CODEX_BRIDGE_AUDIT_EVENT_RETENTION_DAYS`,
    90 dias por padrão), varrida no startup como os registros de idempotência.
    Sign-in recusado é o primeiro caminho de escrita **não autenticado** nessa
    tabela e nada removia linha nenhuma antes disso. A varredura só apaga linhas
    de `entity_type = "auth"`: a janela existe para limitar spam de sign-in, e
    aplicá-la à tabela inteira apagaria `task.approved` — o registro de quem
    autorizou uma tarefa sensível — junto. Se aquele registro pode envelhecer em
    90 dias é decisão do operador sobre a própria conformidade, não herança de
    um controle de spam.

### Risco aceito: refresh token gasto ainda encerra a própria concessão

* **Superfície:** `POST /api/v1/auth/revoke`, sem autenticação, com
  `{"refreshToken": "<token já consumido, revogado ou expirado>"}`.
* **Caminho de abuso:** quem recuperar qualquer refresh token já emitido sob uma
  concessão viva — de um backup de aparelho, de um dump, de log antigo de
  cliente — força uma reautenticação do operador. A rotação carrega o `grant_id`
  adiante, então um token do dia 1 ainda endereça a concessão no dia 29.
* **Mitigação / por que fica assim:** é a direção *fail-closed*
  (`design-standards.md` §6). O contrário — recusar agir sobre um token gasto —
  faz o sign-out de um cliente relatar sucesso com a sessão viva, que é
  exatamente a falha que este endpoint existe para impedir. Além disso
  `/refresh` já lê reapresentação como roubo; ler o mesmo token como inofensivo
  aqui faria os dois endpoints discordarem sobre a mesma credencial.
* **Risco residual:** negação de serviço limitada — uma reautenticação forçada
  por concessão capturada. Nada é lido, nada é emitido, e um novo sign-in gera
  um `grant_id` novo que o token antigo não endereça. Fixado por
  `tests/integration/test_auth.py::test_a_consumed_refresh_token_still_ends_its_own_grant`,
  que é o que precisa mudar se a decisão mudar.

## Lacunas assumidas para endurecimento

* **O token de máquina já exposto continua válido, e os logs antigos continuam
  no disco.** Tirar a credencial da URL impede exposição nova; não desfaz a
  antiga. Rotacionar o token no `registry.json` e purgar ou rotacionar os logs
  que já o contêm são ações do operador, e a issue #15 as coloca explicitamente
  fora do escopo do código. Enquanto não acontecerem, qualquer membro do grupo
  `adm` no host do gateway — e qualquer backup daqueles logs — tem uma credencial
  de executor funcionando.
* **A forma com query string ainda autentica.** É deliberado, para permitir
  publicar gateway e agente em momentos diferentes, mas significa que o caminho
  vulnerável continua aberto até ser removido na release seguinte. O `WARNING` de
  depreciação existe para que ninguém esqueça que ele está lá.

* **`POST /oauth/token` não tem rate limiting.** `POST /oauth/authorize` passou a
  ter (mesmo limitador, mesmo balde por endereço), porque era o único endpoint de
  senha sem teto e porque fechar o oráculo de tempo lá dentro encareceu cada
  tentativa não autenticada em ~190x — de ~3 ms para ~300 ms de CPU. Essa troca
  não estava registrada em lugar nenhum e é o que decidia a urgência do teto.
  `POST /oauth/token` não recebe senha (troca um código de autorização com PKCE),
  então a exposição restante é menor, mas segue sem teto.
* **O limitador de `/oauth/authorize` não protege contra origens distribuídas.**
  O balde é o endereço do chamador, então 120 tentativas por minuto **por
  endereço** continuam custando ~36 s de CPU por minuto por origem. A derivação
  roda fora do event loop, então isso não para o processo; satura núcleo. Um
  bloqueio por conta após N falhas seria o próximo passo e não está feito.
* **`users.json` não tem gerador.** `docs/installation.md` manda trocar a senha
  inicial e agora traz o comando; nada verifica, em produção, que o hash
  resultante usa o custo esperado. O engodo acompanha o registro e a verificação
  real é completada até o custo máximo dele, então um custo menor não abre
  oráculo nem no registro misto — só torna aquela senha mais barata de quebrar
  offline, e faz toda tentativa custar o do hash mais caro do arquivo.
* **A varredura de `audit_events` acontece no startup**, como a de idempotência:
  não há agendador neste deployment. Um gateway que fica meses de pé não coleta
  nada nesse período. O teto continua sendo o limitador (120/min/bucket).
* o limitador é em memória por processo: não sobrevive a restart e não é
  compartilhado entre réplicas.
* rotação de tokens existe apenas para as concessões do
  `/api/v1/auth/*` (issue #4). Os tokens emitidos pelo fluxo OAuth do navegador
  não têm refresh e continuam válidos até expirar — revogáveis um a um, não em
  cadeia. Os tokens estáticos de `mcp_auth_mode=bearer` não têm rotação alguma.
* cgroups finos por subprocesso do `codex exec` ainda dependem do host do agente.
* `sensitive_patterns` por projeto está no schema mas não é aplicado em lugar
  nenhum; a classificação de tarefa sensível usa apenas a lista global
  `SENSITIVE_KEYWORDS` em `shared/policy.py`. Ver `docs/project-onboarding.md`.

## Recomendações de produção

* usar PostgreSQL real com backup e retenção;
* mover tokens para `EnvironmentFile` root-only;
* colocar o gateway atrás de `nginx` com TLS válido;
* executar o agente em conta dedicada `codexbridge`;
* limitar os diretórios liberados em `ReadWritePaths`;
* manter o modo bearer apenas para compatibilidade administrativa;
* operar o uso humano do ChatGPT exclusivamente via OAuth.
