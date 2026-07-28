# Plano objetivo

## Fase 1 — Descoberta

Concluída em `2026-07-28`.

* `codex exec` confirmado localmente.
* MCP remoto para ChatGPT confirmado em `HTTPS /mcp`.
* Developer mode do ChatGPT confirmado para criação do app MCP remoto.
* Transporte reverso por `wss` escolhido para o canal do executor.

## Fase 2 — MVP

1. contratos compartilhados e schemas
2. persistência e filas
3. gateway HTTP/MCP + WebSocket do agente
4. cadastro estático de projetos e executores
5. runner do `codex exec`
6. logs, diff, resultado e cancelamento
7. documentação operacional
8. testes unitários e de integração

## Fase 3 — Endurecimento

1. aprovação formal para tarefas sensíveis
2. rate limiting
3. métricas adicionais e alertas
4. rotação de credenciais
5. recuperação mais fina de sessões e redispatch
6. OAuth/Mixed Authentication para o MCP do ChatGPT

