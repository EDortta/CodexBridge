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

## Lacunas assumidas para endurecimento

* rate limiting ainda não foi ligado no middleware HTTP.
* rotação automatizada de tokens ainda não foi implementada.
* cgroups finos por subprocesso do `codex exec` ainda dependem do host do agente.

## Recomendações de produção

* usar PostgreSQL real com backup e retenção;
* mover tokens para `EnvironmentFile` root-only;
* colocar o gateway atrás de `nginx` com TLS válido;
* executar o agente em conta dedicada `codexbridge`;
* limitar os diretórios liberados em `ReadWritePaths`;
* manter o modo bearer apenas para compatibilidade administrativa;
* operar o uso humano do ChatGPT exclusivamente via OAuth.
