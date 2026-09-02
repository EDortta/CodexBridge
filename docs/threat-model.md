# Modelo de ameaça

## Ativos protegidos

* repositórios e workspaces do executor (`devel3`; historicamente `T610`)
* credenciais do `codex`, Git e ferramentas locais
* histórico de tarefas, logs e diffs
* disponibilidade do `gateway`
* integridade da fila de tarefas

## Atores

* usuário legítimo do ChatGPT com acesso ao MCP
* operador do gateway
* agente executor legítimo
* atacante externo tentando usar o endpoint público
* repositório malicioso contendo prompt injection

## Ameaças e controles

### Acesso indevido a projeto não autorizado

* controle: `project_id` obrigatório, sem path arbitrário
* controle: allowlist no gateway (`registry.json`) e allowlist redundante no
  agente (`projects.json`); o agente responde `unknown_project` se o id não
  estiver na sua própria lista
* controle: `realpath` do caminho cadastrado antes de executar

Precisão sobre a ancestralidade: `ensure_within_root` existe e resolve `realpath`,
mas hoje é chamada como `ensure_within_root(project.path, project.path)`
(`agent/codex_bridge_agent/service.py`) — raiz comparada contra ela mesma, então a
verificação de ancestralidade sempre passa. Isso **não** é vulnerabilidade no
desenho atual, porque não existe componente de caminho vindo do cliente: o único
path possível é o cadastrado na allowlist local.

A checagem passa a ser necessária de verdade no momento em que qualquer campo de
subcaminho for aceito na tarefa (arquivo alvo, subdiretório, worktree). Quem
implementar isso precisa passar a raiz do projeto e o alvo como argumentos
distintos. Registrado aqui para que ninguém leia "ancestralidade verificada" e
presuma proteção que ainda não está armada.

**Raiz de auto-descoberta do executor (WK-20260830, opt-in, `CODEX_BRIDGE_AGENT_AUTO_PROJECT_ROOT`).**
Decisão do operador (2026-08-30): quando ligada, "allowlist redundante no
agente" acima deixa de ser uma lista fechada e vira "qualquer repositório git
real sob esta raiz" (`shared/project_discovery.py`, `resolve_auto_project`).

* controle: só ativa por configuração explícita — desligada por padrão, sem
  mudança de comportamento para quem não a liga
* controle: a varredura nunca segue symlink e nunca sobe diretório (herdado
  de `walk_for_git_repos`) — testado explicitamente
  (`test_a_symlinked_directory_outside_root_is_never_followed`)
* controle: o caminho encontrado é resolvido (`realpath`) e checado contra a
  raiz resolvida antes de virar um `ProjectRegistration` — segunda barreira
  sobre a mesma garantia, no único ponto que devolve um caminho para quem vai
  rodar um agente de código contra ele
* controle: só precisa ter `.git` — uma pasta comum não vira projeto por
  engano
* risco aceito, com escopo explícito: esta válvula move a fronteira da
  **camada 7** (`docs/project-onboarding.md`) de "cadastrado à mão" para
  "existe fisicamente dentro desta árvore" — ainda uma fronteira, mais larga.
  **Não afeta as camadas 1–6**, que rodam no gateway: um projeto ainda
  precisa existir em `registry.json` antes de o ChatGPT conseguir nomeá-lo
  (`gateway/app/services/store.py:resolve_project_reference` não tem
  equivalente — o gateway não enxerga o disco do executor). Ligar esta
  válvula sozinha não entrega "qualquer projeto, sem cadastro nenhum,
  ponta a ponta" — só remove o segundo cadastro (o do executor), não o
  primeiro (o do gateway).

### Descoberta de projetos pelo nó (WK-20260902, issue #73 Stage 3)

Distinta da válvula anterior: `AgentSettings.discovery_roots` não amplia o que
um despacho pode resolver (`auto_project_root` continua sendo isso, inalterado
por este trabalho). Ela faz o nó **relatar** o que vê sob raízes configuradas
por ele mesmo — para um humano decidir depois, numa PR seguinte, que ainda
não existe.

* controle: opt-in explícito e vazio por padrão
  (`AgentSettings.discovery_roots`) — nenhum comportamento novo sem
  configuração
* controle: a varredura reusa `shared.project_discovery.walk_for_git_repos`,
  herdando as mesmas duas garantias já testadas para
  `resolve_auto_project`: nunca segue symlink, nunca sobe diretório
* controle: só lê — nenhum comando de varredura escreve no repositório
  candidato (`git remote get-url origin`, `git rev-parse HEAD`,
  `git status --porcelain`, todos read-only)
* controle: **nenhuma escrita de autorização é alcançável por este caminho**.
  `store.record_discovery_report` só tem acesso de escrita a
  `discovered_resources`; não importa, não consulta para escrita, e não
  atribui a `ProjectAuthorizationModel`, `ProjectModel` nem
  `WorkspaceBindingModel` — propriedade estrutural, testada diretamente
  (`tests/unit/test_discovery_store.py::
  test_record_discovery_report_never_writes_authorization_or_projects`,
  `tests/integration/test_agent_ws_discovery.py::
  test_the_receiving_branch_writes_only_discovered_resources`). Um nó
  comprometido que relata candidatos fabricados só polui a fila de adoção —
  não tem, por construção, nenhum caminho para conceder capacidade a nada
* controle: o path absoluto do candidato (`DiscoveredResourceModel.
  resource_path` desde `migrations/0014_discovery_resource_key_hash.sql`;
  antes disso vivia em `resource_key`) só sai por uma rota REST: `GET
  /api/v1/nodes/{nodeId}/discovered-resources` e as respostas de
  `adopt`/`deny` — a mesma regra de `local_path`
  (`docs/api/README.md`, "Fields that must never ship"), gated pelo mesmo
  escopo administrativo de `nodes.read`. `resource_key` propriamente dito
  deixou de ser o dado sensível: é `hash_resource_key(path)`, sem relação
  reversível com o path, e não aparece em DTO nenhum
* controle: o mesmo guard de identidade do `hello`/`heartbeat`
  (`envelope.executor_id` reivindicado vs. autenticado no handshake) já cobre
  `discovery.report` por estar antes de qualquer branch no laço de
  recepção — um nó não pode relatar descobertas **como** outro nó
* controle: um `DiscoveryReport` malformado é descartado com `WARNING`, nunca
  derruba a conexão — mesma postura já adotada para um `hello` inválido
* risco aceito, sem mitigação nova nesta PR: nenhum teto explícito no número
  de candidatos por relatório (`DiscoveryReport.candidates` não tem
  `max_length`). Na prática limitado pelo filesystem real do nó e por
  `max_size=2_000_000` bytes na conexão WebSocket que o próprio nó abre
  (`agent/codex_bridge_agent/service.py:_run_once`); o gateway não impõe um
  limite equivalente do seu lado hoje — o mesmo estado, não pior, que já vale
  para `task.log` e os demais tipos de mensagem deste canal. O pior caso
  continua sendo ruído em `discovered_resources`, nunca escalada de
  privilégio, pela mesma garantia estrutural do controle acima
* recomendação operacional: um nó cujo `discovery_roots` aponta para uma
  árvore que o operador não controla totalmente relata o que existir nela —
  a mitigação é a mesma de sempre: escolher a raiz com cuidado, não confiar
  cegamente no que ela aponta

### Adoção de descobertas pelo painel (WK-20260902-gh73-discovery-adoption, issue #73 Stage 3, metade de adoção)

A metade que fecha o ciclo aberto pela seção anterior: `discovered_resources`
passa a poder virar `ProjectModel`, `WorkspaceBindingModel`,
`ScmAssociationModel` e `project_authorizations` — só por este caminho, nunca
pelo caminho do nó.

* controle: **um nó não alcança `project_authorizations` por construção,
  mesmo com as rotas de adoção existindo.** `store.adopt_discovered_resource`
  e `store.deny_discovered_resource` são as ÚNICAS funções que escrevem
  nessas quatro tabelas a partir de uma linha de `discovered_resources`, e
  ambas exigem `permissions.NODES_DISCOVERIES_DECIDE`
  (`codexbridge.admin`). `gateway/app/api/auth.py:current_principal` — o
  único jeito de uma requisição REST virar um `AuthenticatedPrincipal` —
  resolve exclusivamente um token OAuth (`store.get_oauth_access_token`); o
  `machine_token` do executor autentica só o WebSocket
  (`gateway/app/main.py:agent_ws`), checado ali mesmo, e nunca produz um
  `AuthenticatedPrincipal`. Não existe caminho de código da credencial de um
  nó conectado até `adopt`/`deny` (testado diretamente:
  `tests/integration/test_discovery_routes.py::
  test_a_principal_without_the_administrative_scope_cannot_adopt`,
  `tests/unit/test_discovery_store.py::
  test_a_matching_auto_authorize_root_grants_nothing_from_a_report_alone` —
  este último com uma raiz `auto_authorize` de verdade configurada, provando
  que a configuração por si só não basta sem a decisão humana)
* controle: `AUTO_AUTHORIZABLE_CAPABILITIES` (`read`/`test`) é validado no
  parse de `DiscoveryRoot`, antes de qualquer nó conectar — `modify`/
  `deliver` nunca são obteníveis por `auto_authorize`, só por
  `grantCapabilities` explícito no corpo da requisição, atribuído a
  `operator:<user_id>`
* controle: `adopt`/`deny` só agem sobre um candidato em estado
  `discovered`/`stale` — um já decidido responde `409`, o que também é o que
  impede uma segunda chamada de duplicar `WorkspaceBindingModel`/
  `ScmAssociationModel`
* controle: a regra "DENIED nunca é tocado por observação" (seção anterior)
  continua valendo depois de decidido — nada nesta PR toca
  `record_discovery_report`'s tratamento de `DENIED`, e há teste direto
  (`tests/integration/test_discovery_routes.py::
  test_a_denied_resource_is_not_touched_by_a_later_report`)
* controle: `ProjectAuthorizationModel` permite só uma linha não revogada por
  `(node_id, project_id)` — uma concessão de raiz e uma concessão explícita
  do operador na mesma chamada de adoção são mescladas na mesma linha
  (`granted_by` vira um conjunto `;`-separado de origens), nunca duas linhas
  competindo pelo índice único
* risco aceito: `resourcePath`/`rootPath` (paths absolutos) saem por
  `GET /api/v1/nodes/{nodeId}/discovered-resources` e pelas respostas de
  `adopt`/`deny` — exceção deliberada e estreita à regra "nenhuma resposta
  expõe path de filesystem", gated pelo mesmo escopo administrativo de
  `nodes.read`. Ver `docs/api/README.md`, "Fields that must never ship"

### Execução de comandos arbitrários

* controle: nenhuma ferramenta MCP genérica de shell
* controle: o agente chama `codex exec` sem shell
* controle: argumentos montados como arrays

### Replay e duplicação de mensagens

* controle: `message_id` por evento
* controle: tabela de deduplicação no gateway
* controle: ACK explícito do agente

### Prompt injection a partir do repositório

* controle: instrução-base anexada pelo agente antes do prompt do usuário
* controle: política explícita proibindo exfiltração, push, deploy e leitura fora do projeto
* controle: bloqueio de tarefas sensíveis sem aprovação
* controle: truncagem e sanitização de conteúdo retornado

### Vazamento de segredos por logs

* controle: sanitização por padrões conhecidos
* controle: limitação de tamanho por chunk e total
* controle: persistência separada de logs e resultado final

### Credenciais herdadas pelo subprocesso `codex exec`

Decisão declarada, não lacuna acidental.

O agente monta o ambiente do subprocesso com uma allowlist de 6 variáveis
(`filtered_environment`, em `agent/codex_bridge_agent/codex_runner.py`):
`HOME`, `PATH`, `LANG`, `LC_ALL`, `CODEX_HOME`, `OPENAI_API_KEY`.

Consequência: o `codex exec` roda com `HOME` do usuário do agente. Com `HOME` vêm,
por alcance de sistema de arquivos, `~/.gitconfig`, credential helpers do Git,
`~/.ssh` e o próprio `CODEX_HOME`. E `OPENAI_API_KEY` é repassada diretamente.

* razão: o `codex` precisa de autenticação e de identidade Git para operar; sem
  `HOME` e sem a chave, o produto não funciona
* risco aceito: instrução vinda do ChatGPT executa num processo que **alcança**
  essas credenciais. Um repositório com prompt injection pode tentar induzir o
  modelo a lê-las e devolvê-las no resultado
* controles que mitigam, sem eliminar: `BASE_PROMPT` proíbe explicitamente
  acessar segredos e diretórios pais; `sanitize_log_line` redige `sk-*`, `ghp_*`
  e `Bearer *` nos logs; o resultado é truncado
* controle que **não** existe: nada impede leitura de `~/.ssh` pelo subprocesso, e
  a sanitização cobre três padrões conhecidos, não chave privada SSH nem token de
  formato novo
* recomendação operacional: usuário Linux dedicado ao agente, com `HOME` próprio,
  sem chaves SSH pessoais e sem credenciais Git de escrita em repositório de
  produção — assim o que o subprocesso alcança é o mínimo que o `codex` exige

A política de sandbox do `codex exec` é explícita, não mais o default herdado
do CLI (issue #34): `read-only` a menos que o `policy_level` da tarefa já
indicasse escrita, com trava adicional por executor
(`AgentSettings.allow_workspace_write`). Ver `docs/development.md`.

### Commit e push deliberados pelo executor (WK-20260830, slice de #51)

A premissa muda aqui, e precisa ficar escrita: a seção acima já documentava
que o `HOME` herdado alcança `~/.gitconfig`, credential helpers do Git e
`~/.ssh` — mas até esta mudança essa credencial era alcançável e nunca
deliberadamente usada pelo produto. `agent/codex_bridge_agent/git_delivery.py`
passa a **usar** essa mesma credencial de propósito, para dar commit e (se
autorizado) push, a pedido de uma tarefa concluída.

* controle: roda **fora** do sandbox do provider (`codex exec`/`claude -p`) —
  o agente (LLM) nunca invoca `git commit`/`git push` ele mesmo; é sempre este
  módulo, depois que o processo do provider já saiu
* controle: `AgentSettings.allow_git_delivery` — trava de máquina, **False por
  padrão**. Só liga quando um operador decide explicitamente que este
  executor pode escrever remoto
* controle: `delivery.branch` é conferido contra `PUSHABLE_BRANCH_PATTERN`
  duas vezes — uma no gateway (`shared.policy.push_is_preauthorized`), outra
  aqui — para que um gateway comprometido ou com bug não consiga conceder
  `main` alegando já ter verificado
* controle: `delivery.remote` é validado contra um formato conservador de
  nome de remote (deve começar com letra) antes de entrar no argv de
  `git push --set-upstream <remote> <branch>` — sem essa checagem, um valor
  como `"--force"` seria interpretado como flag pelo próprio git, já que este
  módulo monta listas de argv, não uma string de shell
* controle: staging é sempre por caminho explícito (`git add -- <paths>`),
  nunca `-A`/`.`/`commit -a`; nenhum comando emite `--force`,
  `--force-with-lease` ou refspec `+refs`; `HEAD` é relido imediatamente antes
  do commit e a operação é recusada (nunca forçada) se mudou nesse intervalo
* controle: a pós-condição do push é verificada (`git rev-parse
  <remote>/<branch>` comparado ao sha do commit) — um `git push` que retorna 0
  não é, por si, prova de que o remoto está no estado esperado
* risco aceito: com `allow_git_delivery=true`, uma tarefa pré-autorizada
  (`allow_push=true` numa branch válida) resulta em push real usando a
  credencial de git deste executor. O controle final contra abuso é a
  pré-autorização em si — registrada como decisão auditável
  (`task.push_preauthorized`), nunca implícita
* recomendação operacional: a mesma da seção anterior — usuário Linux
  dedicado ao agente, sem credenciais de escrita em repositório de produção
  além do(s) repositório(s) que este executor está autorizado a entregar

### Escalada local no executor

* controle: usuário Linux dedicado e não root
* controle: diretórios autorizados e env allowlist
* controle: `systemd` com endurecimento
* controle: limites de CPU, memória, tarefas e tempo

### Egresso novo do gateway para o Google Calendar (WK-20260830, issue #71)

Até esta mudança o `frida` só *aceita* conexão (WebSocket reverso do
executor, chamadas MCP do ChatGPT). `create_reminder`/`cancel_reminder`
introduzem o primeiro caso em que o **gateway** disca para fora, dentro do
tratamento de uma chamada MCP: `oauth2.googleapis.com` (troca de token) e
`www.googleapis.com` (Calendar API v3).

* controle: timeout duro em toda chamada HTTP (`connect=10s, read=20s`) —
  uma indisponibilidade do Google não pode prender um worker do MCP
  indefinidamente
* controle: token de acesso em cache no processo por ~55 min (5 min de
  margem sob o TTL de 60 min do Google) — o subprocess `openssl` e a troca de
  token são raros, não por chamada
* controle: a chave privada da service account só toca disco num arquivo
  temporário modo 0600, apagado em `finally` logo após a assinatura; nunca
  passada como argumento de linha de comando (apareceria em `/proc/*/cmdline`)
  e nunca logada — testado explicitamente
  (`test_no_fixture_private_key_value_ever_appears_in_any_raised_message`)
* controle: nenhuma mensagem de erro deste módulo pode conter a chave privada
  — só o `client_email` (não é segredo) para tornar a instrução de
  compartilhamento acionável
* controle: `create_reminder`/`cancel_reminder` são a única superfície que
  toca o Google; falha de configuração ou de rede nelas nunca falha
  `submit_codex_task`/`start_development_task` — testado explicitamente
  (`test_an_unconfigured_gateway_still_serves_submit_codex_task_normally`)
* risco aceito: uma service account comprometida escreve/apaga eventos na
  agenda que foi compartilhada com ela — mitigado por escopo
  `codexbridge.reminders.write` separado (nunca implícito no escopo padrão
  de leitura/tarefas) e pela recomendação de uma agenda dedicada
  "CodexBridge", não a agenda pessoal do operador
* recomendação operacional: service account dedicada a este uso, não
  reaproveitada de outro projeto — revogar a chave de uma SA compartilhada
  quebraria os outros consumidores dela

### Egresso novo do gateway por e-mail (WK-20260830, issue #70)

`notify.notify_task_finished` é o segundo caso em que o gateway disca para
fora: ao SMTP configurado em `CODEX_BRIDGE_NOTIFICATION_EMAIL_CONFIG_FILE`,
depois que `TASK_RESULT` já comitou o resultado real da tarefa.

* controle: credencial só por referência — a variável de ambiente aponta
  para um arquivo (`~/.config/credentials/email/*.conf` em dev, obrigatoriamente
  fora de qualquer home em produção por causa de `ProtectHome=true` na unit
  systemd), nunca a senha inline em configuração versionada
* controle: o arquivo de credencial é recusado se tiver qualquer bit de
  grupo/outro (`mode & 0o077`) — testado explicitamente
  (`test_a_world_readable_config_file_is_refused`, `tests/unit/test_notify.py`)
* controle: `aiosmtplib`, não `smtplib` bloqueante — a mesma classe de
  problema já documentada e corrigida uma vez para `users.authenticate`
* controle: uma falha de envio (config ausente, arquivo inseguro, erro de
  rede, credencial rejeitada pelo servidor) nunca falha a tarefa — o estado
  final já foi comitado antes desta chamada; toda falha vira um evento
  `task.notification_failed` com **apenas o nome do tipo da exceção**, nunca
  a mensagem (que rotineiramente ecoa o banner do servidor e às vezes a
  própria credencial) — testado explicitamente
  (`test_a_sender_that_raises_never_fails_the_task_and_records_only_the_exception_type`)
* controle: o corpo do e-mail nunca inclui diff, linha de log, conteúdo de
  arquivo do repositório, ou caminho absoluto. Duas escolhas deliberadas: (1)
  `task.last_error` **nunca** entra no corpo — não está na lista de campos
  que a issue #70 permite, e `redact()` só reconhece formas conhecidas de
  segredo/caminho, não "isto é um log ou um diff" em geral, então um
  `last_error` "redigido" ainda não seria uma garantia real contra a issue
  (`test_task_last_error_is_never_included_in_the_email`); (2) o único campo
  de texto livre que o corpo carrega — o motivo de recusa da entrega — passa
  pelo mesmo `redact()` já usado nas respostas da API
  (`gateway/app/api/routes/sessions.py`) antes de entrar no corpo
  (`test_a_delivery_refusal_reason_is_redacted`) — ambos em
  `tests/unit/test_notify.py`
* controle: destinatário fixo por configuração do operador
  (`CODEX_BRIDGE_NOTIFICATION_TO`), nunca `requested_by_email` nem qualquer
  noção de "o usuário" vinda do harness — ver
  `docs/required-reading.md`, "Fontes locais — fora do checkout"
* risco aceito, escopo explícito (finding F27 do concílio, parcial): dispara
  em `TASK_RESULT` (concluída/falhou), `task.cancelled`, e no cancelamento
  por reconexão órfã (issue #17) — testado em
  `tests/integration/test_agent_ack_handling.py` e
  `tests/integration/test_reconnect_replay_resolves.py`. Só a varredura de
  recuperação no startup (`store.recover_tasks_after_startup`, que resolve
  tarefas expiradas ou perdidas após uma queda do gateway) ainda não dispara
  e-mail — esse único caminho continua coberto apenas pelo polling descrito
  em `docs/chatgpt-registration.md`

### Fila inconsistente após reinício

* controle: banco transacional
* controle: recuperação de tarefas `running` para `lost`
* controle: redispatch apenas para tarefas `queued` ou `waiting_executor`

## Premissas

* o `frida` terá TLS válido no reverse proxy
* o executor (`devel3`) possui `codex` autenticado e funcional
* os projetos autorizados são cadastrados explicitamente
* o agente roda em conta sem privilégios administrativos

