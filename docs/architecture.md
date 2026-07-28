# Arquitetura proposta

## Resumo

O sistema tem dois componentes independentes:

1. `gateway` no `frida.inovacaosistemas.com.br:8443`
2. `codex-bridge-agent` no executor `T610`

O ChatGPT conversa apenas com o `gateway`, através de um servidor MCP remoto exposto em `HTTPS /mcp`. O `gateway` não acessa o `T610` por SSH. O `T610` abre uma conexão reversa `wss://frida.inovacaosistemas.com.br:8443/agent/ws` e fica escutando tarefas.

## Decisões arquiteturais

### Transporte MCP para o ChatGPT

* Protocolo: MCP remoto sobre HTTP streamable em `/mcp`
* Justificativa: é o caminho documentado pela OpenAI para ChatGPT e plugins MCP remotos
* Trade-off: maior cuidado na aderência ao protocolo HTTP do MCP; em troca, evita dependências não documentadas no lado do ChatGPT

### Transporte reverso para o executor

* Protocolo: WebSocket seguro em `/agent/ws`
* Justificativa: canal full-duplex simples para heartbeat, despacho, ACK, logs incrementais e cancelamento
* Trade-off: exige controle de reconexão e deduplicação; em troca, elimina SSH de entrada e simplifica entrega em tempo real

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

1. O ChatGPT conecta o MCP remoto em `https://frida.inovacaosistemas.com.br:8443/mcp`.
2. O ChatGPT chama `list_executors`, `executor_status` e `list_projects`.
3. Ao chamar `submit_codex_task`, o gateway valida autenticação, executor, projeto, política e prazo.
4. Se o executor estiver offline:
   * `run_when_available=false` -> rejeita.
   * `run_when_available=true` -> persiste em fila.
5. O agente do `T610` mantém `wss` com heartbeat.
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

## Observação sobre autenticação ChatGPT

O MCP do ChatGPT suporta `OAuth`, `No Authentication` e `Mixed Authentication` segundo a documentação oficial consultada em `2026-07-28`. O MVP deste repositório implementa autenticação por bearer token no servidor MCP e deixa o adaptador OAuth isolado para a fase de endurecimento, porque o foco inicial é fechar o plano de controle, o canal reverso e a execução segura do `codex exec`.

