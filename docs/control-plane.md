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
