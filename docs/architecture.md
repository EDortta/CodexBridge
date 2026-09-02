# Arquitetura proposta

## Resumo

O sistema tem dois componentes independentes:

1. `gateway` no `frida`
2. `codex-bridge-agent` no executor com os repositórios locais, preferencialmente `devel3`

O ChatGPT conversa apenas com o `gateway`, através de um servidor MCP remoto exposto em `HTTPS /mcp` no `frida`. O `gateway` não acessa o executor por SSH. O executor abre uma conexão reversa `wss://codexbridge.inovacaosistemas.com.br:8443/agent/ws` e fica escutando tarefas.

## Decisões arquiteturais

### Transporte MCP para o ChatGPT

* Protocolo: MCP remoto sobre HTTP streamable em `/mcp`
* Justificativa: é o caminho documentado pela OpenAI para ChatGPT e plugins MCP remotos
* Trade-off: maior cuidado na aderência ao protocolo HTTP do MCP; em troca, evita dependências não documentadas no lado do ChatGPT

### Transporte reverso para o executor

* Protocolo: WebSocket seguro em `/agent/ws`
* Justificativa: canal full-duplex simples para heartbeat, despacho, ACK, logs incrementais e cancelamento
* Trade-off: exige controle de reconexão e deduplicação; em troca, elimina SSH de entrada e simplifica entrega em tempo real

### Topologia operacional definida

| Host | Papel | Observação |
|---|---|---|
| `frida` | hub público, hospeda o gateway MCP | Raspberry Pi, 24x7. Ponto de entrada único. |
| `devel3` | executor, roda o `codex-bridge-agent` | Tem os repositórios locais. |
| `T610` | histórico | Primeira máquina de desenvolvimento do projeto. |
| `dom1` | workloads adjacentes | Não é runtime do bridge. |

Portas no `frida`: o `nginx` termina TLS na porta **interna 443**, publicada
**externamente na 8443**. Daí `CODEX_BRIDGE_PUBLIC_BASE_URL=https://codexbridge.inovacaosistemas.com.br:8443`.
O gateway em si escuta em `127.0.0.1:18080`, atrás do `nginx`, porque `*:8080` já
está ocupado por `mosquitto`.

Dois caminhos distintos, que não devem ser confundidos:

* **Caminho de dados do bridge**: o agente no `devel3` abre conexão reversa
  `wss` para o `frida` e fica escutando tarefas. O `frida` nunca inicia conexão
  para o `devel3`.
* **Caminho administrativo humano**: o operador entra pelo `frida` e de lá alcança
  o `devel3` pelo túnel SSH já operacional (portas `2200/2204`). Esse túnel é para
  operação manual e não participa da execução de tarefas.

Sobre o `T610`: foi a primeira máquina usada para desenvolver o projeto, antes da
decisão de entrar pelo `frida`. O nome sobreviveu como valor de exemplo em
`.env.example` (`CODEX_BRIDGE_AGENT_EXECUTOR_ID=T610`) e em `examples/registry.json`.
`executor_id` é apenas um rótulo de registro — mas os exemplos ainda trazem `T610`
enquanto o executor real é o `devel3`, e essa divergência é intencionalmente
apontada aqui até que alguém decida renomear.

### Persistência

* Banco: PostgreSQL em produção
* Modo de testes/desenvolvimento: SQLite assíncrono
* Justificativa: PostgreSQL é suficiente para tarefas, auditoria, locks lógicos e recuperação após reinício sem exigir um cluster extra
* Redis: opcional e fora do MVP

### Isolamento e políticas

* Projetos autorizados são cadastrados por `project_id`
* O ChatGPT nunca informa caminho
* O agente resolve `realpath` e compara contra a allowlist local
* Modos `analyze`, `review`, `edit`, `test`, `implement` são mapeados para níveis de política
* Ações sensíveis exigem aprovação no gateway e no agente

**A mesma fronteira vale um nível abaixo, para a materialização de épicas
(issue #78, WK-20260902-issue-materialize).** "O ChatGPT nunca informa
caminho" implica "o gateway nunca sabe o path" — e decidir o próximo `NNN`
livre em `docs/issues/` exige listar o que já existe em disco, o que só o
executor pode fazer. Por isso `publish_epic_to_repo` manda ao executor
apenas conteúdo já renderizado (`gateway/app/services/issue_render.py`,
função pura) com caminhos relativos à pasta da épica e SEM `NNN`; é o agente,
em `agent/codex_bridge_agent/issue_materialize.py`, que varre o diretório
(reaproveitando o mesmo scanner que `instructions.py` usa para resolver
`docs:NNN`/`NNN` na leitura) e escolhe cada número, com criação atômica
para sobreviver a uma corrida entre duas publicações. Ver `docs/protocol.md`,
seção "Materialização de épicas", para o par de mensagens completo.

## Fluxo de comunicação

1. O ChatGPT conecta o MCP remoto em um hostname dedicado no `frida`, por exemplo `https://codexbridge.inovacaosistemas.com.br:8443/mcp`.
2. O ChatGPT chama `list_executors`, `executor_status` e `list_projects`.
3. Ao chamar `submit_codex_task`, o gateway valida autenticação, executor, projeto, política e prazo.
4. Se o executor estiver offline:
   * `run_when_available=false` -> rejeita.
   * `run_when_available=true` -> persiste em fila.
5. O agente do executor, idealmente no `devel3`, mantém `wss` com heartbeat.
6. Quando o executor está disponível, o gateway envia `task.dispatch`.
7. O agente confirma `task.ack`, executa `codex exec` localmente e transmite `task.log` (com `offset` incremental) e `task.result`.
8. O gateway persiste tudo e responde aos tools MCP.
9. `cancel_codex_task` marca a tarefa como `cancelled` incondicionalmente para qualquer estado cancelável (fila, aprovação pendente, execução, pausa/retomada/reinício pendentes); envia `task.cancel` ao agente apenas se ele estiver conectado no momento. Se estiver offline, o cancelamento é reenviado quando o executor reconectar (`AgentHub.register`, limitado por `cancel_replay_max_age_seconds`).

## Trade-offs principais

### Por que WebSocket entre agente e gateway

* Melhor para logs incrementais do que polling.
* Permite cancelamento em tempo real.
* Facilita heartbeat e reconexão.

Contra:

* Requer controle de sessão e mensagens idempotentes.

### Por que não SSH reverso

* Mais superfície operacional.
* Mistura plano de controle com acesso shell.
* Viola a exigência de não expor acesso de desenvolvimento direto.

### Por que não Redis no MVP

* PostgreSQL já cobre persistência, fila simples e recuperação.
* Menos componentes para operar no Frida.

## Ambiente real levantado em 2026-07-28

* `frida` é acessível por `ssh -p 2200 esteban@frida.inovacaosistemas.com.br`.
* `frida` já roda `nginx` em `80/443`.
* `frida` já tem `mosquitto` ocupando `*:8080`.
* Portanto, o gateway deve escutar em outra porta local, por exemplo `127.0.0.1:18080`, com proxy reverso no `nginx`.
* `devel3` é a máquina com os repositórios locais e é o executor primário.
* `T610` é a máquina de desenvolvimento original e não é executor de produção.

## Observação sobre autenticação ChatGPT

O MCP do ChatGPT suporta `OAuth`, `No Authentication` e `Mixed Authentication` segundo a documentação oficial consultada em `2026-07-28`. O estado atual deste repositório já inclui o fluxo `OAuth Authorization Code + PKCE` no gateway, mantendo bearer estático apenas como modo opcional de compatibilidade administrativa.
