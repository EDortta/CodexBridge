# CodexBridge — plano incremental para avançar pelo ChatGPT

Data: 2026-09-14  
Branch de trabalho atual: `feature/control-ui-and-mobo-orch`  
Objetivo operacional: permitir que um operador use ChatGPT/MCP para dar ordens de desenvolvimento a um Bridge Node específico, sobre um Project lógico autorizado, sem expor paths/credenciais e sem transformar o gateway em shell remoto.

## 0. Como usar este documento

Este documento foi escrito para ser executado paulatinamente em conversas futuras com ChatGPT/Claude/CodexBridge. Cada etapa tem:

- **Contexto**: por que a etapa existe.
- **Entrada para o chat**: prompt curto que pode ser colado em uma sessão futura.
- **Arquivos prováveis**: onde mexer primeiro.
- **Critério de aceite**: como saber se a etapa acabou.
- **Testes mínimos**: comandos que devem ficar verdes antes de avançar.

Regra de ouro: não pule etapa P0/P1. As etapas posteriores dependem da base de segurança/autorização estar estabilizada.

## 1. Estado atual conhecido

### 1.1 Worktree

Na branch `feature/control-ui-and-mobo-orch`, há alterações locais em andamento cobrindo:

- Control/UI e adoption:
  - `gateway/app/api/routes/control_ui.py`
  - `tests/integration/test_control_ui.py`
- MCP/ChatGPT entry:
  - `gateway/app/mcp/server.py`
  - `gateway/app/mcp/tools.py`
  - `tests/integration/test_start_development_task.py`
  - `tests/integration/test_store_and_mcp.py`
  - `tests/integration/test_smoke.py`
- Store/autorização:
  - `gateway/app/services/store.py`
  - `tests/unit/test_discovery_store.py`
- Engine registry / runners:
  - `agent/codex_bridge_agent/runners/registry.py`
  - `agent/codex_bridge_agent/runners/pool.py`
  - `tests/unit/test_runner_registry.py`
- Segurança/redaction:
  - `shared/security.py`
  - `gateway/app/api/routes/sessions.py`
- Agente/reconnect:
  - `agent/codex_bridge_agent/service.py`
  - `tests/unit/test_agent_service.py`
- Docs/config:
  - `.env.example`
  - `docs/chatgpt-registration.md`
  - `docs/protocol.md`
  - `gateway/app/core/config.py`

Artefatos locais que **não devem ser commitados** sem decisão explícita:

- `.claude-flow/`
- `.swarm/`
- `ruvector.db`
- `claude-handoff-*.md`
- `coordination-status-*.txt`

### 1.2 Testes focados já verdes neste corte

Comando rodado:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/unit/test_runner_registry.py \
  tests/unit/test_agent_service.py \
  tests/integration/test_start_development_task.py \
  tests/integration/test_store_and_mcp.py \
  tests/integration/test_control_ui.py \
  tests/integration/test_smoke.py
```

Resultado observado:

```text
126 passed, 1 warning
```

### 1.3 Correção recente importante

Foi encontrada e corrigida uma falha no caminho Control adoption → MCP dispatch:

- Problema: projeto criado por `adopt_discovered_resource()` nascia com `config_json="{}"`.
- Efeito: `effective_task_modes()` via `allowed_modes` retornava conjunto vazio, mesmo com grant `read`.
- Correção: projeto novo criado por adoption agora serializa defaults de `ProjectRegistration`, preservando `allowed_modes`.

Essa correção está em:

- `gateway/app/services/store.py`

## 2. Issues que orientam o plano

### Núcleo de orquestração / MOBO

- **#40** — Epic: transformar CodexBridge em development orchestrator.
- **#41** — contrato genérico de provider/agent.
- **#42** — descoberta de ferramentas, agents e capacidades.
- **#43** — aggregate durável de Mission e state machine.
- **#44** — issue-to-mission workflow.
- **#49** — branches/worktrees/concurrency por mission.
- **#51** — completion/testing/delivery contract.
- **#53** — MOBO orchestration commands/status/events.
- **#58** — multi-agent authorized mode com critique/council.

### ChatGPT/MCP e Control

- **#63** — ChatGPT-facing conversational control plane.
- **#73** — CodexBridge Control: fleet, nodes, adoption e authorization plane.
- **#78** — MCP tools para epics/issues locais.
- **#79** — forge binding per project.
- **#80** — decidir quem fala com forge: sandbox egress vs operação estreita do executor.
- **#81** — terminology pass.

## 3. Invariantes que não podem ser quebrados

1. **Project não é path**  
   ChatGPT/MOBO nunca deve mandar path local. Deve mandar Project lógico.

2. **Node não é executor**  
   Bridge Node identifica a máquina/instalação. Executor é conexão/protocolo. O roteamento pode resolver Node → executor elegível, mas não fundir conceitos.

3. **Discovery não é autorização**  
   Nó pode descobrir recurso; só operador/gate pode autorizar operação.

4. **Binding não é authorization**  
   WorkspaceBinding diz onde o projeto existe naquele Node. ProjectAuthorization diz o que o Node pode fazer.

5. **Explicit Node routing é fail-closed**  
   Se a frase nomeia `devel3`, não pode cair em outro node online. Se faltar binding/autorização/capability, deve negar sem criar Task.

6. **Gateway não vira shell remoto**  
   Operações devem ser enumeradas, auditáveis e autorizadas. Nada de path arbitrário ou comando arbitrário vindo do cliente.

7. **Credenciais não entram no prompt do coding agent**  
   Especialmente para forge/GitHub. A direção de #80 é operação estreita do executor, não sandbox com token e egress amplo.

8. **Resultado MCP é projeção segura**  
   MCP pode expor resultado verificável, mas não command raw, raw provider events, snapshots Git crus, session ids internos, paths sensíveis ou tokens.

## 4. Plano incremental

---

# P0 — Congelar e validar o corte atual

## Contexto

Antes de avançar para novas features, estabilizar o corte já feito: engine registry extensível, explicit Node routing, authorization guard, result privacy e smoke tests.

## Entrada para o chat

> Continue em CodexBridge a partir de `docs/chatgpt-incremental-execution-plan.md`. Execute P0: revise o diff atual, separe artefatos locais que não devem ser commitados, rode a regressão focada e depois uma regressão maior possível. Não implemente feature nova antes de reportar o estado.

## Arquivos prováveis

- `agent/codex_bridge_agent/runners/registry.py`
- `agent/codex_bridge_agent/runners/pool.py`
- `gateway/app/mcp/server.py`
- `gateway/app/services/store.py`
- `tests/integration/test_smoke.py`

## Checklist

- [ ] `git status --short` revisado.
- [ ] Confirmado que `.claude-flow/`, `.swarm/`, `ruvector.db`, handoffs e coordination-status não serão commitados.
- [ ] Diff revisado para alterações acidentais.
- [ ] Testes focados verdes.
- [ ] Regressão maior rodada ou motivo registrado para não rodar.
- [ ] Commit planejado ou criado com escopo claro.

## Testes mínimos

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/unit/test_runner_registry.py \
  tests/unit/test_agent_service.py \
  tests/integration/test_start_development_task.py \
  tests/integration/test_store_and_mcp.py \
  tests/integration/test_control_ui.py \
  tests/integration/test_smoke.py
```

Se possível:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider
```

## Critério de aceite

O corte atual está verde e pronto para commit/review, sem artefatos locais indesejados.

---

# P1 — Fechar o contrato mínimo: “em devel3, faça X no wa-hub”

## Contexto

Este é o primeiro fluxo funcional mínimo para ChatGPT/MCP + Control:

> `@CodexBridge, em devel3, verifique as issues locais que não resolvemos ainda no wa-hub`

Mesmo antes de existir ferramenta nativa de listar issues locais, o sistema precisa provar que resolve Node/Project corretamente e despacha ao executor certo.

## Entrada para o chat

> Execute P1 do plano. Garanta, com testes de integração, que `start_development_task` com `node=devel3` e `project=wa-hub` resolve o Node correto, exige binding ativo e autorização ativa, nunca cai em outro Node, não expõe paths e cria Task apenas nos casos permitidos.

## Arquivos prováveis

- `gateway/app/mcp/server.py`
- `gateway/app/mcp/tools.py`
- `gateway/app/services/store.py`
- `tests/integration/test_start_development_task.py`
- `tests/integration/test_control_ui.py`
- `tests/integration/test_smoke.py`

## Checklist

- [ ] Resolver `devel3` por id/nome/prefixo único de Node.
- [ ] Resolver `wa-hub` por project id/nome/prefixo único.
- [ ] Rejeitar Node ambíguo.
- [ ] Rejeitar Project ambíguo.
- [ ] Rejeitar Node inexistente.
- [ ] Rejeitar Project não visível ao principal.
- [ ] Rejeitar Project não onboarded naquele Node.
- [ ] Rejeitar binding ausente.
- [ ] Rejeitar binding inativo.
- [ ] Rejeitar authorization ausente/revogada.
- [ ] Rejeitar capability incompatível com `mode`.
- [ ] Não criar Task nas recusas.
- [ ] Retornar `node_id`, `executor_id`, `project_id`, `task_id` no sucesso.
- [ ] Não retornar `local_path`/path local.

## Testes mínimos

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/integration/test_start_development_task.py \
  tests/integration/test_control_ui.py \
  tests/integration/test_smoke.py
```

## Critério de aceite

Uma chamada MCP equivalente ao exemplo seleciona inequivocamente `devel3` e `wa-hub`, cria Task apenas se binding/autorização/capability permitirem e nunca vaza path.

---

# P2 — Implementar tools MCP para issues/epics locais (#78)

## Contexto

Hoje `start_development_task` consegue despachar uma tarefa que pergunta ao agente sobre issues. Mas a pergunta “quais issues locais estão abertas?” deveria ser respondida de forma estruturada pelo gateway quando as issues são locais.

Issue guia: **#78**.

## Entrada para o chat

> Execute P2 do plano, issue #78. Implemente tools MCP para listar/criar/atualizar issues e epics locais usando as tabelas existentes, sem schema novo. Reuse autorização REST, `store.resolve_project_reference`, idempotency e ids `local:<id>`. Comece por listagem de issues abertas de um projeto.

## Escopo recomendado para primeiro corte

Não tentar fazer tudo de uma vez. Primeiro corte:

1. `list_project_issues`
   - input: `project`, filtros opcionais `status`, `epic`, `limit`.
   - output: lista estruturada de issues locais.
2. `list_project_epics`
   - input: `project`.
   - output: epics locais.

Segundo corte:

3. `create_project_issue`
4. `create_project_epic`
5. `update_project_issue`
6. `move_project_issue`

## Arquivos prováveis

- `gateway/app/mcp/tools.py`
- `gateway/app/mcp/server.py`
- `gateway/app/services/store.py`
- `tests/integration/test_mcp_epics_issues.py`
- `tests/integration/test_store_and_mcp.py`

## Requisitos

- [ ] Project resolution aceita id/nome/prefixo único, nunca path.
- [ ] Principal sem project em `allowed_projects` recebe erro tipado.
- [ ] Admin pode operar conforme regras atuais.
- [ ] IDs expostos mantêm formato `local:<id>`.
- [ ] Repeated create com mesma idempotency key não duplica.
- [ ] Issue local criada pode ser usada depois em `start_development_task(issue="local:<id>")`.
- [ ] Sem deleção destrutiva no primeiro corte.

## Testes mínimos

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/integration/test_mcp_epics_issues.py \
  tests/integration/test_store_and_mcp.py
```

## Critério de aceite

ChatGPT/MCP consegue responder, sem chamar coding agent, quais issues locais abertas pertencem a um Project autorizado.

---

# P3 — Unificar “listar issues” entre local e forge, bloqueado por #80/#79

## Contexto

A frase do operador não deve mudar dependendo de onde as issues vivem:

> “lista as issues abertas do wa-hub”

Se o projeto não tiver forge binding, responde das tabelas locais. Se tiver forge binding, responde do forge. Mas isso depende da decisão de #80.

## Entrada para o chat

> Execute P3 somente depois de P2 e depois de decidir #80. Primeiro registre a decisão de #80: forge egress pelo sandbox ou operação estreita do executor. A recomendação do plano é operação estreita do executor. Depois implemente #79 para listar issues do forge quando o Project estiver bound.

## Decisão recomendada para #80

Escolher operação estreita do executor:

- executor guarda credential;
- coding agent não recebe token;
- gateway não guarda token;
- operação é enumerada: list/open/comment/close/etc.;
- writes são `sensitive` e passam por policy/human gate.

## Arquivos prováveis

- `agent/codex_bridge_agent/service.py`
- `agent/codex_bridge_agent/forge/*`
- `gateway/app/mcp/server.py`
- `gateway/app/mcp/tools.py`
- `gateway/app/services/store.py`
- `shared/protocol.py`
- `shared/policy.py`
- docs:
  - `docs/security.md`
  - `docs/architecture.md`
  - `docs/protocol.md`

## Requisitos

- [ ] Registrar decisão #80 em docs.
- [ ] Testar empiricamente se sandbox `workspace-write` tem ou não egress, se ainda não feito.
- [ ] Garantir que credential de forge não aparece em env do coding agent.
- [ ] Implementar operation envelope executor-owned.
- [ ] `list_project_issues` escolhe local vs forge pelo binding do Project.
- [ ] Texto vindo do forge tratado como untrusted/provenance separated.
- [ ] Forge write passa por policy sensitive.

## Critério de aceite

A mesma tool/frase lista issues locais ou forge issues conforme o binding do Project, sem expor credenciais ao gateway, ao client ou ao coding agent.

---

# P4 — Mission aggregate real (#43)

## Contexto

Enquanto tudo for apenas `TaskModel`, CodexBridge ainda não é o orchestrator de desenvolvimento completo da #40. Uma Mission precisa sobreviver a múltiplas tasks/attempts/reviews.

## Entrada para o chat

> Execute P4 do plano. Modele e implemente o primeiro corte do Mission aggregate (#43), sem quebrar as APIs existentes. Uma Mission deve ter identidade própria, timeline append-only, estado explícito e relação com tasks/attempts.

## Escopo mínimo

- Criar modelo/tabela `missions`.
- Criar `mission_events` ou reaproveitar audit events com entity_type mission.
- Relacionar Task como attempt de Mission.
- Estados mínimos:
  - `draft`
  - `queued`
  - `running`
  - `waiting_human`
  - `completed`
  - `failed`
  - `cancelled`
- Não migrar tudo de uma vez: `start_development_task` pode continuar criando Task, mas novo endpoint/tool cria Mission + primeira Task.

## Critério de aceite

Uma intenção do operador possui um id estável de Mission, mesmo que várias Tasks/attempts ocorram por baixo.

---

# P5 — Issue-to-Mission workflow (#44)

## Contexto

Depois de existir Mission, selecionar uma issue local/forge deve criar uma Mission idempotente, não apenas Task solta.

## Entrada para o chat

> Execute P5 do plano. Implemente issue-to-mission workflow (#44): dado `project` + `issue_ref`, snapshot a issue, crie/reuse uma Mission idempotente e despache planejamento/execução conforme policy.

## Requisitos

- [ ] `local:<id>` suportado.
- [ ] `gh:<n>` só se P3/#79 estiver fechado para projetos bound.
- [ ] Snapshot da issue usado no planejamento.
- [ ] Repeated request não duplica Mission.
- [ ] Mudança material na issue enquanto roda gera decisão/replan.
- [ ] Nunca fecha issue apenas porque agent saiu 0.

## Critério de aceite

De ChatGPT/MOBO, “resolva a issue X do projeto Y” cria ou reutiliza uma Mission rastreável com snapshot da issue.

---

# P6 — Branch/worktree/concurrency (#49)

## Contexto

Missões que alteram código precisam workspace isolado e recuperável.

## Entrada para o chat

> Execute P6 do plano. Implemente ownership de branch/worktree por mission attempt (#49), com proteção contra concorrência, dirty state e cleanup seguro.

## Requisitos

- [ ] Naming policy de branch/worktree.
- [ ] Base branch e base commit registrados.
- [ ] Dirty/untracked/conflict detection antes de mutação.
- [ ] Lock/lease por workspace/projeto.
- [ ] Nunca deletar trabalho humano automaticamente.

## Critério de aceite

Cada implementation attempt sabe repo/base/branch/worktree/owner e duas missions incompatíveis não escrevem no mesmo checkout.

---

# P7 — Completion/testing/delivery contract (#51)

## Contexto

“Agent terminou” não significa “software entregue”.

## Entrada para o chat

> Execute P7 do plano. Defina e implemente o contrato de completion/delivery (#51): changed files, diff summary, tests, checks, review, commits, branch, PR/artifacts e estados implemented/validated/delivered.

## Requisitos

- [ ] Capturar changed files/diff summary.
- [ ] Capturar tests/checks rodados e resultado.
- [ ] Capturar commits/branch/PR/artifacts se existirem.
- [ ] Separar implemented vs validated vs delivered vs merged.
- [ ] Merge/deploy nunca sem policy explícita.

## Critério de aceite

Mission completed possui evidência machine-readable do que mudou, o que foi validado e o que foi entregue.

---

# P8 — MOBO contract/events (#53)

## Contexto

MOBO precisa operar o modelo sem conhecer detalhes internos de executor/provider.

## Entrada para o chat

> Execute P8 do plano. Exponha APIs/eventos MOBO para Mission lifecycle (#53): create/list/detail/timeline/log/result/delivery, executors/providers/capabilities e typed events.

## Requisitos

- [ ] OpenAPI source of truth atualizado.
- [ ] Generated/fake client testa fluxo.
- [ ] Commands idempotentes e actor-attributed.
- [ ] Sem paths, raw credentials ou provider secrets.

## Critério de aceite

Um cliente MOBO fake consegue exercitar o ciclo de vida completo da Mission pelo contrato canônico.

---

# P9 — Multi-agent authorized mode (#58)

## Contexto

Somente depois de Mission/worktree/delivery existirem, implementar modo multi-agent com autorização única e bounded.

## Entrada para o chat

> Execute P9 do plano. Implemente o primeiro corte de multi-agent authorized mode (#58) como contrato de orquestração, não convenção de prompt. Exigir proposta, autorização bounded, workers não sobrepostos, critique loops e council trigger.

## Requisitos

- [ ] Proposal antes da execução.
- [ ] Bounded grant com escopo/repositórios/ações/expiração/proibidos.
- [ ] Partition por task/issue sem overlap.
- [ ] Até 4 correction rounds por worker.
- [ ] Commit só após validate + critique pass.
- [ ] Council a cada 5 accepted commits ou no fim do epic.

## Critério de aceite

Operador autoriza uma sessão/scope e CodexBridge executa dentro desse limite, parando em expansão de escopo ou gate sensível.

## 5. Ordem recomendada de commits

1. **Commit A — secure MCP/Node dispatch baseline**
   - engine registry extensível;
   - Node routing;
   - authorization guard;
   - result privacy;
   - reconnect redaction;
   - smoke tests.

2. **Commit B — MCP local planning read tools**
   - list local issues/epics;
   - authorization tests;
   - no writes yet, se quiser reduzir risco.

3. **Commit C — MCP local planning write tools**
   - create/update/move local issues/epics;
   - idempotency.

4. **Commit D — #80 decision and executor-owned forge operation skeleton**
   - docs;
   - protocol envelope;
   - credential non-leak tests.

5. **Commit E — forge-bound issue listing (#79)**
   - same MCP tool routes local vs forge.

6. **Commit F+ — Mission aggregate and beyond**
   - #43, #44, #49, #51, #53, #58 em cortes separados.

## 6. Prompt padrão para retomar qualquer sessão

Use este bloco em sessões futuras:

```text
Estamos no repositório CodexBridge. Antes de mexer em código, leia `docs/chatgpt-incremental-execution-plan.md`, rode `git status --short`, e diga em qual etapa P0–P9 estamos. Não commite `.claude-flow/`, `.swarm/`, `ruvector.db`, handoffs ou coordination-status. Siga apenas a próxima etapa pendente e rode os testes mínimos dela.
```

## 7. Prompt para avançar uma etapa específica

```text
Execute a etapa P<N> de `docs/chatgpt-incremental-execution-plan.md`. Primeiro confirme o estado atual com `git status --short` e testes relevantes. Depois implemente somente o escopo daquela etapa, atualize/adicione testes, rode os testes mínimos e reporte o diff final.
```

## 8. Definição de pronto do objetivo inicial

O objetivo inicial deste plano está pronto quando:

1. ChatGPT/MCP entende uma chamada equivalente a:

   ```text
   @CodexBridge, em devel3, verifique as issues locais que não resolvemos ainda no wa-hub
   ```

2. O sistema resolve `devel3` para um Bridge Node único.
3. O sistema resolve `wa-hub` para um Project lógico único.
4. O sistema exige binding ativo e authorization ativa para esse Node/Project.
5. A operação `read/analyze` é permitida apenas com capability `read`.
6. A listagem de issues locais vem de tool estruturada, não de prompt improvisado.
7. Nenhum path local, token, credential ou raw provider event aparece na resposta MCP.
8. O dispatch, quando necessário, vai ao executor do Node certo, sem spillover.
9. O resultado é auditável e testado por integração.

