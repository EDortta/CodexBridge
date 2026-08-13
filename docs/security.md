# Segurança

## Controles implementados no MVP

* MCP sem ferramenta genérica de shell.
* `project_id` obrigatório; nenhum path vindo do ChatGPT.
* allowlist dupla de executores e projetos.
* resolução por `realpath` no agente.
* `codex exec` e `git` chamados sem shell.
* logs sanitizados.
* tarefas sensíveis desviadas para `awaiting_approval`.
* fila persistente com auditoria append-only.
* WebSocket reverso iniciado pelo executor.
* `systemd` com endurecimento e usuário sem privilégio.
* rate limiting por IP em `POST /mcp` (`MemoryRateLimiter`, `gateway/app/main.py`),
  padrão de 120 requisições por janela de 60 segundos, resposta `429` e métrica
  `RATE_LIMIT_REJECTIONS`.

## Lacunas assumidas para endurecimento

* **`/oauth/authorize` e `/oauth/token` não têm rate limiting.** São endpoints
  públicos que recebem senha; hoje o limitador cobre apenas `/mcp`. É a lacuna de
  maior prioridade nesta lista.
* o limitador é em memória por processo: não sobrevive a restart e não é
  compartilhado entre réplicas.
* rotação automatizada de tokens ainda não foi implementada.
* cgroups finos por subprocesso do `codex exec` ainda dependem do host do agente.
* `sensitive_patterns` por projeto está no schema mas não é aplicado em lugar
  nenhum; a classificação de tarefa sensível usa apenas a lista global
  `SENSITIVE_KEYWORDS` em `shared/policy.py`. Ver `docs/project-onboarding.md`.

## Recomendações de produção

* usar PostgreSQL real com backup e retenção;
* mover tokens para `EnvironmentFile` root-only;
* colocar o gateway atrás de `nginx` com TLS válido;
* executar o agente em conta dedicada `codexbridge`;
* limitar os diretórios liberados em `ReadWritePaths`;
* manter o modo bearer apenas para compatibilidade administrativa;
* operar o uso humano do ChatGPT exclusivamente via OAuth.
