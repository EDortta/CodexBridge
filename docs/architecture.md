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

#### Binding de forge: o gateway guarda o declarado, o executor confirma o real

Issue #79/#80, WK-20260902-forge-binding (PR B4). Um projeto pode estar
"ligado" a um repositório GitHub (`scm_associations`, migration `0009`,
lida/escrita a partir desta PR) — e essa ligação é deliberadamente **dois
fatos separados, guardados em dois lugares diferentes**, não um só:

* **O gateway guarda o DECLARADO.** `gateway/app/services/forge_routing.py`'s
  `project_forge_binding` é o único ponto que lê `scm_associations` e decide
  "ligado" ou "não ligado" — todo chamador (as ferramentas MCP de forge,
  `AgentHub.dispatch_next` para resolver `gh:N`) pergunta a essa função, nunca
  refaz a consulta por conta própria. `confidence` começa `declared` (um
  operador nomeou o repositório) e só vira `confirmed` por ação explícita do
  mesmo operador, na mesma chamada — nunca automaticamente, nem por um
  `repo_identity_mismatch` que passou uma vez.
* **O executor confirma o REAL, sempre ao vivo, nunca cacheado.**
  `agent/codex_bridge_agent/forge/github.py`'s `_confirm_repo_identity_live`
  roda `git remote get-url origin` (o `run_git` que `git_delivery.py` já usa)
  antes de CADA operação de forge — leitura ou escrita — e recusa
  `repo_identity_mismatch` se o remote real divergir do que o gateway
  declarou. Uma chamada `git` local, sem rede, custa o suficiente barato para
  rodar em toda operação e elimina a necessidade de um job de reconciliação:
  não existe janela em que uma pasta que perdeu ou trocou de remote continue
  sendo tratada como o binding antigo, porque nada é lembrado entre uma
  operação e a próxima.

**Por que a operação de forge não é uma extensão do runner.** Um `Runner`
(`agent/codex_bridge_agent/runners/`) roda DENTRO do sandbox do agente de
codificação — é exatamente esse sandbox que não tem rede (verificado contra
a `devel3` em 2026-09-01; `docs/security.md` documenta os dois caminhos
alternativos que foram rejeitados por isso). Uma operação de forge roda FORA
de qualquer sandbox, como uma chamada de subprocesso `gh` limitada no
próprio processo do executor (`agent/codex_bridge_agent/forge/gh_tool.py`),
carregando uma credencial (`GH_TOKEN`) que nunca pode entrar no ambiente de
um `Runner` — a mesma fronteira `agent/codex_bridge_agent/git_delivery.py`
já estabelece para `git push`, aplicada de novo aqui pela mesma razão: o
agente de codificação processa instruções e conteúdo que podem ser não
confiáveis (uma issue de repositório público, por exemplo), e uma
credencial de rede real não pode estar alcançável por esse processo. Tratar
uma operação de forge como "mais um modo do runner" teria significado
ensinar `_sandbox_for`/`RunnerPool` a abrir uma exceção de rede para um caso
— exatamente a superfície não enumerável que `docs/security.md`'s caminho 2
rejeitado descreve.

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
