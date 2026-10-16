# Contrato proposto — Worker de controle por branch (v0)

- Data: 2026-10-16
- Work ID: WK-20261016-worker-control-branch-contract
- Roteiro de implementação: [worker-implementation-plan.md](./worker-implementation-plan.md)
- Estado: **proposta aprovada conceitualmente; não implementada nem implantada**
- Escopo desta alteração: documentação **somente** no repositório CodexBridge.
- Classificação: desenho **aditivo**, com implicações **security-sensitive** e possível **contract-change** na implementação futura. Nenhum contrato MCP/REST/WebSocket em produção é alterado por este documento.

## Objetivo

Oferecer uma via complementar ao MCP para enviar ordens de operação a partir de
ChatGPT Pro através do GitHub. Cada Project lógico autorizado está associado a
seu próprio repositório GitHub; o canal de ordens desse projeto é uma **branch
dedicada de controle no próprio repositório**, e não uma branch central no
repositório CodexBridge.

O Worker observa exclusivamente branches de controle de projetos ativados.
Ele **não** executa operações no workspace, não se comunica diretamente com
Nodes e não decide sozinho a autorização: encaminha a intenção ao **CodexBridge
Gateway (Frida)**, que autoriza, persiste, coordena e despacha aos Executores
conectados pelos canais reversos existentes. O MCP continua disponível para
consulta e, conforme capacidades do cliente, outras operações; a branch não
substitui o MCP.

## Identidades e responsabilidades

- **ChatGPT**: escreve solicitações declarativas na branch de controle do
  repositório do projeto, usando a integração GitHub disponível; consulta
  resultados na branch ou por ferramentas MCP de leitura quando efetivamente
  conectadas.
- **GitHub**: transporte assíncrono por branch dedicada **por projeto**; não é
  fonte de autoridade nem de autorização para executar.
- **Worker de controle** (apelidado inicialmente de "Worker Slave"): observa
  solicitações dos projetos habilitados, valida a forma do envelope, deduplica,
  autentica-se perante o Gateway e publica projeções leves dos resultados na
  branch correspondente. É um adaptador de transporte, não um Executor.
- **Gateway em Frida**: autoridade única por projeto, missão, operação e estado;
  resolve Project, Nodes, Workspace Bindings e capacidades; valida concessões,
  cria execução por destino; recebe logs e estados do Executor; disponibiliza
  um resumo consultável.
- **Bridge Node**: máquina registrada, por exemplo devel3 ou iMac.
- **Executor**: conexão/processo autenticado de um Node com o Gateway, que
  realiza apenas operações permitidas para aquele Project naquele Node.
  Nenhum Worker fala diretamente com um Executor.
- **Engine**: agente de desenvolvimento selecionado dentro de um Executor,
  quando a operação exigir IA. Não se confunde com Node ou Worker.

Invariante operacional: **ChatGPT → GitHub → Worker → Gateway → Executor/Node
→ Gateway → Worker → GitHub**. Em paralelo, **ChatGPT ↔ Gateway pelo MCP**
para leitura/consulta, quando a conexão MCP estiver disponível.

## Ativação limitada de projetos

1. Um Worker observa **no máximo três Projects distintos simultaneamente**
   (uma branch dedicada de controle por Project).
2. Cada ativação dura **oito horas corridas desde a aprovação/ativação**
   (ex.: 12:00–20:00), não 24 horas nem "até o fim do dia".
3. Terminadas as oito horas: parar de coletar novas solicitações e de admitir
   novos despachos/execuções decorrentes dessa ativação; **sem renovação
   automática**. Solicitações não iniciadas expiram de forma explícita.
4. Operações já iniciadas antes da expiração podem apenas concluir sua
   execução atual dentro dos respectivos limites de tempo, sem desencadear
   trabalho novo. Seu resultado pode ser drenado e publicado; isso **não**
   reativa o monitoramento. Cancelamento seguro de operações em andamento é
   uma decisão separada, não inferida do simples vencimento da ativação.
5. Desativação manual bloqueia imediatamente novas admissões. Reativação para
   o período seguinte exige ato explícito do operador.
6. O limite de **três Projects** não limita a quantidade de **Nodes** que podem
   executar uma solicitação autorizada.
7. O primeiro controle de ativações pode ser um **CLI Python**, sem painel
   web/app; o Gateway deve continuar sendo a autoridade de autorização, para
   permitir que Control e Mobile façam a mesma operação futuramente.

Interface de CLI **proposta, ainda não implementada**:

~~~text
workerctl enable --project <project-id> --hours 8
workerctl list
workerctl disable --project <project-id>
~~~

A referência da branch de controle deve estar registrada na associação
Project↔repositório; os comandos não aceitam um path de workspace.

## Branch e esquema de arquivos

Nome recomendado, igual em todos os repositórios: `codexbridge-control`
(nome configurável, decidido na adoção). Ela é persistente, **não é branch de
implementação e não deve ser mesclada em development**. As branches de código
continuam seguindo o fluxo `development → feature → testes → merge`.

~~~text
# Dentro da branch codexbridge-control de CADA repositório GitHub
.codexbridge/
  requests/
    <request-id>.json
  results/
    <request-id>/
      summary.json
      <node-id>--<hostname>/
        <attempt-id>/
          result.json
          tests.txt
~~~

- Request é imutável após aceitação. Cada `request-id` é único e idempotente
  por projeto. Não se sobrescrevem resultados de tentativas antigas.
- `node-id` é a identidade estável autenticada pelo Gateway; `hostname` é
  metadado legível, pode mudar ou repetir entre máquinas; o diretório combina
  os dois de modo sanitizado e sem depender apenas do hostname.
- O **Worker é o único componente CodexBridge que escreve resultados** na
  branch. As gravações são serializadas ou têm controle otimista de SHA/retry
  para não perder resultados de execuções concorrentes.
- O estado e a auditoria autoritativos permanecem no Gateway. A branch contém
  projeções de transporte e consulta, não um segundo banco operacional.
- **Fora do MVP:** APKs, binários, pacotes, logs grandes, anexos e um depósito
  de artefatos. Publicar apenas evidências textuais pequenas, com limites
  explícitos de tamanho e sanitização de segredos.

## Uma solicitação, N execuções, um resultado consolidado

A solicitação declara o Project lógico, a operação **enumerada e autorizável**,
uma revisão de código imutável, e os destinos. Não transmite shell ou caminho
local arbitrário; compilar Android é apenas **um exemplo**, não o caso central.

~~~json
{
  "schemaVersion": 1,
  "requestId": "req-example-001",
  "project": "example-project",
  "operation": "test",
  "source": { "branch": "feature/example", "commit": "<full-commit-sha>" },
  "targets": { "mode": "selected", "nodes": ["devel3", "imac"] },
  "parameters": {}
}
~~~

- `targets.mode = selected`: um ou mais IDs de Node explicitamente indicados.
  `targets.mode = all`: conjunto de todos os Nodes registrados **e elegíveis**
  para o Project/operação, resolvido e congelado no Gateway ao admitir o
  pedido. "Todos" nunca significa todos os hosts da rede ou todos os Nodes
  sem autorização. Não selecionar destino diferente como fallback silencioso.
- O Gateway verifica autorização e capacidade **por par Project–Node**. Um
  destino indisponível, não autorizado ou incompatível recebe estado/razão
  explícitos, não desaparece do consolidado.
- Todos os destinos da mesma solicitação recebem o **mesmo commit SHA
  verificado**; não seguir HEAD móvel para obter "última versão" durante o
  fan-out.
- Cada Node produz uma ou mais tentativas identificadas de forma independente.
  Falha em um Node não apaga o sucesso de outro.
- O resumo é calculado sobre o conjunto congelado de destinos, com estados
  individuais (pending, running, completed, failed, unavailable,
  unsupported, denied, expired) e estado consolidado (completed, partial,
  failed ou expired), incluindo indicação de conclusão da fila.
- Uma solicitação só fica concluída quando todos os destinos chegarem a um
  estado terminal; expiração da ativação não mascara trabalho já iniciado.
- Resultado mínimo por tentativa: `requestId`, `project`, `nodeId`,
  `hostname`, `attemptId`, `operation`, `commit`, início/fim,
  `status`, código de saída (quando aplicável), resumo e evidências textuais
  **limitadas e redigidas**.

## Segurança, limite de confiança e extensibilidade

1. A existência de JSON na branch não prova autorização. O Gateway verifica
   identidade do operador, acesso ao Project, permissão da operação, vínculo
   do workspace, Node, validade da janela de oito horas e aprovação sensível.
   Metadados Git de autor/committer não são substitutos para autenticação.
2. Worker usa credencial própria, de menor privilégio, limitada ao transporte
   e à publicação de resultados; nunca recebe credenciais de Executor ou
   acessa diretamente repositórios locais do Node.
3. Comandos possíveis vêm de catálogo/política explícita por projeto/nó:
   analisar, testar, compilar, verificar, etc. **Nada de shell arbitrário**
   originado de um arquivo GitHub. Operações sensíveis exigem autorização.
4. Um request repetido não dispara novamente por repetição de polling,
   reconexão ou commit. Transições são idempotentes e auditadas no Gateway.
5. Se GitHub, Worker, Gateway ou Executor ficar offline, registrar erro/estado
   verificável; nunca alegar execução bem-sucedida sem evidência.
6. Resultados na branch não contêm tokens, secrets, caminhos privados,
   environment dumps, dados pessoais nem stdout/stderr sem filtragem.
7. A publicação de resultados fora da validade serve apenas para **encerrar**
   solicitações admitidas durante a ativação, sem permitir novos pedidos.
8. Control (web) e CodexBridge Mobile são **futuras interfaces de gestão**
   dessas mesmas ativações/autorização, não uma segunda autoridade.

## Critérios de aceite para uma implementação futura

- Habilitar até três projetos por oito horas, recusar o quarto; comprovar
  expiração automática e renovação apenas manual.
- Receber ordem em uma branch de controle de um único projeto; o Worker
  encaminha ao Gateway, que escolhe Node(s) conforme autorização vigente.
- Executar a mesma revisão em um, dois ou todos os Nodes elegíveis, e produzir
  resultados isolados por Node/hostname/tentativa sem colisão.
- Comprovar que o Worker **nunca** despacha a um Executor por fora do Gateway.
- Consultar resumo e estados pelo Gateway/MCP de leitura quando conectado e,
  alternativamente, pelo GitHub na branch de controle.
- Não incluir binários/artefatos pesados, nem executar shell arbitrário.
- Testar casos de Node offline, sem capacidade, sem autorização, request
  duplicado, concorrência de gravação, expiração da ativação e falha parcial.
- Preservar ferramentas e contratos MCP/REST/WebSocket existentes; qualquer
  alteração nesses protocolos terá proposta e revisão de segurança próprias.

## Fora do escopo da presente atualização

Nenhum script, Worker funcional, endpoint, migration, job, alteração na branch
de controle de outro repositório, teste de runtime, merge ou deploy é feito.
Este documento fixa a **intenção de contrato**, não declara entrega funcional.
