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
* `approve_codex_task`
* `list_recent_tasks`
* `start_development_task`
* `create_epic`
* `list_epics`
* `update_epic`
* `create_issue`
* `list_issues`
* `update_issue`
* `move_issue_to_epic`
* `publish_epic_to_repo`
* `create_reminder`
* `cancel_reminder`

`publish_epic_to_repo` (issue #78, WK-20260902-issue-materialize) materializa
uma épica e suas issues (`EpicModel`/`IssueModel`, já expostas por
`create_epic`/`list_epics`/`create_issue`/`list_issues`) como arquivos
markdown versionados em `docs/issues/` do repositório do PRÓPRIO projeto —
inclusive um projeto nunca publicado em nenhum forge. Requer um executor
conectado que autorize o projeto da épica: sem um, falha com erro tipado
(`project_not_onboarded`/`executor_not_connected`), nunca enfileira
silenciosamente. `gateway/app/services/issue_render.py:render_epic_markdown`
é uma função pura — sem I/O, sem LLM — que decide os bytes de cada arquivo
antes de qualquer coisa cruzar para o executor; ver `## Materialização de
épicas` abaixo para o fluxo completo sobre o canal reverso.

São 22 ferramentas. `create_reminder`/`cancel_reminder` (issue #71) escrevem
no Google Calendar do operador, não em `tasks` — nada a ver com execução de
código. Exigem escopo `codexbridge.reminders.write` e ficam desligadas com
erro acionável (nunca 500) quando `CODEX_BRIDGE_GOOGLE_CALENDAR_ID` ou
`CODEX_BRIDGE_GOOGLE_CALENDAR_CREDENTIALS_FILE` não estão configuradas —
o resto do gateway continua servindo normalmente. `approve_codex_task` é a que libera tarefa parada em
`awaiting_approval` pela política de sensibilidade, e exige principal com escopo
`codexbridge.task.approve` ou `can_approve_sensitive`.

`start_development_task` (WK-20260830-chatgpt-entry-provider-and-delivery, issue
#65) é a entrada conversacional: resolve `project` (id, nome ou prefixo único),
resolve o executor automaticamente quando omitido, calcula `expires_at` sozinho
e devolve uma estimativa de duração (`eta_seconds`/`eta_basis`/`eta_sample_size`,
mais `queue_wait_seconds` quando o executor-alvo está no limite de concorrência
ou acima — WK-20260903-gh67-70-read-gaps, issue #67) baseada no histórico real
de tarefas. Aceita `issue` (`docs:NNN`/`NNN` resolvido
**no executor**, `local:<id>` resolvido no gateway, `gh:<n>` recusado —
ingestão de issue do GitHub não tem dono neste sistema) e `engine`
(`codex`/`claude`/`cursor-agent`/`gemini`/`opencode`/`aider`, default `claude`).
`allow_push=true` exige `branch` casando `PUSHABLE_BRANCH_PATTERN` e escopo
`codexbridge.task.approve` — nunca cria a tarefa sem os dois. As quatro
ferramentas com nome `codex` continuam respondendo exatamente como antes
(57a surface inventory): `get_task_status` e `list_recent_tasks` só ganharam
campos aditivos (`engine`, `issue_ref`, `delivery`, `delivery_result`, e agora
também `eta_seconds`/`eta_basis`/`eta_sample_size` — WK-20260903-gh67-70-read-gaps,
issue #67 Scope / #70 Scope; `queue_wait_seconds` fica só em
`start_development_task`, que é onde a espera antes do despacho é decidida).

## Canal reverso do agente

Endpoint: `wss://codexbridge.inovacaosistemas.com.br:8443/agent/ws?executor_id=<ID>`

O token de máquina vai no header `X-Executor-Token`, **não na URL**. Um handshake
WebSocket é uma requisição HTTP e carrega headers normalmente; a query string vira
linha de log em todo componente do caminho — foi assim que o token apareceu 37
vezes no journal do gateway e 70 nos logs do nginx (#15). O `executor_id` continua
na query: ele nomeia o executor, não é segredo.

```
GET /agent/ws?executor_id=devel3
Upgrade: websocket
X-Executor-Token: <token de máquina>
```

A forma antiga `?token=...` **foi removida** (a release de compatibilidade que
#15 concedeu já passou). Token só na URL agora é o mesmo que token nenhum: o
handshake fecha com `4401`, antes de qualquer consulta ao registro. Um executor
que ainda mande o parâmetro precisa ser atualizado — o agente envia o header
desde a mesma release (`agent/codex_bridge_agent/service.py`).

Códigos de fechamento no handshake:

| Código | Significado |
|---|---|
| `4401` | nenhuma credencial apresentada |
| `4403` | token não confere com o registro, **ou** o nó foi revogado (issue #76: `admission_state == "revoked"`) — mesmo código para os dois motivos, sem estado novo no protocolo em si |
| `4404` | `executor_id` desconhecido |

Issue #76 (corte mínimo): o gateway não compara mais o token apresentado contra
texto claro em `metadata_json` — compara `hash_token(presented)` contra
`executors.machine_token_hash`. Isso é interno (`gateway/app/main.py:agent_ws`,
`gateway/app/services/store.py:upsert_registry`) e não muda nada do que está
descrito acima: mesmo header, mesmos códigos, mesma semântica de `4403` para
quem já estava lá antes — só passa a valer também para um nó revogado por
`POST /api/v1/nodes/{nodeId}/revoke` (`docs/api/README.md`, seção "Nodes and
enrollment"). Um socket já aberto no momento da revogação é fechado com este
mesmo `4403` por `AgentHub.force_close`, chamado pelo endpoint de revoke — não
pelo laço de recepção deste handshake.

Mensagens (`AgentMessageType` em `shared/protocol.py`):

* `hello`
* `hello_ack`
* `heartbeat`
* `task.dispatch`
* `task.ack`
* `task.log`
* `task.result`
* `task.cancel`
* `task.pause`
* `task.resume`
* `task.restart`
* `task.cancelled`
* `forge.operation`
* `forge.operation_result`
* `error`
* `issue.materialize`
* `issue.materialize_result`
* `discovery.report`

Não existe mensagem `task.progress`. O progresso é inferido pelo fluxo de
`task.log`, cada uma com `offset` incremental.

### Payload do `hello`: `NodeAnnouncement`

Até a Stage 2 da #73 o `hello` levava `{"version": "0.1.0"}` e o gateway **não
tinha branch para ele** — a mensagem era persistida como recibo e descartada.
Agora ela carrega um `NodeAnnouncement` (`shared/protocol.py`):

```json
{
  "agent_version": "0.1.0",
  "os": "Linux",
  "arch": "x86_64",
  "engines": [
    {"engine": "codex",  "implemented": true,  "available": true,  "version": "codex-cli 1.4.2"},
    {"engine": "claude", "implemented": true,  "available": false, "detail": "not found on PATH"},
    {"engine": "gemini", "implemented": false, "available": false, "detail": "no runner implemented"}
  ],
  "capabilities": ["read", "test"],
  "max_concurrent_tasks": 1,
  "discovery_root_count": 1
}
```

Sem `node_id`: o nó é aquele para o qual o `executor_id` autenticado aponta. Sem
caminho: `discovery_root_count` é contagem, não as raízes. `capabilities` é o que
a configuração da máquina permitiria, nunca uma concessão sobre projeto — ver
`docs/control-plane.md`.

**Compatibilidade:** um agente de release anterior segue enviando `{"version":
...}`. O gateway lê essa forma como `agent_version` e um payload que não valide
gera `WARNING` e **não derruba a conexão** — um gateway que desliga o agente da
release anterior transforma deploy em interrupção.
## Materialização de épicas

`issue.materialize`/`issue.materialize_result` (issue #78,
WK-20260902-issue-materialize) são o par que `publish_epic_to_repo` usa —
**fire-and-forget, no mesmo padrão de `task.dispatch`**, mas sem
`TaskModel` por trás: não há fila nem vaga de concorrência a liberar, e "sem
executor conectado" já é recusado de forma síncrona pela própria tool (ver
`## MCP externo` acima), nunca despachado depois.

1. O gateway renderiza os arquivos com `issue_render.render_epic_markdown`
   (função pura — dado o mesmo `EpicModel`/lista de `IssueModel`, sempre os
   mesmos bytes) e envia `issue.materialize` com o payload de
   `MaterializeRequest` (`shared/protocol.py`): `epic_id`, `project_id`,
   `slug` (o componente `<epic-slug>-[<status>]` do nome da pasta, sem o
   `NNN`), `files` (caminho relativo à pasta da épica → conteúdo),
   `existing_path` (não nulo numa republicação), `epic_revision`/
   `issue_revisions` (a `revision` de cada linha no instante da renderização)
   e o bloco `delivery` opcional (reaproveita `DeliveryRequest`/
   `PUSHABLE_BRANCH_PATTERN`, mesmo mecanismo de `SubmitTaskRequest.delivery`).
2. As chaves de `files` para issues carregam o id da issue como segmento do
   caminho (`issues/<issue_id>/<slug>-[<status>].md`) — um token de
   correlação consumido pelo executor e nunca escrito em disco (ver
   `agent/codex_bridge_agent/issue_materialize.py`), porque `NNN` não é
   escolhido nem aqui nem no gateway (próximo item).
3. O EXECUTOR escolhe todo `NNN` — a mesma fronteira que `docs:NNN`/`NNN`
   já respeita do lado da leitura (`## MCP externo`, `start_development_task`):
   o gateway nunca aprende o path real do projeto (`docs/architecture.md`).
   Numeração é um pool único compartilhado entre a pasta da épica e cada
   arquivo de issue (e qualquer outra épica/issue já no disco); corrida de
   numeração é resolvida por criação atômica (`mkdir`/`O_CREAT|O_EXCL`) com
   nova tentativa no próximo número livre.
4. O executor responde `issue.materialize_result`: `{epic_id, ok, epic_path,
   epic_revision, written_paths, issue_revisions}` no sucesso (`written_paths`
   ecoa as MESMAS chaves de `files`, resolvidas para o caminho final relativo
   ao projeto — inclusive `README.md`/`epic.md`, sem segmento de id); ou
   `{epic_id, ok: false, error}` na falha, nunca uma exceção crua.
5. `gateway/app/main.py:handle_issue_materialize_result` grava
   `materialized_path`/`materialized_revision` na épica e, para cada chave de
   `written_paths` prefixada por `issues/`, na issue cujo id está embutido no
   segundo segmento do caminho — sem re-derivar a correspondência a partir da
   lista atual de issues (que pode ter mudado entre o pedido e a resposta).
### Payload de `discovery.report`: `DiscoveryReport`

Issue #73 Stage 3. Um nó com `AgentSettings.discovery_roots` configurado (por
padrão, vazio — nenhum comportamento novo sem opt-in) varre cada raiz num laço
próprio (`AgentService._discovery_loop`, intervalo
`discovery_scan_interval_seconds`, padrão 3600s), **desacoplado do
heartbeat de 15s**: uma varredura real (247 repositórios, na raiz que motivou
este trabalho) não é algo para repetir a cada 15 segundos, nem algo que possa
atrasar um heartbeat ou um despacho.

**Uma mensagem por raiz, nunca um payload único para todas as raízes** — uma
raiz lenta ou incomumente grande não pode atrasar o relatório de nenhuma
outra:

```json
{
  "root_path": "/home/esteban/Sync/Projects",
  "candidates": [
    {
      "resource_key": "/home/esteban/Sync/Projects/AI/CodexBridge",
      "suggested_project_id": "codexbridge",
      "suggested_name": "CodexBridge",
      "remote_url": "git@github.com:example/codexbridge.git",
      "head": "a1b2c3d",
      "dirty": false
    }
  ],
  "scanned_at": "2026-09-02T18:00:00Z"
}
```

Deliberadamente **separada** de `NodeAnnouncement`/`hello`, não um campo a
mais nele: o `hello` é pequeno e viaja a cada reconexão; um relatório de
descoberta pode carregar centenas de candidatos, e misturar os dois faria
toda reconexão arrastar esse inventário inteiro junto — ver o próprio
docstring de `DiscoveryReport` em `shared/protocol.py`.

`resource_key` é o path absoluto do candidato no nó — dado sensível, na mesma
categoria de `workspace_bindings.local_path`
(`docs/control-plane.md`, `docs/api/README.md` "Fields that must never
ship"). Deliberadamente **não** é `suggested_project_id`:
`suggest_project_id` só garante unicidade dentro da varredura de uma raiz, e
duas raízes varridas de forma independente podem sugerir o mesmo id para
dois diretórios diferentes — o que de fato identifica uma linha em
`discovered_resources` é o path.

`remote_url` vem de `git remote get-url origin`; ausência de `origin`
configurado não é erro, vira `None`.

`root_path` é exatamente a string configurada em
`AgentSettings.discovery_roots` no nó, nunca resolvida/expandida — ela
precisa casar, caractere a caractere, com o `DiscoveryRoot.path` que o
operador configura no lado do gateway (`ExecutorRegistration.
discovery_roots`, consumido pela PR de adoção que segue este trabalho), que
por sua vez também nunca é resolvido (`DiscoveryRoot.path`'s próprio
docstring): o gateway não enxerga o disco do nó.

**Recepção no gateway:** o laço de `/agent/ws` (`gateway/app/main.py`) chama
**apenas** `store.record_discovery_report(session, executor, report)`, que
escreve **apenas** em `discovered_resources` — nunca em
`project_authorizations`, `projects` ou `workspace_bindings`. Isso é o que
torna "o nó propõe, o painel adota" verdade **por construção**: o caminho que
recebe uma descoberta não tem, no código, nenhum jeito de conceder
autorização. As regras de reconciliação de estado (candidato novo, candidato
já visto, ausência, `DENIED`, `STALE` que reaparece) estão em
`docs/control-plane.md`.

Mesma postura tolerante do `hello`: um payload que não valida como
`DiscoveryReport` gera `WARNING` e é descartado — a conexão **nunca** é
derrubada por um relatório malformado, e o guard de identidade
(`envelope.executor_id` reivindicado vs. autenticado no handshake, "Identidade:
o handshake manda, o envelope não" acima) já cobre este tipo de mensagem
também, por estar antes de qualquer branch, não dentro de um.

**Nenhuma rota REST lê `discovered_resources` ainda** — listar e decidir
candidatos é a próxima PR.

Campos comuns:

* `message_id`
* `executor_id`
* `sent_at`
* `type`
* `payload`

## Identidade: o handshake manda, o envelope não

`AgentEnvelope.executor_id` é campo que o **cliente escreve** no corpo da
mensagem; o `executor_id` do `/agent/ws` é o que apresentou token de máquina no
handshake. O laço de recepção compara os dois **antes** de despachar e descarta
o envelope quando divergem, com `WARNING`.

A verificação vive num ponto só, e não em cada branch, por histórico: a #16 já
tinha corrigido isso para `task.ack` isoladamente, e todo tipo de mensagem
acrescentado depois herdou a confiança de novo. Sem a guarda, um nó autenticado
podia anunciar-se **como outro** — forjando as capacidades relatadas de uma
máquina alheia, ou renovando a liveness dela para que um nó morto aparecesse
saudável, que é exatamente a superfície de frota que a Stage 2 existe para
tornar confiável.

Descartar, não redirecionar: reescrever o id reivindicado para o autenticado
aceitaria em silêncio, como declaração do remetente, uma mensagem que ele não
fez sobre si. E descartar não derruba a conexão — derrubar transformaria um
agente com bug em interrupção, e daria a um atacante um jeito de desconectar
um nó.

## Idempotência

O gateway persiste `message_id` em `message_receipts`. Mensagens repetidas do agente são descartadas.

## Reconexão: replay de controle pendente

`AgentHub.register()` roda a cada `hello` aceito, **antes** de qualquer
`task.dispatch` para esse executor:

1. Marca o executor como conectado.
2. Busca tarefas desse executor em `cancelled` sem `task.cancel_acknowledged`
   registrado — o executor nunca confirmou a parada porque estava
   desconectado quando `task.cancel` foi enviado (issue #17). Reenvia
   `task.cancel` para cada uma.
3. Busca tarefas presas em `pausing`/`resuming`/`restarting` — o `task.ack`
   correspondente nunca chegou porque o executor caiu antes de respondê-lo
   (issue #16). Reenvia `task.pause`/`task.resume`/`task.restart` conforme
   o estado.
4. Só então despacha a próxima tarefa da fila, se houver vaga.

O replay de `task.cancel` é limitado a `cancel_replay_max_age_seconds`
(padrão 24h, `gateway/app/core/config.py`) contado a partir do momento em que
a tarefa virou `cancelled`. O replay de `task.pause`/`task.resume`/
`task.restart` (passo 3) é limitado do mesmo jeito, por
`control_replay_max_age_seconds` (padrão 24h também, configurável
separadamente), contado a partir do último `task.state_changed` da tarefa —
esse limite não existia antes (issue #17 council, "the sweep skeptic"): sem
ele, uma tarefa presa havia um ano era reenviada a cada reconexão, para
sempre. Um executor que reaparece depois do prazo quase certamente já
terminou ou foi reimplantado — o replay existe para fechar a janela normal de
reconexão, não para reenviar controles de dias atrás. Passado o prazo, a
tarefa permanece no estado em que estava, sem novo reenvio.

O executor sempre confirma um `task.cancel`, mesmo para um `task_id` que não
conhece: a tarefa correspondente já pode ter terminado, expirado, ou nunca ter
sido executada nesta máquina (por exemplo, um `cancel_codex_task` que cancelou
uma tarefa ainda `queued`/`waiting_executor` nem chegou a ser despachada).
`CodexRunner.cancel` retorna `False` nesse caso, mas o pós-condição de um
cancel — "não está rodando aqui" — vale de qualquer forma, então
`task.cancelled` é enviado de volta incondicionalmente (issue #17 council,
"the claim auditor" / "the second caller"). Antes disso o agente só
respondia quando havia um processo de verdade para terminar, e o gateway
ficava esperando um `task.cancelled` que um runner reiniciado nunca ia
mandar — prendendo a vaga de concorrência do executor pelo resto do processo
do gateway.

O mesmo problema existia para `task.pause`/`task.resume`/`task.restart`: o
`task.ack` sempre foi enviado, mas com `accepted: false` tanto para "sei da
tarefa e recusei por um motivo real" quanto para "nunca ouvi falar dessa
tarefa" — o gateway não conseguia distinguir os dois casos. O payload do
`task.ack` agora inclui `known` (booleano, ausente = `true` para
compatibilidade com agentes antigos): quando `known` é `false`, o gateway
resolve a tarefa como `cancelled` e libera a vaga de concorrência, em vez de
reverter para o estado que o controle assumia (que pressupõe um processo
vivo em algum lugar, e não há nenhum).

## Operações de forge e o portão humano

Issue #80/#79, `WK-20260902-forge-wiring-and-gate` (PR B3). Uma operação de
forge (abrir/comentar/fechar/listar issue no GitHub via `gh`) não é uma
`task.dispatch`: ela roda fora do sandbox do provedor de codificação, como um
único processo `gh` limitado no próprio executor, e carrega uma credencial
(`GH_TOKEN`) que nunca entra no sandbox de uma sessão de codificação. Por
isso tem envelope próprio (`forge.operation`/`forge.operation_result`) em vez
de virar mais um modo de `task.dispatch` — os dois campos que
`_sandbox_for`/`RunnerPool` entendem (`mode`, `engine`) não descrevem nada
sobre uma operação de forge, e forçar um valor sentinela neles ensinaria
esses módulos a tratar um caso que não é deles.

Persistência é uma tabela própria no gateway, `forge_operations`
(`migrations/0015_forge_operations.sql`), **não** uma linha em `tasks`: as
colunas de `tasks` (`mode`, `instruction`, `engine`, `timeout_seconds`,
`session_id`, `delivery_json`) descrevem uma sessão de agente de código, e
`shared.policy.forge_operation_policy_level` é explícita que a classificação
`SENSITIVE` de uma escrita de forge não tem — e nunca deve ter — um campo de
bypass, ao contrário de `delivery_json`'s push (`push_is_preauthorized`).
Ver a docstring de `ForgeOperationModel`
(`gateway/app/models/entities.py`) e o corpo do commit desta PR para a
justificativa completa dessa decisão, incluindo por que ela não reusa a
superfície `/api/v1/decisions` da issue #6.

Ciclo de vida de uma linha `forge_operations.state`:

1. `awaiting_approval` — nasce assim toda ESCRITA (`issue_open`,
   `issue_comment`, `issue_close`): `forge_operation_policy_level` devolveu
   `SENSITIVE`. `issue_list` (leitura) nasce direto em `approved` — nunca
   passa pelo portão.
2. `approved` — um humano decidiu (`store.decide_forge_operation`, mesmo
   vocabulário `ApprovalDecision` da issue #6: `approved`/`rejected`/
   `revision_requested`), ou a operação era `issue_list`.
3. `dispatched` — `AgentHub.dispatch_forge_operation` enviou o envelope
   `forge.operation` para o executor. Esta função É o portão do lado do
   gateway: recusa (levanta `ValueError`) para qualquer estado que não seja
   `approved`, antes de tocar em `self.connections` ou enviar qualquer
   coisa — não existe caminho por onde um `forge.operation` sai do gateway
   para uma linha ainda `awaiting_approval`.
4. `completed`/`failed` — um `forge.operation_result` voltou
   (`gateway/app/main.py:handle_forge_operation_result`, que chama
   `store.resolve_forge_operation`).

Ou termina sem nunca despachar: `rejected`/`revision_requested`, uma decisão
humana negativa — este protocolo não tem mensagem que reabra uma operação de
forge para edição, a mesma lacuna que `routes/decisions.py` já documenta
para `TaskModel`.

O executor (`AgentService._handle_forge_operation`,
`agent/codex_bridge_agent/service.py`) **não** re-deriva
`forge_operation_policy_level` a partir do envelope, ao contrário do que
`_handle_dispatch` faz com `evaluate_task_policy` para uma task. A diferença
é deliberada: como a política de forge não tem campo de bypass, re-derivá-la
no executor recusaria toda escrita incondicionalmente, mesmo depois de uma
aprovação humana real — apagaria a funcionalidade em vez de defendê-la. O
executor confia que o gateway só manda `forge.operation` para uma linha
`approved`, e defende, de forma independente, só o que um gateway
comprometido ou com bug ainda poderia mentir: o projeto está na allowlist
local deste executor (a mesma resolução de `_handle_dispatch`, reaproveitada)
e a trava de máquina `allow_forge_operations` (default `False`) — as duas
travas são independentes; ambas precisam estar ligadas para `gh` rodar de
verdade.

Nesta PR (B3) o único jeito de criar/aprovar/despachar uma operação de forge
é chamando `store.create_forge_operation`/`store.decide_forge_operation`/
`AgentHub.dispatch_forge_operation` diretamente — não existe rota REST nem
ferramenta MCP ainda (por isso o contrato OpenAPI não muda nesta PR). Expor
isso para o operador via ChatGPT é B4.

## Binding de forge, `gh:N` e as ferramentas MCP (B4)

WK-20260902-forge-binding, issue #79/#80 (PR B4). B3 (acima) deixou a
operação de forge com portão humano mas sem superfície: nenhuma rota REST,
nenhuma ferramenta MCP, `gh:N` sempre recusado. Esta PR fecha os três.

### `project_forge_binding` — o único ponto que decide "ligado" ou não

`gateway/app/services/forge_routing.py`'s `project_forge_binding(session,
project_id) -> ForgeBinding | None` lê `scm_associations` (migration `0009`,
vazia e sem código até esta PR) e é a única função que qualquer chamador —
as ferramentas MCP abaixo, `AgentHub.dispatch_next` para `gh:N` — deveria
consultar para essa pergunta. `None` significa "roteie para as tabelas
locais", não um erro.

O `confidence` da associação começa `declared` (um operador nomeou o
repositório via `bind_project_forge`) e só vira `confirmed` por um
`confirm=true` explícito, na mesma chamada — nunca automaticamente. Ver
`ScmAssociationModel`'s docstring (`gateway/app/models/entities.py`) para a
razão completa.

### O executor confirma o remote real antes de qualquer operação

`agent/codex_bridge_agent/forge/github.py`'s `_confirm_repo_identity_live`
roda `git remote get-url origin` (via `git_tools.run_git`) antes de CADA
operação de forge — leitura ou escrita, `issue_list`/`issue_view` incluídos
— e recusa `repo_identity_mismatch` se o remote real divergir do
`repo_identity` que o gateway declarou no envelope. Sempre ao vivo, nunca
cacheada: uma chamada `git` local não custa rede nenhuma, e elimina a
necessidade de um job de reconciliação para o caso "a pasta perdeu ou
trocou o remote depois que o binding foi declarado".

### `gh:N` deixa de ser recusado incondicionalmente

Novo quinto membro em `ForgeOperationKind`: `ISSUE_VIEW` (`gh issue view
--json title,body`), classificado `READ` como `ISSUE_LIST` —
`shared.policy.forge_operation_policy_level` nunca gate nenhum dos dois.

Fluxo para um `issue_ref` no formato `gh:N`:

1. Na criação da task (`gateway/app/mcp/server.py:start_development_task`),
   `gh:N` não é mais recusado incondicionalmente — só quando
   `project_forge_binding(project_id)` devolve `None`. Ligado, segue para
   dispatch como qualquer outro `issue_ref`, sem tentar resolver o conteúdo
   no gateway (o gateway nunca aprende o path real do projeto,
   `docs/architecture.md`).
2. No dispatch (`AgentHub.dispatch_next`), se `task.issue_ref` começa com
   `"gh:"`, o binding é resolvido e `repo_identity` viaja no payload como
   `forge_repo_identity` — só computado para esse formato, para não pagar
   uma consulta extra em todo dispatch normal.
3. No executor (`AgentService._handle_dispatch`), sem `forge_repo_identity`
   no envelope, a recusa é `issue_source_unsupported`, byte a byte igual à
   de antes desta PR. Com ele, o executor monta um `ForgeOperationRequest`
   `ISSUE_VIEW` e chama `run_forge_operation` — a mesma trava
   `allow_forge_operations`, a mesma confirmação de remote ao vivo, o mesmo
   módulo `forge/github.py` que qualquer outra operação usa.

**Invariante inegociável, testado diretamente**
(`tests/unit/test_agent_service.py::test_gh_issue_body_never_reaches_policy_evaluation`):
o texto devolvido por `gh issue view` só alcança
`instructions.build_task_instruction`'s `issue_text`, dentro do bloco
`--- BEGIN UNTRUSTED ISSUE CONTENT ---` — nunca `SubmitTaskRequest.instruction`
nem `evaluate_task_policy`, que só vê as próprias palavras do operador,
montadas pelo gateway antes de `_handle_dispatch` rodar. Issue de repositório
público é gravável por qualquer um; deixar seu texto influenciar a
classificação de política deixaria um estranho forçar (ou evitar) o portão
de aprovação sensível de uma tarefa deste operador.

### As ferramentas MCP de forge — roteamento é um `if`, não uma escolha do operador

Cinco ferramentas novas em `gateway/app/mcp/server.py`/`tools.py`:

* `bind_project_forge` (escopo `codexbridge.admin`) — declara/confirma a
  associação. É o que liga o roteamento das outras quatro.
* `create_project_issue`, `list_project_issues`, `comment_project_issue`,
  `close_project_issue` — cada uma faz `binding = await
  project_forge_binding(session, project.id)`; `binding is not None` roteia
  para uma operação de forge (`store.create_forge_operation`, mesmo portão
  de toda escrita de forge); `None` roteia para as tabelas locais deste
  gateway (issue #8: `store.create_issue`/`list_issues_page`/`update_issue`).
  O operador chama a mesma ferramenta, com os mesmos argumentos, nos dois
  casos — nunca precisa dizer em qual projeto está.

`comment_project_issue` não tem equivalente local (este gateway não modela
comentário em issue local) e devolve `forge_binding_required` quando o
projeto não está ligado — uma recusa tipada honesta, não uma tentativa de
forçar o conceito onde ele não existe.

Uma leitura de forge (`list_project_issues` ligado) é despachada na mesma
chamada — `hub.dispatch_forge_operation`, o mesmo "nunca no-op silencioso"
que `dispatch_available` já tem para uma task, mas nunca espera decisão
humana (`issue_list` nasce `approved`). Uma escrita de forge de qualquer
uma dessas ferramentas nunca é despachada pela própria ferramenta — nasce
`awaiting_approval` e espera na Central de Decisões, como toda escrita de
forge desde B3.

### A Central de Decisões projeta as duas fontes

`gateway/app/api/routes/decisions.py`'s módulo docstring e
`docs/api/README.md`'s seção "Decisions" têm o desenho completo: uma decisão
de forge tem `id` prefixado (`forge:<uuid>`, nunca colide com um `TaskModel.id`
por construção), `decisionType: "forge_operation"`, e aprovar despacha via
`AgentHub.dispatch_forge_operation` — o mesmo par
`decide_task_approval`/`dispatch_available` que a issue #20 corrigiu para
task, aplicado à tabela de forge para que o mesmo bug não aconteça de novo
num lugar diferente.
