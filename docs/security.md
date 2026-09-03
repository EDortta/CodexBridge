# Segurança

## Controles implementados no MVP

* MCP sem ferramenta genérica de shell.
* `project_id` obrigatório; nenhum path vindo do ChatGPT.
* allowlist dupla de executores e projetos.
* resolução por `realpath` no agente.
* `codex exec` e `git` chamados sem shell.
* logs sanitizados.
* tarefas sensíveis desviadas para `awaiting_approval`.
* entrega com commit e push pré-autorizados (issue #66,
  WK-20260830-chatgpt-entry-provider-and-delivery): `SENSITIVE_KEYWORDS`
  (`shared/policy.py`) não foi alterada nem enfraquecida — a lista fechada
  (`deploy`, `production`, `migration`, `secret`, `secrets`, `"push "`,
  `"pull request"`, `"terraform apply"`, `"kubectl apply"`, `"rm -rf"`)
  continua exatamente a mesma. Em vez disso, `shared.policy.
  evaluate_task_policy` ganhou uma cláusula própria e independente:
  `delivery.allow_push == True` força `PolicyLevel.SENSITIVE` com o motivo
  `delivery_requests_push`, quer a palavra "push" apareça na instrução ou
  não — uma intenção de push é estruturalmente sensível, não lexicalmente.
  Pontos de segurança:
  - a pré-autorização (`shared.policy.push_is_preauthorized`) reduz — nunca
    amplia — o conjunto `SENSITIVE` que pode prosseguir sem decisão humana
    no momento: só se aplica quando **todo** sinal sensível presente é um
    dos dois textuais de push (`"push "`, `"pull request"`) e/ou a própria
    cláusula `delivery_requests_push`, e `delivery.branch` casa com
    `PUSHABLE_BRANCH_PATTERN` (`shared/protocol.py`). Qualquer outra
    palavra da lista (`deploy`, `secret`, `rm -rf`, …) mantém
    `approved=False` sempre, mesmo com `delivery` presente —
    `tests/unit/test_policy.py::test_no_other_sensitive_keyword_is_ever_preauthorized`
    prova isso iterando a lista inteira;
  - quando a pré-autorização se aplica, a tarefa não pula a aprovação:
    `gateway/app/services/store.py::create_task` grava a linha como
    `AWAITING_APPROVAL` exatamente como qualquer outra `SENSITIVE`, e só
    então resolve pelo caminho já existente e testado
    `decide_task_approval(..., ApprovalDecision.APPROVED, reason="pre-
    authorized in request by <ator>")` — o mesmo caminho que uma aprovação
    humana via `approve_codex_task` usa —, produzindo o mesmo
    `task.approval_decision`, o mesmo `policy_level`, e a mesma
    visibilidade em `/api/v1/decisions`. Um evento
    `task.push_preauthorized` próprio registra ator, branch, base branch e
    remote;
  - isso só acontece se quem chamou tiver autoridade de aprovação
    (`codexbridge.task.approve`, não apenas `codexbridge.task.submit`):
    `gateway/app/mcp/server.py` recusa `start_development_task` (e
    `publish_epic_to_repo`, quando um `delivery` é pedido) com
    `403 approval_not_allowed` se o principal não tem `can_approve_
    sensitive`/`is_admin()`, e com `400 branch_not_pushable`/
    `branch_required_for_push` se a branch falha `PUSHABLE_BRANCH_PATTERN`
    ou está ausente — a tarefa **nunca chega a ser criada** nesses casos,
    recusada na submissão em vez de enfileirada para falhar depois.
    `submit_codex_task` continua sem esse campo no seu próprio JSON
    Schema — `create_task`'s `can_approve_push` é inerte por esse caminho
    hoje, conforme o próprio comentário do call site;
  - `PUSHABLE_BRANCH_PATTERN` e a recusa de `main`/`master` são impostas em
    três camadas independentes, cada uma cega às outras: submissão
    (`gateway/app/mcp/server.py`, antes de qualquer linha existir),
    política do gateway (`shared.policy.push_branch_is_allowed`/
    `push_is_preauthorized`, usadas dentro de `evaluate_task_policy` e de
    `store.create_task`), e checagem do executor
    (`agent/codex_bridge_agent/git_delivery.py::deliver_changes`, que casa
    `PUSHABLE_BRANCH_PATTERN` de novo e recusa `main`/`master`/`HEAD`
    mesmo que o gateway já tenha aprovado — "a compromised or buggy
    gateway must not be able to grant `main` by lying about what it
    already verified", no próprio docstring do módulo). `AgentSettings.
    allow_git_delivery` é a trava de máquina desta terceira camada,
    **False por padrão** (mesmo desenho de `allow_workspace_write`) —
    desligada, `deliver_changes` recusa com `executor_delivery_disabled`
    mesmo com tudo o mais autorizado;
  - nenhum comando desta entrega pode carregar flag de força:
    `git_delivery.py` nunca emite `--force`, `--force-with-lease` ou
    refspec `+refs`
    (`tests/unit/test_git_delivery.py::test_no_command_ever_carries_a_force_flag`);
    staging é sempre por caminho explícito, nunca `-A`/`.`/`commit -a`
    (`::test_staging_never_uses_add_all_or_a_bare_dot`); `delivery.remote`
    passa por um padrão conservador antes de entrar no argv de
    `git push`, para que um valor como `"--force"` não seja lido como
    flag
    (`::test_refuses_an_invalid_remote_name_that_could_be_parsed_as_a_flag`);
    `HEAD` é relido imediatamente antes do commit e a operação é recusada,
    não forçada, se mudou nesse intervalo
    (`::test_head_moving_between_status_and_commit_is_refused_not_forced`);
    e a pós-condição do push é verificada contra o sha remoto, não apenas
    o código de saída;
  - **um `task.cancel` que chega enquanto a entrega já está em andamento**
    (issue #66, achado ARO **F34**: "a cancelled task that still has a
    running git delivery step in flight ... the git step should check for
    cancellation before committing") é tratado por uma trava dentro de
    `deliver_changes`, não no chamador (`design-standards.md` §3):
    `RunnerPool` grava um flag durável (`mark_cancel_requested`/
    `is_cancel_requested`, `agent/codex_bridge_agent/runners/pool.py`) no
    momento em que `_run_once` recebe `TASK_CANCEL` — independente do
    retorno de `runners.cancel()`, que só encontra um processo vivo para
    matar e já não encontra nenhum a essa altura, já que a entrega só roda
    depois que o runner terminou. `deliver_changes` consulta esse flag
    **uma única vez, imediatamente antes do `git commit`** — o mesmo ponto,
    e pela mesma razão, em que `HEAD` é relido logo acima — e recusa sem
    commitar (`outcome="refused", reason="cancelled_before_commit"`, árvore
    staged intacta, nada é "desfeito" à força). Uma vez passado esse
    checkpoint, o commit e qualquer push seguinte rodam até o fim sem
    interrupção: interromper um `git push` em andamento foi descartado
    deliberadamente (não há como este módulo reconhecer com segurança um
    subprocesso morto no meio de uma transferência, e nenhum `--force`
    jamais corrige isso depois). O flag é delimitado por `mark_dispatched`/
    `forget`, os mesmos que já delimitam `_task_engine`, então a
    cancelação de uma tarefa nunca vaza para a entrega de outra. Provado
    contra um repositório git real (não um mock que só verifica se a trava
    foi chamada) em
    `tests/unit/test_git_delivery.py::test_a_cancel_pending_before_the_commit_is_refused_without_committing`,
    `::test_cancellation_is_checked_exactly_once_immediately_before_commit`,
    `::test_a_cancel_arriving_after_the_commit_checkpoint_does_not_stop_the_push`
    e, de ponta a ponta através de `_handle_dispatch`/`RunnerPool` reais, em
    `tests/unit/test_agent_service.py::
    test_a_task_cancel_arriving_during_delivery_refuses_the_commit`/
    `::test_a_task_cancel_before_dispatch_does_not_prevent_a_later_unrelated_delivery`.
    Nenhum campo, ferramenta, estado ou coluna foi renomeado; `reason` já
    existia em `DeliveryOutcome`/`delivery_result_json` e só ganhou mais um
    valor possível — `GET /api/v1/missions/{id}/delivery` (issue #69)
    continua mapeando os mesmos nove campos de sempre
    (`gateway/app/api/routes/missions.py::_DELIVERY_RESULT_FIELDS`), então
    esse `reason` específico não é servido por esse endpoint hoje — ver
    "Lacunas assumidas para endurecimento" abaixo;
  - uma trava adicional contra "`SENSITIVE` vira `read-only` por engano"
    (o mesmo modo de falha da issue #34: saída 0, nenhuma mudança, nenhum
    erro) é fixada por `tests/unit/test_agent_service.py::
    test_sandbox_for_is_workspace_write_for_controlled_write_and_sensitive`;
  - cobertura completa: a matriz de quatro células (palavra-chave sozinha /
    `allow_push` sem palavra-chave / `allow_push` para `main` / os dois
    juntos) em `tests/unit/test_policy.py`; o passo de git isolado em
    `tests/unit/test_git_delivery.py`; a fiação `_handle_dispatch` →
    `deliver_changes` (com e sem `delivery` no payload, e nunca após uma
    tarefa que falhou) em `tests/unit/test_agent_service.py::
    test_handle_dispatch_runs_delivery_when_the_payload_carries_one`/
    `::test_handle_dispatch_never_runs_delivery_without_a_delivery_payload`/
    `::test_handle_dispatch_never_runs_delivery_after_a_failed_task`; o
    encaminhamento do `delivery` no payload de despacho do gateway em
    `tests/integration/test_dispatch_payload_engine_and_delivery.py`; e o
    schema/migração das quatro colunas novas (`engine`, `issue_ref`,
    `delivery_json`, `delivery_result_json`) em `tests/unit/
    test_schema_guard.py::test_engine_and_delivery_columns_are_required` e
    `tests/unit/test_apply_migrations.py::
    test_engine_and_delivery_columns_default_existing_rows_to_codex`.
    Não há, hoje, um teste de ponta a ponta com socket real gateway↔executor
    exercitando este caminho (o mais próximo é o par acima, um em cada
    lado, com o WebSocket substituído por um dublê) — ver "Lacunas
    assumidas para endurecimento" abaixo.

  A credencial que o `git push` de fato usa, o porquê de o executor poder
  alcançá-la agora, e a mudança na base do risco aceito F14 estão em
  `docs/threat-model.md`, seção "Commit e push deliberados pelo executor"
  — não repetidos aqui.
* operação de forge (issue #79/#80, WK-20260902-forge-binding): trava de
  máquina `allow_forge_operations` desligada por padrão; superfície fechada a
  quatro operações enumeradas à mão (`ForgeOperationKind`) sem "rodar `gh`
  com argv arbitrário"; credencial (`GH_TOKEN`) nunca entra no ambiente do
  processo do executor — fica fora da árvore, atrás de um symlink que
  `resolve_gh_token` recusa se apontar para dentro do repositório, e é
  injetada só no `env=` do subprocesso `gh`, uma vez por chamada; toda
  escrita nasce `awaiting_approval` sem nenhum campo de pré-autorização
  (`shared.policy.forge_operation_policy_level` — ver a subseção abaixo para
  os caminhos que este desenho recusou).
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
* download de artefatos (issue #11, `/api/v1/artifacts`, `/api/v1/builds/android`):
  os bytes ficam atrás de um token curto, emitido por
  `POST /api/v1/artifacts/{id}/download-token` e aceito **apenas** por
  `GET /api/v1/artifacts/{id}/download`. Pontos de segurança:
  - o token de sessão **não** baixa. O Android entrega uma transferência grande
    ao downloader do sistema, processo separado sem acesso à sessão do app; dar
    a ele o bearer de sessão colocaria a credencial que aprova tarefa sensível
    dentro de um componente cujo único trabalho é buscar arquivo. O contrato
    declara essa credencial como um `securityScheme` próprio
    (`artifactDownloadToken`), para que um cliente gerado não anexe o token
    errado e entre em laço de refresh;
  - a credencial viaja em `Authorization: Bearer`, **nunca** em query string —
    mesma regra que o #15 impôs ao `X-Executor-Token` (`security-standards.md`
    §2). A resposta do mint devolve um *caminho* sem credencial;
  - amarrada a um artefato, à conta que a emitiu (relida a cada download, então
    conta desabilitada ou com projeto retirado para de baixar) e a um prazo
    curto (`CODEX_BRIDGE_ARTIFACT_DOWNLOAD_TOKEN_TTL_SECONDS`, 300 s por padrão,
    limitado a `[30, 3600]`);
  - **`POST /api/v1/auth/revoke` mata também os tokens de download** do ator, em
    ambas as portas de revogação. Sem isso o sign-out derrubava a sessão e
    deixava o APK sendo baixado até o fim do TTL — a falha que aquele endpoint
    existe para impedir. Duas lentes do concílio reproduziram;
  - guardada com hash (`shared.security.hash_token`), como o access token: quem
    lê a tabela não baixa nada. Linhas expiradas são varridas a cada emissão;
  - **emitir é auditado** (`auth.artifact_download_authorized`, tipo de entidade
    `auth`, dentro da janela de retenção que `purge_expired_audit_events` varre).
    Sem isso, um APK vazado não teria como responder "quem foi autorizado a
    buscá-lo, e quando" — a linha do token some ao expirar;
  - toda recusa do download é o **mesmo** `401`: ausente, desconhecido,
    expirado, emitido para outro artefato, de conta desabilitada, ou revogado;
  - `artifacts.storage_path` nunca sai do servidor. A confinação é checada duas
    vezes: lexicamente na escrita (recusa `..`, absoluto, separador, segmento
    vazio) e após `Path.resolve()` na leitura, que é o que pega symlink plantado
    dentro da raiz. `CODEX_BRIDGE_ARTIFACTS_ROOT` define a raiz e **precisa ser
    definido no deploy**: o padrão resolve contra o diretório de trabalho do
    processo, não contra o checkout.
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
    tabela e nada removia linha nenhuma antes disso. A varredura só apaga os
    tipos de alto volume em `AUTH_SWEEPABLE_EVENT_TYPES` (`auth.sign_in_failed`,
    `auth.token_refreshed`, `auth.signed_in`): a janela existe para limitar
    volume, e aplicá-la a `entity_type = "auth"` inteiro apagaria
    `auth.credentials_revoked{reason:"refresh_token_reuse"}` — o único registro
    durável de que um refresh token roubado foi reapresentado — junto com
    `task.approved`, que o filtro por `entity_type` já poupava. Prova de violação
    e registro de aprovação não envelhecem por herança de um controle de spam.

### Caminhos rejeitados para uma operação de forge alcançar a rede

Issue #79/#80, decisão registrada nesta sessão (WK-20260902-forge-binding).
Uma operação de forge precisa de rede — `gh` fala com a API do GitHub — e o
sandbox do agente de codificação (`workspace-write`) não tem rede nenhuma,
verificado empiricamente na `devel3` em 2026-09-01
(`tests/integration/test_codex_sandbox_has_no_network.py`). Havia três
formas de dar rede a essa operação; duas foram descartadas.

1. **Rede aberta em `workspace-write`.** Ligar rede para toda tarefa que
   roda nesse sandbox — não só forge. Rejeitado: qualquer instrução chegando
   ao agente, incluindo conteúdo não confiável de uma issue lida de um
   repositório público (a própria separação de proveniência que
   `agent/codex_bridge_agent/instructions.py` existe para manter), ganharia
   rede sem nunca passar pela classificação de política. Isso não é "forge
   com um risco a mais" — é apagar a fronteira que today existe entre "este
   texto é do operador" e "este texto é de terceiros" para toda tarefa,
   permanentemente, para servir um caso que é uma fração pequena do
   trabalho.
2. **Rede só na tarefa aprovada, via `sandbox_workspace_write.
   network_access=true` por invocação.** Testado de verdade na `devel3` em
   2026-09-01 (`docs/napkin-lessons.md`, mesma data): a flag liga a rede
   dentro do sandbox de uma chamada específica sem tocar em nenhuma outra.
   Rejeitado mesmo assim — e a facilidade de ligar é o argumento *contra*,
   não a favor: uma flag por invocação não é uma superfície fechada e
   enumerável, é uma decisão que cada chamada pode tomar de novo. Nada
   impede uma futura instrução (ou um prompt de sistema editado sem cuidado)
   de simplesmente passar `network_access=true` para uma tarefa que não
   precisava de forge nenhum — o controle vira "confiar que ninguém liga a
   flag à toa", não "a rede está estruturalmente fechada exceto por um
   caminho revisado". A superfície deixa de ser enumerável, que é
   exatamente a propriedade que `ForgeOperationKind` (fechado, quatro
   membros, nenhum "rodar `gh` com argv arbitrário") existe para preservar.
3. **Adotado: a operação de forge roda FORA do sandbox, no processo do
   executor, como uma chamada de subprocesso limitada
   (`agent/codex_bridge_agent/forge/github.py`/`gh_tool.py`), nunca dentro de
   uma sessão do agente de codificação.** O sandbox do agente continua sem
   rede, sempre, sem exceção por invocação — a rede que uma operação de
   forge precisa nunca está disponível para nenhuma instrução que o agente
   de codificação processa, confiável ou não. O que substitui a flag por
   invocação é a superfície fechada e enumerada à mão
   (`ForgeOperationKind`), o portão humano sem pré-autorização
   (`shared.policy.forge_operation_policy_level`), e a credencial fora do
   ambiente do runner. Ver `docs/architecture.md`, "Isolamento e políticas",
   para o desenho completo.

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

### Risco aceito: token de download não é de uso único

* **Superfície:** `GET /api/v1/artifacts/{artifactId}/download` (issue #11), com
  um token emitido por `POST .../download-token`.
* **Caminho de abuso:** quem interceptar o token dentro da janela de validade
  (300 s por padrão) pode baixar aquele artefato quantas vezes quiser até o
  vencimento, ou até a conta ser desabilitada ou a sessão revogada.
* **Mitigação / por que fica assim:** a issue #11 pede *range e download
  retomável* na mesma frase em que pede *autorização de vida curta*, e as duas
  puxam para lados opostos. Um token consumido pela primeira requisição torna a
  retomada impossível — o downloader teria que se reautenticar no meio da
  transferência, que é exatamente o que essa credencial existe para evitar. O
  **prazo** é o controle, e é curto por isso. As demais amarras continuam:
  um artefato, uma conta (relida a cada download), e `POST /api/v1/auth/revoke`
  apaga todos os tokens de download vivos do ator.
* **Risco residual:** leitura repetida de bytes que o portador do token já podia
  ler uma vez, dentro de minutos. Nada é escrito, nada é emitido. Fixado por
  `tests/integration/test_artifacts.py::test_a_token_survives_reuse_inside_its_lifetime`,
  que é o que precisa mudar se a decisão mudar.


## Lacunas assumidas para endurecimento

* **`GET /api/v1/missions/{id}/delivery` não expõe o `reason` da entrega,
  inclusive o novo `cancelled_before_commit` (issue #66, F34).**
  `_DELIVERY_RESULT_FIELDS` (`gateway/app/api/routes/missions.py`) mapeia
  só nove campos — `branch`, `baseBranch`, `headCommit`, `commitSubject`,
  `filesChanged`, `insertions`, `deletions`, `pushed`, `deliveryOutcome` —
  deliberadamente sem `**data` passthrough, e `reason` nunca esteve entre
  eles, para nenhum motivo de recusa (`forbidden_path:...`, `head_moved:...`,
  `push_verification_failed`, ou agora `cancelled_before_commit`). Um
  operador lendo esse endpoint hoje distingue "recusado" de "commitado" e
  de "commitado mas não empurrado" (os campos `deliveryOutcome`/`pushed`
  já bastam para isso), mas não distingue POR QUÊ foi recusado sem olhar
  `delivery_result_json` bruto no banco ou o log do executor
  (`task.delivery_cancelled:<id>`, emitido por `deliver_changes` no mesmo
  ponto em que recusa). `deliveryOutcome` é um enum fechado no contrato
  (`docs/api/codex-bridge.openapi.yaml::MissionDeliveryOutcome`) e não foi
  alterado por esta entrega — abrir um valor específico para "recusado por
  cancelamento" exigiria mudar esse contrato, fora do escopo desta issue.
  Fechar esta lacuna é decisão do operador: versionar o contrato para
  adicionar `reason` (ou um outcome próprio) a essa resposta, ou aceitar
  que a distinção fica em `delivery_result_json`/logs, não na API.
* **Uma corrida pré-existente entre `task.cancelled` e `task.result` no
  gateway pode mostrar uma tarefa como `cancelled` por um instante mesmo
  quando a entrega termina com sucesso (branch de verdade no remoto).**
  Achada ao investigar F34, não introduzida por esta entrega e não corrigida
  por ela — está fora do escopo desta issue, que é sobre o passo de git no
  executor, não sobre reconciliação de estado no gateway.
  `AgentService._run_once` responde a `TASK_CANCEL` imediatamente,
  mandando `task.cancelled` de volta antes que a entrega em andamento
  termine (`gateway/app/main.py::handle_task_cancelled` grava
  `TaskState.CANCELLED` sem condição nenhuma). Quando a entrega termina
  depois — mesmo tendo sido recusada por `cancelled_before_commit`, ou
  tendo commitado e empurrado porque o cancelamento chegou tarde demais
  (ver o bullet acima sobre o checkpoint único) — `TASK_RESULT` chega e
  `store.store_result`/`update_task_state` sobrescrevem o estado sem
  checar transição alguma, então o estado final do lado gateway é sempre o
  que `TASK_RESULT` diz por último, e a leitura `CANCELLED` no meio é
  apenas transitória. Isso já é verdade para QUALQUER entrega recusada
  hoje, não é novo neste PR; fica registrado aqui porque é exatamente a
  situação que a issue nomeia como "a task reported cancelled while its
  branch is live" — o `delivery_result_json` está correto em qualquer
  ponto dessa corrida, é o `TaskModel.state` que pode ler `cancelled`
  momentaneamente enquanto o branch já existe no remoto. Fechar isso é
  uma mudança de `gateway/app/main.py`/`store.py` (validar transição de
  estado, ou não sobrescrever um estado terminal com outro), fora dos
  arquivos que esta entrega toca.
* **A entrega com push pré-autorizado (issue #66) não tem, neste checkout,
  teste de ponta a ponta com um socket real gateway↔executor, nem registro de
  um push de verdade contra um remoto real.** A suíte cobre cada lado
  isoladamente — a política em `tests/unit/test_policy.py`, o passo de git em
  `tests/unit/test_git_delivery.py`, a fiação `_handle_dispatch` →
  `deliver_changes` com um WebSocket dublê em `tests/unit/test_agent_service.py`,
  o encaminhamento do payload de despacho em
  `tests/integration/test_dispatch_payload_engine_and_delivery.py` — mas
  nenhum teste faz um `codex-bridge-agent` real se conectar a um gateway real
  e completar um push. A issue #66 lista essa live corrida como item do
  Definition of Done ("A pre-authorized push ... produces a real commit and
  a verified push, end to end, in the live smoke test"); nada em
  `docs/napkin-lessons.md`, `handoff.md` ou no histórico git deste checkout
  registra que ela foi executada. Fechar essa lacuna é rodar a corrida contra
  um repositório e remoto reais e registrar o resultado, ou o operador emitir
  uma renúncia (waiver) explícita por escrito.
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
  offline. O custo por tentativa é limitado a `_MAX_ITERATIONS` (2.000.000):
  `verify_password` recusa um hash acima disso e `_iterations_of` o conta como 0,
  então um `pbkdf2_sha256$99000000$…` (typo ou hash migrado) não vira DoS de
  autenticação — a conta fica inutilizável, não cara, e o padding a cobre para
  não abrir oráculo de timing. Algoritmo diferente de `pbkdf2_sha256` também vale
  0. Uma conta legitimamente escrita acima do teto ficaria inutilizável.
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

## Revisão adversarial da issue #4 — decisões pendentes do operador

O concílio de revisão adversarial da issue #4 (2026-08-26, três lentes:
segurança, cético, segundo-chamador — `docs/napkin-lessons.md`) levantou achados
que **contradizem uma regra estabelecida ou uma decisão de direção**, e por
`.docs/agents/council.md` §1 saem do concílio para o operador em vez de serem
corrigidos pelo programador. Estão aqui para não se perderem:

* **[S1 — ship-blocking] Delegação OAuth estreitada ainda confere admin.** Uma
  conta com `roles: ["admin"]` em `users.json` recebe um grant com escopos
  interseccionados a `CODEX_BRIDGE_OAUTH_DEFAULT_SCOPES` — possivelmente `[]` —
  e mesmo assim `is_admin()` (lê `roles`, não o grant) libera tudo em ambos os
  transportes. `CODEX_BRIDGE_OAUTH_DEFAULT_SCOPES`, o único teto de um deployment,
  não retém nada de uma conta admin; um grant de terceiro (ChatGPT) que o
  operador estreitou no formulário de consentimento não é estreitado.
  Reproduzido: sign-in admin → `scopes:[]`, `/auth/me` → `projects.all:true`,
  `decisions.decide.allowed:true`. Correção aponta contra o modelo de papéis
  fixado por `tests/integration/test_auth.py:1120-1156` (`is_admin` derivar de
  `codexbridge.admin` no grant, mintado no sign-in) — **direção do operador**,
  não mudança silenciosa. `gateway/app/core/users.py:64-68`.
* **[Política da corrida de rotação — conflito de direção] Duas lentes apontam
  em sentidos opostos.** O cético: o **perdedor da corrida concorrente** de
  `/refresh` recebe 401 mas o grant **não** é revogado nem auditado
  (`auth.py:286-290`), então roubo sobrevive à corrida que o UPDATE condicional
  existe para arbitrar. O segundo-chamador: um **retry após resposta perdida**
  (o cliente móvel normal) reapresenta o mesmo refresh, cai em `REFRESH_REUSED`
  e revoga o grant inteiro — inclusive os tokens novos que o vencedor acabou de
  emitir — e grava um registro de *roubo* contra um retry benigno. Consertar num
  sentido (revogar na corrida perdida) piora o outro (retry benigno mata a
  sessão). É um conflito de papéis → `.docs/agents/council.md` §1 → **operador
  decide a direção** (uma opção citada: aceitar `Idempotency-Key` em `/refresh`,
  como `epics.py`/`issues.py` já fazem, e reservir o par do vencedor).
* **[Oráculo dos contadores do /revoke — entrelaçado com o achado 17]** Os
  contadores `accessTokensRevoked`/`refreshTokensRevoked` na resposta de
  `/revoke`, sem autenticação, distinguem token vivo (`1/1`) de desconhecido
  (`0/0`) e vazam quantas rotações a sessão teve — contradizendo o próprio
  contrato ("says nothing about which one"). **Não corrigido** porque o corpo de
  contadores está fixado pelo teste do achado 17
  (`test_a_consumed_refresh_token_still_ends_its_own_grant`, que afirma
  `accessTokensRevoked >= 1` no caminho refresh-token-only), que é fenced. Mudar
  os contadores exige mexer no achado 17 → **operador**. Opção: emitir contadores
  só a chamador autenticado, ou remover os campos (RFC 7009 não define corpo).
* **[S6 — fora do escopo da #4] `/mcp` com corpo JSON não-objeto explode antes de
  autenticar.** `POST /mcp` com corpo `[]` sem `Authorization` em modo `oauth`
  → `AttributeError` → 500 nu, antes do bearer check (`main.py:211`). É a função
  de auth, mas do transporte `/mcp`, adjacente à #4. Correção de 1 linha
  (`isinstance(body, dict)`), deixada para o operador decidir se entra aqui ou
  numa issue de `/mcp`.
* **[S7 — escalabilidade] `users.json` é relido e reparseado por request no event
  loop.** 0,159 ms com 10 contas, 46,4 ms com 5.000 / 1,1 MB. Inofensivo hoje;
  registrar. Cache por mtime ou `to_thread` fecharia.

Achados corrigidos nesta entrega (branch `feature/gh-4/adversarial-review-fixes`,
com teste que falha sem a correção): S2 (registro malformado falha fechado, não
500), S4 (colisão de chave case-insensitive recusa o registro), S5 (custo de
derivação limitado por algoritmo e teto), SC#1 (`accessTokenExpiresAt` e
`expiresIn` limitados ao prazo do grant), SC#7 (revogação no-op não grava linha
de auditoria), S3 (varredura de retenção poupa registros de incidente).

### Risco aceito (issue #4, review): registro ilegível derruba sessões

`load_user_registry` falha **fechado** para qualquer exceção, inclusive `OSError`
(volume desmontado, permissão trocada) — o mesmo que para JSON malformado. Uma
falha de I/O transitória vira sign-out forçado da frota inteira em `/api/v1` em
vez de um `500 retryable:true`. Aceito: um registro que o processo não consegue
ler não deve conceder nada, e a falha de deployment continua nomeada no startup
(`main.py`) e em `/mcp` (`user_registry_unavailable`). Se a distinção I/O vs
parse valer um `503` em `/api/v1`, é ajuste do operador.

### Achados da rodada 2 do concílio (introduzidos pelos próprios fixes)

A rodada 2 checou os fixes acima. Fechados na mesma entrega: o teste do cap de
SC#1 ganhou limite inferior (`0 < expiresIn`); `_MAX_ITERATIONS` subiu para
10.000.000 (16x o custo de produção) para não travar um operador que endurece; a
docstring do teste de retenção foi corrigida. Ficam registrados, com risco
aceito ou como decisão do operador:

* **[risco aceito] Conta com hash acima de `_MAX_ITERATIONS` fica inutilizável e
  o sign-in com a senha *correta* audita `bad_password`.** Acima de 10.000.000 de
  rounds `verify_password` recusa (a conta não entra), `_iterations_of` conta 0,
  e `unusable_registry_reason` não sinaliza a entrada específica. Aceito porque o
  teto agora está muito acima de qualquer custo honesto; uma entrada acima dele é
  configuração absurda. Se o operador quiser sinal explícito,
  `unusable_registry_reason` pode passar a nomear a entrada fora do teto.
* **[decisão do operador] Sign-out de rotina agora é retido para sempre.** A
  varredura de retenção poupa todo `auth.credentials_revoked` para preservar a
  prova de roubo (`refresh_token_reuse`) e a revogação forçada
  (`account_unavailable`); como consequência, o `signed_out` de rotina — antes
  varrido sob `entity_type == "auth"` — também deixa de envelhecer. Volume baixo
  (um por fim de sessão, autenticado) e a varredura só roda no startup de todo
  jeito. O fix limpo distingue por `reason`, o que hoje exigiria SQL específico
  de banco (`json_extract`) ou um `event_type` distinto para o sign-out de
  rotina — mudança no contrato de auditoria, direção do operador.
* **[pré-existente, não introduzido] Replay repetido de um refresh token roubado
  é auditado uma vez e depois nunca mais.** A primeira reapresentação grava
  `refresh_token_reuse`; da segunda em diante `inspect_refresh_token` retorna
  `revoked` e o handler responde 401 sem gravar evento (não existe
  `auth.refresh_failed`). O operador não distingue um replay de dez mil. Anterior
  a esta entrega; um tipo de evento para falha de refresh o fecharia.
* **[nota] Sinal-de-lado de S4:** o sign-in por `user_id` ficou
  case-insensitive (as chaves do índice são `.lower()`). Seguro — a guarda de
  colisão proíbe a ambiguidade — mas nem `docs/installation.md` nem o OpenAPI
  mencionam. **[nota] S2 loga por request** enquanto o registro está quebrado
  (sem cache), até 120 linhas WARNING/min/bucket com o caminho do arquivo.

## Recomendações de produção

* usar PostgreSQL real com backup e retenção;
* mover tokens para `EnvironmentFile` root-only;
* colocar o gateway atrás de `nginx` com TLS válido;
* executar o agente em conta dedicada `codexbridge`;
* limitar os diretórios liberados em `ReadWritePaths`;
* manter o modo bearer apenas para compatibilidade administrativa;
* operar o uso humano do ChatGPT exclusivamente via OAuth.
