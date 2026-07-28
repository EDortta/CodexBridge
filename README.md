# CodexBridge

CodexBridge conecta o ChatGPT a executores remotos que rodam `codex exec` sem expor SSH público nem permitir caminhos arbitrários.

Topologia recomendada neste ambiente:

* `frida` publica o gateway MCP.
* `devel3` executa o agente e acessa os repositórios locais.
* `dom1` pode continuar servindo outros workloads, sem ser o runtime principal do bridge.

O repositório implementa:

* `gateway/`: servidor MCP remoto e plano de controle.
* `agent/`: executor reverso `codex-bridge-agent` para máquinas como o `devel3`.
* `shared/`: contratos, schemas e utilitários compartilhados.
* `deploy/`: exemplos de `systemd`, `nginx` e instalação.
* `docs/`: arquitetura, ameaça, protocolo, operação e segurança.
* `tests/`: testes unitários e de integração.

## Estado da implementação

Esta primeira entrega cobre o MVP:

* endpoint MCP remoto em `HTTPS /mcp`;
* canal reverso `wss://.../agent/ws` para executores;
* fila persistente com recuperação após reinício;
* cadastro estático de projetos autorizados;
* execução não interativa via `codex exec`;
* logs incrementais, cancelamento e diff Git;
* políticas de autorização no gateway e no agente;
* documentação operacional e exemplos de instalação.

## Restrições confirmadas do Codex CLI 0.145.0

O projeto usa apenas capacidades verificadas localmente em `2026-07-28`:

* `codex exec [PROMPT]`
* `codex exec --json`
* `codex exec -C <DIR>`
* `codex exec -o <FILE>`
* `codex exec --skip-git-repo-check`
* `codex exec --ephemeral`
* `codex exec resume`

Nenhuma flag fora dessa lista é presumida pela implementação.
