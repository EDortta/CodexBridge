# Plano de controle — nós, projetos, bindings e autorização

Modelo de domínio da issue **#73** ("CodexBridge Control: fleet, nodes, project
adoption and authorization plane"), Stage 1. Este arquivo descreve **o que as
entidades significam e por que são separadas**. O protocolo pelo fio está em
`docs/protocol.md`; as camadas de autorização em ordem de execução continuam em
`docs/project-onboarding.md`.

## As três regras da #73 que decidiram o formato

Cada uma descarta a mudança menor que teria sido tentadora.

**1. "A project MUST NOT be structurally owned by a node or by GitHub."**
Por isso a relação Projeto↔máquina é uma tabela própria (`workspace_bindings`) e
a relação Projeto↔repositório é outra (`scm_associations`). Uma coluna em
`projects` teria privilegiado estruturalmente um nó e um remote — e tornaria
inexprimível "o mesmo projeto no `frida` e no `devel3`, em caminhos diferentes",
que é justamente o caso que a #73 desenha.

**2. "Discovery is not authorization."**
O que um nó **relata** cai em `discovered_resources`; o que ele **pode fazer**
vive em `project_authorizations`. Duas tabelas porque são escritas por dois
atores diferentes — o nó anuncia, o operador (ou uma concessão permanente de
raiz) autoriza. Confundir as duas é exatamente a falha que a #73 nomeia:
*"a node cannot grant itself project authorization merely by reporting a
discovery."*

**3. "Do not collapse these into a single `enabled` boolean."**
`discovered_resources.state` carrega os cinco valores de
`shared.protocol.DiscoveredState`. Cada par que alguém se sentiria tentado a
fundir perde uma distinção real:

| par fundido | o que se perde |
|---|---|
| `denied` + `discovered` | candidato recusado volta à fila de adoção a cada reconexão |
| `stale` + ausência | projeto que mudou de lugar perde linha e histórico |
| `adopted` + `authorized` | some a diferença entre "aceitei este projeto" e "concedi capacidade sobre ele" — que a #73 separa explicitamente |

## Entidades

| Tabela | O que é | O que **não** é |
|---|---|---|
| `nodes` | uma instalação CodexBridge (máquina + capacidades) | não é a conexão; não é o executor |
| `executors` | a conexão autenticada que leva trabalho a um nó | não é a máquina |
| `projects` | o projeto lógico | não é um diretório, não é um repositório |
| `workspace_bindings` | o projeto **naquele** nó, no disco dele | não é autorização |
| `scm_associations` | o projeto ↔ um repositório remoto | não é identidade do projeto |
| `project_authorizations` | o que aquele nó pode fazer àquele projeto | não é "o workspace existe" |
| `discovered_resources` | o que o nó vê, adotado ou não | não é permissão |

`nodes` e `executors` são 1:1 hoje — `0009_control_plane.sql` semeia um nó por
executor existente — e o schema não exige que continuem sendo. A separação existe
porque a #73 alerta contra *"conflating `node`, `executor`, `engine` and
`project` into one entity"*, e renomear o executor para nó teria feito a mesma
confusão na direção oposta.

## Capacidades

O vocabulário (`shared.protocol.Capability`) é **derivado** de `TaskMode`, nunca
paralelo a ele. `CAPABILITY_MODES` é o mapa inteiro, e `allowed_modes` segue
sendo o único ponto de enforcement:

| capacidade | modos |
|---|---|
| `read` | `analyze`, `review` |
| `test` | `test` |
| `modify` | `edit`, `implement` |
| `deliver` | *(nenhum)* |

`deliver` não mapeia modo porque entrega não é modo: é
`SubmitTaskRequest.delivery`, gateada por `PUSHABLE_BRANCH_PATTERN` e pelo escopo
`codexbridge.task.approve`. Está nomeada para que uma autorização possa
**negá-la**, não para mover esse portão.

Introduzir um segundo vocabulário de permissão independente seria o
"parallel concepts" que a #73 desaconselha: exigiria enforcement próprio, testes
próprios e teria drift próprio.

## Raízes de descoberta e a concessão automática

Um nó só varre as `discovery_roots` configuradas no seu registro — a #73 é
explícita: *"No recursive whole-machine discovery by default."* Sem raiz
configurada, nada é descoberto, que é o comportamento de hoje.

`DiscoveryRoot.auto_authorize` é a concessão permanente e auditável do operador
para tudo sob **uma** árvore. A decisão é tomada uma vez por árvore em vez de uma
vez por projeto — é esse o atrito que este trabalho remove. Ela é limitada por
`AUTO_AUTHORIZABLE_CAPABILITIES` a `read` e `test`, **validado no parse**, antes
de qualquer nó conectar: `modify` e `deliver` nunca são obteníveis por anúncio,
só por concessão explícita que nomeia uma pessoa (`granted_by` distingue
`root-config:<path>` de `operator:<user_id>`).

Uma raiz sem `auto_authorize` — o padrão — varre e enfileira candidatos para
adoção, concedendo nada.

## Caminho absoluto: dado operacional sensível

`workspace_bindings.local_path` existe porque a #73 precisa dele para responder
"esse workspace é usável?" e "onde este projeto roda?". Ela também limita onde
ele pode aparecer: *"must only be returned to appropriately authorized operator
surfaces; they must not leak through public/client contexts that do not need
them."*

Isso **reverte** o invariante que `docs/architecture.md` afirmava — o gateway
passa a aprender o caminho. A contenção mudou de "o gateway nunca sabe" para "o
gateway sabe e só conta a quem tem escopo de operador". Registrado aqui, e em
`docs/threat-model.md`, porque uma reversão de invariante silenciosa é pior que a
reversão.

Nunca sai em `ProjectStatus`, `Session`, `Mission` nem em ferramenta MCP alguma —
ver `docs/api/README.md`, "Fields that must never ship".

## O que a 0009 deliberadamente **não** faz

- **Não concede nada.** A tabela de autorização nasce vazia. Adotar o schema não
  pode, por si, dar a nenhum nó capacidade sobre nenhum projeto — nem sobre os
  projetos que ele já rodava, cujo acesso continua fluindo pelo
  `allowed_projects` pré-existente. Uma migration que pré-preenchesse isso "para
  preservar comportamento" estaria inventando concessões que ninguém fez.
- **Não remove `projects.path`.** Ele deixa de ser autoritativo assim que
  `workspace_bindings` é populado, mas removê-lo na mesma migration que cria seu
  substituto destruiria a única cópia do caminho de qualquer projeto ausente do
  `registry.json` atual. O backfill vive em `store.upsert_registry` (onde a
  associação executor↔projeto de fato mora, dentro de `executors.metadata_json`)
  e não é exprimível em SQL portável. A remoção é migration posterior, depois de
  bindings verificados em produção.

## Stage 2 — visibilidade de frota

Stage 1 criou o vocabulário; a Stage 2 o preenche com observação. A pergunta que
ela responde é a primeira da #73: *"que nós eu tenho, e quais estão utilizáveis?"*

### O nó anuncia, o gateway observa

Quando o agente conecta, o `hello` — que até aqui carregava `{"version":
"0.1.0"}` e era **ignorado pelo gateway** — passa a carregar um
`NodeAnnouncement`. O gateway o valida, carimba `capabilities_observed_at` e
grava em `nodes`. Três propriedades desse desenho não são detalhe:

**O anúncio não tem identidade.** Não existe campo `node_id` no payload. O nó é
aquele para o qual o `executor_id` autenticado aponta. A #73 exige que a
identidade *"sobreviva a reconexões e não seja inferida de hostname/IP
mutáveis"*; aceitar um id declarado pelo próprio nó abriria, além disso, o
caminho para um nó reivindicar a linha de outro — que é a falha
anúncio-como-autorização que a issue nomeia.

**O anúncio não concede nada.** `capabilities` no payload é o que a
*configuração daquela máquina* permitiria (`allow_workspace_write`,
`allow_git_delivery`), não o que ele pode fazer a um projeto. Isso continua em
`project_authorizations`, escrito pelo operador. `record_node_announcement` não
toca `enabled`, `health_reason` nem tabela de autorização alguma.

**O anúncio é datado.** Fica gravado *quando* foi observado, e a rota devolve
`inventory_stale`. A #73 pede que *"informação offline/obsoleta seja
visivelmente distinguida de observação corrente"* — sem o carimbo, um inventário
de três semanas atrás é indistinguível de um de agora.

### Três fatos diferentes sob a palavra "engine"

`EngineAvailability` separa o que seria tentador fundir:

| campo | o que afirma | quando muda |
|---|---|---|
| `implemented` | existe um `Runner` no código para esse engine | numa release |
| `available` | o binário respondeu **nesta** máquina | ao instalar/remover a CLI |
| `version` | o que o binário disse de si | ao atualizar a CLI |

Fundir os dois primeiros num só booleano apaga justamente os dois casos que o
operador precisa ver: engine que este build suporta mas esta máquina não tem
(*instale*) e engine presente na máquina que nenhum runner sabe dirigir (*falta
código*). São problemas diferentes, com donos diferentes.

`Runner.probe()` é medição, não declaração — e por isso **nunca levanta
exceção**: um probe que estoura impediria o nó de conectar, e um nó invisível é
pior que um nó com um engine marcado indisponível.

### Saúde é derivada, nunca coluna

`shared.protocol.node_health` é a única derivação, e a ordem dos testes importa:

- nunca visto → `unknown` (não `offline`: "nunca conectou" e "esteve aqui e
  sumiu" são problemas distintos, com correções distintas);
- visto, mas fora da janela de graça → `offline`;
- vivo, porém desabilitado ou com `health_reason` → `degraded`;
- vivo e habilitado → `ok`.

Um nó desligado lê `offline`, não `degraded`: chamar de degradada uma máquina
que está simplesmente apagada inventa um incidente. Nada disso é persistido —
reinício de gateway não pode deixar um nó afirmando saúde que ninguém remediu.

### Caminho nenhum sai daqui

O anúncio carrega `discovery_root_count`, um número, não as raízes. A pergunta
de frota é *"este nó está configurado para descobrir alguma coisa?"*, e um
contador a responde sem publicar o layout de disco da máquina em todo cliente.
Vale a mesma regra da seção "Caminho absoluto" acima.

Desde a Stage 3 (abaixo), `discovery_root_count` é `len(AgentSettings.
discovery_roots)` — a lista real de raízes do nó. A Stage 2 o calculava a
partir de `auto_project_root` (0 ou 1) só porque nenhuma lista de verdade
existia ainda para contar; o próprio docstring de `_build_announcement`
previa essa substituição. `auto_project_root` nunca produziu um relatório de
descoberta nem qualquer outra mensagem ao gateway — é a válvula da camada 7
(`docs/project-onboarding.md`), que só amplia quais `project_id` um despacho
resolve localmente. Contá-la aqui teria respondido "descobre algo?" com um
número para o qual o gateway nunca vê evidência nenhuma.

## Stage 3 — o nó propõe, o painel adota (issue #73)

A Stage 1 criou `discovered_resources` vazia; a Stage 2 fez o nó se anunciar
sem produzir nenhuma linha nela (`discovery_root_count` era só um número). A
Stage 3 é o que faz as raízes de descoberta produzirem linhas de verdade —
sem conceder nada sobre elas. Adotar e decidir candidatos (a rota REST que
lista `discovered_resources` e move `state`) é a próxima PR; esta entrega
apenas a proposta.

### Duas listas de raízes, dois donos, nomes parecidos de propósito

A #73 pede exatamente esta distinção, e um nome parecido é o que faz alguém
tentado a fundir as duas perceber que não deveria:

| lista | onde mora | quem decide | o que ela faz |
|---|---|---|---|
| `AgentSettings.discovery_roots` (nó) | no nó, `agent/codex_bridge_agent/config.py` | o operador **daquela máquina** | quais diretórios este nó varre no próprio disco. Vazia por padrão — sem opt-in, nenhum comportamento novo |
| `ExecutorRegistration.discovery_roots` (operador, `list[DiscoveryRoot]`) | no gateway, `registry.json` | o operador do **registro** | o que cada raiz concede automaticamente (`auto_authorize`), casando por `root_path` — consumido pela próxima PR (adoção), não por esta |

Só o nó pode decidir a primeira — é o filesystem dele. Só o operador do
registro pode decidir a segunda — é ele quem concede. As duas precisam
concordar na **string** `path`/`root_path`, porque o casamento na próxima PR é
por igualdade de string, nunca por resolução: o gateway não enxerga o disco
do nó (mesma razão pela qual `DiscoveryRoot.path` já não era resolvido desde
a Stage 1). É por isso que `DiscoveryReport.root_path` (a mensagem, abaixo) é
exatamente a string configurada no nó, nunca `Path.resolve()`'d.

Uma terceira lista não deveria nunca nascer por acidente aqui — se um dia
parecer necessária, é sinal de que uma das duas acima está sendo esticada
para um papel que não é o dela.

`auto_project_root` (a válvula da camada 7, `docs/project-onboarding.md`)
continua exatamente como está — é uma preocupação diferente: resolve
`project_id` desconhecido no momento do despacho, nunca produz uma mensagem
ao gateway, e não tem relação estrutural com nenhuma das duas listas acima
além da sobreposição de vocabulário ("descoberta").

### `discovery.report`: uma mensagem, não um campo do `hello`

`AgentMessageType.DISCOVERY_REPORT` (`shared/protocol.py`) é deliberadamente
separada de `NodeAnnouncement`. A Stage 2 já documentava que o `hello` carrega
só uma contagem (`discovery_root_count`); um relatório de descoberta pode
carregar centenas de candidatos (247, na raiz real que motivou este
trabalho), e o `hello` viaja a cada reconexão — misturar os dois faria toda
reconexão arrastar esse inventário inteiro consigo. Ver `docs/protocol.md`
para o payload completo.

O nó varre cada raiz num laço próprio (`AgentService._discovery_loop`),
desacoplado do heartbeat de 15s por desenho: `AgentSettings.
discovery_scan_interval_seconds` (padrão 3600s) é a única cadência dessa
varredura. Uma varredura roda logo após o `hello`, depois a cada intervalo. A
varredura em si (`shared.project_discovery.build_project_id_index`, reusando
`walk_for_git_repos`/`suggest_project_id` — o mesmo walk de
`scripts/discover_projects.py` e `resolve_auto_project`, nunca um segundo
scanner) roda em `run_in_executor`: é I/O de filesystem bloqueante, e não pode
travar o heartbeat nem o laço de despacho. **Um envelope por raiz**, nunca um
payload único para todas: uma raiz lenta ou incomumente grande não pode
atrasar o relatório de nenhuma outra.

### `resource_key` é dado sensível — mesma categoria de `local_path`

Na prática, `resource_key` é o path absoluto do candidato no nó — a única
forma de identificá-lo antes de existir um `projects.id` para apontar, e por
isso não é chave estrangeira (mesmo raciocínio que já vale para
`DiscoveredResourceModel.project_id`, nullable). Cai na mesma categoria de
dado sensível que `workspace_bindings.local_path` já ocupa nesta página: um
path absoluto do disco do nó, que só pode aparecer em superfícies de operador
devidamente autorizadas, nunca em `ProjectStatus`, `Session`, `Mission` ou
qualquer ferramenta MCP. Essa exceção para `resource_key` está registrada
aqui e em `docs/api/README.md` ("Fields that must never ship") e
`docs/threat-model.md` — sem isso, a próxima pessoa a expor
`discovered_resources` numa rota reintroduz o vazamento que `local_path` já
evitou uma vez.

**Atualização (WK-20260902-gh73-discovery-adoption, `migrations/
0013_discovery_resource_key_hash.sql`).** O parágrafo acima descreve a coluna
como a PR de relatório a deixou — e é exatamente aí que mora um defeito que
essa PR encontrou e não teve escopo para consertar: `resource_key` é
`varchar(255)`, dimensionado quando a coluna ainda era pensada como um id
curto sugerido, mas passou a receber o path inteiro (até 2048 caracteres,
`DiscoveredCandidate.resource_key`). O SQLite nunca impôs essa largura (é
afinidade de tipo, não restrição), mas `aiomysql` é dependência declarada — e
lá a mesma escrita é `Data too long for column`.

Alargar a coluna não seria o conserto: ela ancora o índice único composto
`(node_id, kind, resource_key)`, e o limite de chave de índice do MySQL
(3072 bytes, ~767 caracteres em `utf8mb4`) é quase certamente o que os 255
originais protegiam — alargar para 2048 trocaria uma falha silenciosa por
outra no mesmo alvo. A forma escolhida: `resource_key` vira
`shared.security.hash_resource_key(path)` — sha256 hex, sempre 64
caracteres, folgado tanto na coluna quanto no limite de índice do MySQL — e
o path de verdade passa a viver em `resource_path`, coluna nova, sem índice,
na mesma largura de 2048 que o protocolo já permitia. `resource_path`, não
`resource_key`, é agora o dado sensível desta seção; `resource_key` é só
uma chave de busca interna, sem relação reversível com o path, e não sai em
DTO nenhum. Ver o comentário da própria migração para o porquê de o backfill
de linhas existentes copiar o path para `resource_path` sem tentar
recalcular o hash em SQL portável — e `store.record_discovery_report`'s
docstring para como uma linha pré-0013 se autorrepara na próxima observação.

Deliberadamente **não** é `suggested_project_id`: `shared.project_discovery.
suggest_project_id` só garante unicidade dentro da varredura de **uma** raiz
(seu `taken` é reiniciado a cada chamada); duas raízes varridas de forma
independente podem sugerir o mesmo id para dois diretórios diferentes. O que
de fato identifica uma linha em `discovered_resources` — e o que uma nova
varredura precisa reconhecer como "o mesmo candidato" — é o path, não a
sugestão.

### Reconciliação de estado: observação nunca é decisão

`store.record_discovery_report` processa um `DiscoveryReport` inteiro (uma
raiz) como um lote, escaneado por `(node_id, kind, resource_key)` contra o
que já existe para `(node_id, root_path)`:

- candidato novo → `INSERT`, `state=DISCOVERED`, `first_seen_at=last_seen_at=now`;
- candidato já existente → atualiza `evidence_json` e `last_seen_at`, e
  **nunca** muda `state` — uma observação repetida não é uma decisão nova do
  operador, então um `ADOPTED` ou `AUTHORIZED` não pode regredir só porque o
  nó reconectou e relatou de novo;
- linha daquele `(node_id, root_path)` ausente do relatório atual, com
  `state != DENIED` → `STALE` — visto antes, não visto agora;
- `DENIED` nunca é tocado por observação, em nenhuma direção: nem regride
  para a fila de adoção por reaparecer (a falha que esta seção nomeou na
  Stage 1: "candidato recusado volta à fila de adoção a cada reconexão"), nem
  tem sua evidência atualizada — uma linha negada simplesmente para de se
  mover quando o operador decide;
- uma linha `STALE` que reaparece **não** volta a `DISCOVERED` por padrão: se
  já havia binding/autorização ativos antes de ficar `STALE`, ela volta para
  `ADOPTED`/`AUTHORIZED`; só cai em `DISCOVERED` quando não havia decisão
  nenhuma sobre ela. Hoje, como nada nesta PR ainda escreve
  `discovered_resources.project_id` (isso é da PR de adoção), todo caso
  prático cai em `DISCOVERED` — a lógica para os outros dois já existe porque
  a linha sobre a qual ela vai operar já existe hoje.

O upsert é em lote: um único `select` carrega tudo que já existe para aquele
`(node_id, root_path)`, o laço só muda objetos ORM em memória, e há um único
`commit` — um relatório de 247 candidatos custa uma consulta e um commit, não
247 de cada.

### O que esta PR deliberadamente não faz

Nenhuma rota REST lê ou decide `discovered_resources` — listar candidatos e
adotá-los é a PR seguinte. Por isso `API_CONTRACT_VERSION` não muda aqui. E o
branch que recebe `discovery.report` no gateway chama **só**
`store.record_discovery_report`, que escreve **só** em
`discovered_resources` — nunca em `project_authorizations`, `projects` nem
`workspace_bindings`. Isso é o que torna "o nó propõe, o painel adota"
verdade por construção: o caminho que recebe uma descoberta não tem, no
código, nenhum jeito de chegar a uma tabela de autorização.

## Stage 3 — a metade de adoção (issue #73, WK-20260902-gh73-discovery-adoption)

A seção anterior descreveu a PR que fez o nó propor. Esta é a PR seguinte que
ela previa: `GET /api/v1/nodes/{nodeId}/discovered-resources`,
`POST /api/v1/discovered-resources/{resourceId}/adopt` e
`POST .../{resourceId}/deny` — o único caminho, em todo o código, de uma
linha de `discovered_resources` para `projects`, `workspace_bindings`,
`scm_associations` ou `project_authorizations`.

### O invariante não muda de lado — só ganha uma porta

`store.record_discovery_report` continua escrevendo só em
`discovered_resources`, inalterado nesta PR além do ajuste de
`resource_key`/`resource_path` (seção acima). `store.
adopt_discovered_resource` e `store.deny_discovered_resource` são as únicas
funções novas com acesso de escrita às outras quatro tabelas, e as duas só
são alcançáveis por `gateway/app/api/routes/discovery.py`, atrás de
`permissions.NODES_DISCOVERIES_DECIDE` — uma ação administrativa que exige
`AuthenticatedPrincipal`, e `current_principal` só produz um a partir de um
token OAuth. O `machine_token` do executor autentica exclusivamente o
WebSocket (`gateway/app/main.py:agent_ws`) e nunca vira um principal REST —
não há, por construção, nenhuma sequência de chamadas que leve da conexão de
um nó até `adopt`/`deny`. É isso que mantém "um nó não se autoriza sozinho"
verdadeiro depois desta PR existir, não apenas antes dela: o teste que prova
isso é `tests/unit/test_discovery_store.py::
test_a_matching_auto_authorize_root_grants_nothing_from_a_report_alone`, que
roda com uma raiz `auto_authorize` de verdade configurada e mostra que
`record_discovery_report` sozinho não a usa — só `adopt_discovered_resource`
usa, e só um humano chega lá.

### `adopt`: cria ou reusa projeto, e a concessão automática tem teto

Corpo `{projectId?, newProject?: {projectId, name}, grantCapabilities?}` —
exatamente um de `projectId`/`newProject`. Cria (ou reusa)
`ProjectModel`, cria/atualiza `WorkspaceBindingModel` com `local_path` =
`resource_path` do candidato, cria `ScmAssociationModel` com
`confidence="observed"` quando a evidência do candidato carrega
`remote_url`, e move `discovered_resources.state` para `adopted` ou
`authorized`.

A concessão automática (a partir de `ExecutorRegistration.discovery_roots` —
a lista do operador do registro, não a do nó; ver a seção "Duas listas de
raízes" acima) entra em jogo quando `root_path` da linha casa, por igualdade
de string, uma entrada com `auto_authorize`: essa concessão é
gravada com `granted_by="root-config:<path>"`. Um `grantCapabilities`
explícito no corpo é gravado com `granted_by="operator:<user_id>"`. As duas
podem valer na mesma chamada de adoção — `project_authorizations_node_
project_idx` permite só uma linha não revogada por `(node_id, project_id)`,
então as duas origens se fundem numa linha só (`capabilities_json` vira a
união, `granted_by` vira um conjunto `;`-separado de origens) em vez de
competir pelo índice único. `AUTO_AUTHORIZABLE_CAPABILITIES` continua
limitando `auto_authorize` a `read`/`test`, validado no parse de
`DiscoveryRoot` — antes de qualquer nó conectar, muito antes de qualquer
adoção. `modify`/`deliver` só chegam a uma linha de autorização por
`grantCapabilities`, nomeando um operador.

### `deny`: um sexto estado não nasce por acidente

Move `state` para `denied`, grava `decided_by`/`decided_at`. "Ignorar" fica
sendo filtro de UI sobre `discovered`/`stale` — `shared.protocol.
DiscoveredState` continua com cinco valores, e nenhuma rota desta PR grava um
sexto. A regra que a Stage 1 nomeou e a PR de relatório implementou —
`DENIED` nunca regride por observação — continua valendo depois desta PR:
`adopt`/`deny` só agem sobre uma linha em `discovered`/`stale`
(`DECIDABLE_DISCOVERY_STATES`), e uma linha já `denied` responde `409` em vez
de ser tocada de novo.

### Por que `409`, não sobrescrita silenciosa

`adopt`/`deny` só decidem uma linha `discovered`/`stale`. Uma linha já
`adopted`/`authorized`/`denied` é uma decisão já tomada — decidi-la de novo
responde `409 conflict`. Isso não é um defensive check em cima da escrita: é
o que impede uma segunda chamada de `adopt` de duplicar o
`WorkspaceBindingModel`/`ScmAssociationModel` que a primeira já produziu —
a segunda chamada nunca chega à escrita.

## Stage 4 — o plano de autorização passa a valer (issue #73, WK-20260902-gh73-authorization-plane)

Até aqui, `project_authorizations` só recebia escritas — Stage 1 criou a
tabela e o vocabulário, Stage 3 fez a adoção gravar nela pela primeira vez.
Nenhum código **lia** essa tabela para decidir o que um dispatch podia fazer:
uma autorização concedida não mudava nada, na prática. Esta PR fecha esse
buraco, em dois lugares — o gateway e o executor — sem criar um segundo ponto
de verdade em nenhum dos dois.

### O gate estreita `allowed_modes`, nunca o substitui

O único enforcement de modo, hoje como antes, é um `if` em
`gateway/app/services/store.py::create_task`. O que muda é que a lista
consultada por esse `if` passa a ser calculada por
`store.effective_task_modes(session, executor, project)`, em vez de ser lida
direto de `project.config_json["allowed_modes"]`:

1. `base` = os modos de `allowed_modes` do projeto — exatamente o que
   `create_task` já lia antes desta PR;
2. se o par `(executor.node_id, project.id)` **não tem** linha em
   `workspace_bindings`, a resposta é `base`, sem mudança nenhuma. Isto não é
   um período de graça: é permanente, para sempre, para qualquer par que
   nunca passou pela adoção — a mesma garantia que a migração `0009` já
   registrou por escrito ("access continues flowing through the pre-existing
   `allowed_projects`"). Até esta PR, essa frase era só uma promessa em
   comentário; `tests/unit/test_effective_task_modes.py::
   test_no_binding_returns_the_project_base_unchanged` e `test_create_task_
   for_an_unbound_pair_behaves_exactly_as_before_this_pr` são os primeiros
   testes que a provam contra código de verdade;
3. se tem binding, a resposta é `base` interseccionado com
   `capabilities_to_modes(...)` da linha ATIVA (`revoked_at is null`) de
   `project_authorizations` para aquele par. Nenhuma linha = nenhuma
   capacidade = conjunto vazio — adoção sozinha não autoriza nada, exatamente
   como a Stage 3 já dizia.

A interseção nunca alarga o que `allowed_modes` já permitia — só pode
estreitar. `project_authorizations` tira, nunca acrescenta, por nó.

### A checagem espelhada no executor

`agent/codex_bridge_agent/service.py::_handle_dispatch` ganha seu próprio
gate, logo depois de montar o `SubmitTaskRequest` do dispatch: computa as
`Capability` que a configuração DESTE executor permite
(`_configured_capabilities`, o mesmo cálculo que `_build_announcement` já
fazia para o `hello` — fatorado numa função só para as duas nunca divergirem),
deriva `capabilities_to_modes(...)`, e recusa com
`capability_not_configured:<mode>` se o modo do dispatch não estiver nesse
conjunto.

Isto não duplica o gate do gateway — protege contra um gateway comprometido
ou com bug mandando um modo que este nó específico nunca se ofereceu para
rodar, o mesmo raciocínio de defesa em profundidade que `git_delivery.py` já
aplica reconferindo o padrão de branch que o gateway já validou. As duas
checagens são independentes: `tests/unit/test_agent_service.py::
test_handle_dispatch_refuses_a_write_mode_when_workspace_write_is_off` prova
que o executor recusa um modo mesmo quando nada no payload do dispatch diz
que o gateway não aprovou.

### Conceder e revogar: `gateway/app/api/routes/authorizations.py`

`POST /api/v1/nodes/{nodeId}/projects/{projectId}/authorize` (corpo
`{capabilities: [...]}`) e `POST .../revoke` — a metade explícita, fora do
fluxo de descoberta, de escrever `project_authorizations`. Separado de
`routes/discovery.py` porque as duas são ações distintas com pré-condições
distintas: adoção exige uma linha de `discovered_resources` para agir; isto
exige só um nó e um projeto que já existam.

`store.grant_project_authorization` faz get-or-create pelo par
`(node_id, project_id)` — a constraint única já garante no máximo uma linha
não revogada. Se a linha existir revogada, REATIVA (limpa `revoked_at`,
sobrescreve `capabilities_json`/`granted_by`/`granted_at`) em vez de inserir
uma segunda. Diferente de `_grant_project_authorization` (o helper interno da
adoção, que só funde capacidades e nunca revoga), esta é a superfície do
operador: uma chamada aqui declara a autorização que o operador quer AGORA,
não soma ao que já havia. `store.revoke_project_authorization` marca
`revoked_at`; a linha nunca é apagada, e um `grant` seguinte reativa a mesma
linha. O histórico completo — cada concessão, cada revogação — vive em
`audit_events` via `record_event`, como todo o resto deste sistema;
`tests/unit/test_effective_task_modes.py::
test_revoke_then_regrant_reuses_the_same_row` prova a linha única e os dois
tipos de evento.

### A escada de privilégio, e por que ela não pode reusar `principal.is_admin()`

`permissions.NODES_AUTHORIZATIONS_MANAGE` é administrativa, `codexbridge.admin`
— a mesma classe que `NODES_READ`/`NODES_DISCOVERIES_DECIDE` já usam. Conceder
`modify` ou `deliver` exige uma condição a mais, aplicada dentro de
`permissions.is_allowed` (nunca num `if` solto na rota): `principal.
can_approve_sensitive or "admin" in principal.roles`.

Note que essa condição NÃO chama `principal.is_admin()`, ao contrário do
segundo portão de `DECISIONS_DECIDE` — e essa diferença é deliberada, não um
descuido. `is_admin()` é `"admin" in principal.roles or "codexbridge.admin"
in principal.scopes`. O escopo de `DECISIONS_DECIDE` é
`codexbridge.task.approve`, disjunto de `codexbridge.admin`, então ali
`is_admin()` acrescenta uma condição de verdade. Mas o escopo BASE de
`NODES_AUTHORIZATIONS_MANAGE` já É `codexbridge.admin` — então, para esta
ação, `principal.has_scope(action.scope)` e `principal.is_admin()` são O
MESMO PREDICADO: qualquer principal que passa pelo portão de base já teria
passado por um segundo portão baseado em `is_admin()`, tornando esse segundo
portão tautológico e o `can_approve_sensitive` irrelevante — exatamente a
escalada que este portão existe para fechar. `tests/integration/
test_authorization_routes.py::
test_granting_modify_without_can_approve_sensitive_or_admin_role_is_refused`
prova isso com um principal que tem só o escopo `codexbridge.admin` (sem
papel `admin`, sem `can_approve_sensitive`) sendo recusado; os dois testes de
controle positivo ao lado provam que `can_approve_sensitive` sozinho e o
papel `admin` sozinho, cada um isoladamente, já bastam.

### O que ainda não muda

A allowlist local do agente (`AgentSettings.allowed_projects_file`, ou o
registro estático em `agent.codex_bridge_agent.config`) continua existindo e
continua sendo consultada — esta PR não a remove nem a substitui.
`project_authorizations` estreita o que já era permitido por
`allowed_modes`/allowlist local; nunca alarga. Ver
`docs/project-onboarding.md` para o que muda no fluxo operacional de cadastro
de projeto e o que continua manual.
