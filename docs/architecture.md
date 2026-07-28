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

### Topologia operacional recomendada

* `frida` é o hub público 24x7 e deve hospedar o gateway MCP.
* `devel3` é o executor 24x7 mais adequado quando os repositórios locais são necessários.
* `dom1` pode continuar servindo workloads adjacentes, mas não é o runtime principal do bridge.
* A ponte reversa já existente em `devel3 -> frida` nas portas `2200/2204` continua útil para acesso administrativo.

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

## Fluxo de comunicação

1. O ChatGPT conecta o MCP remoto em um hostname dedicado no `frida`, por exemplo `https://codexbridge.inovacaosistemas.com.br:8443/mcp`.
2. O ChatGPT chama `list_executors`, `executor_status` e `list_projects`.
3. Ao chamar `submit_codex_task`, o gateway valida autenticação, executor, projeto, política e prazo.
4. Se o executor estiver offline:
   * `run_when_available=false` -> rejeita.
   * `run_when_available=true` -> persiste em fila.
5. O agente do executor, idealmente no `devel3`, mantém `wss` com heartbeat.
6. Quando o executor está disponível, o gateway envia `task.dispatch`.
7. O agente confirma `ACK`, executa `codex exec` localmente e transmite `task.log`, `task.progress`, `task.result`.
8. O gateway persiste tudo e responde aos tools MCP.
9. `cancel_codex_task` envia `task.cancel` ao agente ou marca a tarefa antes da execução.

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
* `devel3` é a máquina com os repositórios locais e deve ser tratada como executor primário.

## Observação sobre autenticação ChatGPT

O MCP do ChatGPT suporta `OAuth`, `No Authentication` e `Mixed Authentication` segundo a documentação oficial consultada em `2026-07-28`. O estado atual deste repositório já inclui o fluxo `OAuth Authorization Code + PKCE` no gateway, mantendo bearer estático apenas como modo opcional de compatibilidade administrativa.
