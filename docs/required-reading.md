# Required Reading

**O índice único da leitura obrigatória deste projeto.** O agente abre este arquivo e
sabe tudo o que precisa ler — não precisa saber que parte da documentação mora em
`.docs/` (território do kit, substituído no `--upgrade`) e parte em `docs/` (território
do projeto, nunca sobrescrito). A coluna "Dono" diz de quem é cada arquivo, e isso só
importa na hora de **escrever**, não de ler.

<!-- AI-AGENTS:BEGIN kit reading list — gerado por install-agents-kit.sh; edições aqui dentro são substituídas no --upgrade. Escreva fora do bloco. -->
## Sempre, antes de qualquer issue

| Documento | Dono | O que é |
|---|---|---|
| `AGENTS.md` | kit | contrato universal de operação |
| `.docs/software-overview.md` | kit semeia, **projeto preenche** | produto, stack, módulos, comportamento |
| `.docs/limits.md` | kit semeia, **projeto preenche** | fronteiras duras do agente |
| `docs/project-rules.md` | **projeto** | regras que valem só aqui |

## Conforme o papel do trabalho

| Vai fazer | Leia também | Dono |
|---|---|---|
| codar / resolver issue | `.docs/agents/programmer.md` + `.docs/agents/design-standards.md` | kit |
| revisar código ou PR | `.docs/agents/reviewer.md` + `.docs/agents/design-standards.md` | kit |
| automatizar issue/PR | `.docs/agents/issue-automation.md` | kit |
| revisão adversarial de trabalho já aprovado | `.docs/agents/council.md` | kit |
| mudança com impacto em runtime | `.docs/agents/security.md` + `.docs/agents/security-standards.md` | kit |
| tratar dado pessoal | `.docs/agents/privacy-compliance.md` | kit |
| retomar / fechar sessão | `.docs/workflows/session-restore.md`, `.docs/workflows/session-close.md` | kit |
| implementar seleção/orçamento de contexto | `.docs/context-optimization.md` | kit |
| adotar, inicializar ou definir o escopo do projeto | `.docs/agents/domains-and-capabilities.md` + `.docs/agents/credentials-operations.md` | kit |
| classificar mudança estrutural | `.docs/agents/architecture-classification.md` | kit |
<!-- AI-AGENTS:END -->

## Deste projeto

Documentos específicos deste repositório. Esta seção é 100% do projeto: nenhum upgrade
a toca. Use `- (none)` se genuinamente não houver nenhum.

- `docs/project-rules.md` — regras específicas deste projeto (também na tabela acima)
- `docs/control-plane.md` — **obrigatório** ao tocar em nó, projeto lógico,
  binding de workspace, associação SCM ou autorização (issue #73). Explica por que
  essas entidades são separadas e o que se perde ao fundi-las.
- `docs/napkin-lessons.md` — lições curtas; leia ao retomar trabalho relacionado

## Fontes locais — fora do checkout

Credenciais e destinos vivem fora do repositório (nunca versionados), mas um agente
precisa saber onde estão e para que servem — path e propósito, nunca o conteúdo. Ver
`.docs/workflows/sending-email.md` antes de qualquer envio de e-mail.

| Fonte | Propósito | Symlink no projeto |
|---|---|---|
| `~/.config/credentials/email/dortta-yahoo.conf` | transporte SMTP (conta Yahoo) para notificação de conclusão de tarefa | `.credentials/yahoo-email.conf` |
| `~/.config/credentials/job-outreach/calendar/service-account.json` | service account Google Calendar (`create_reminder`/`cancel_reminder`), compartilhada com job-outreach e igreja-pequena | `.credentials/google-calendar-sa.json` |

**Destinatário fixo das notificações de conclusão de tarefa: `edortta71@gmail.com`.**
Definido pelo operador nesta sessão (2026-08-30) — nunca resolver de
`requested_by_email` nem do `userEmail` do harness; ver `CODEX_BRIDGE_NOTIFICATION_TO`
em `.env.example`.

## Por área

Leitura escopada: só quem for mexer na área precisa.

<!-- Exemplo:
- `docs/architecture.md` — ao tocar na camada de orquestração
- `clara-definitions/00-index.md` — ao trabalhar em Clara / WhatsApp / comprovantes
-->

- `docs/api/README.md` — **obrigatório** ao tocar em qualquer endpoint sob `/api`,
  ou ao serializar projeto, task, sessão ou log para a API móvel. Contém as regras
  que o YAML não expressa: o que é breaking change, o procedimento de depreciação,
  e a seção "Fields that must never ship" (o `ProjectModel.path` é a armadilha
  canônica — caminho real no executor, nunca sai em resposta).
- `docs/api/codex-bridge.openapi.yaml` — o contrato canônico da API móvel. Mudar
  endpoint significa mudar este arquivo **primeiro**; `tests/contract/` reprova a
  divergência.
- `docs/api/testing.md` — **obrigatório** ao mexer no contrato: qual gate guarda
  qual par, como publicar uma versão (`scripts/publish_contract.py`), como o repo
  móvel fixa uma versão pelo digest, e o que o gate de breaking change
  (`scripts/check_contract_compatibility.py`) **não** consegue ver. Mudou o YAML
  e não republicou? A suíte reprova, e a mensagem diz o arquivo.
- `migrations/` + `scripts/apply_migrations.py` — **obrigatório** ao alterar
  `gateway/app/models/entities.py`. Uma mudança de schema não está pronta quando o
  modelo muda: o `create_all` do startup só cria tabela nova, nunca adiciona coluna
  a tabela existente, então sem a migration a instalação limpa funciona e toda
  instalação existente quebra na primeira leitura. Registre o objeto novo em
  `gateway/app/db/schema_guard.py`.
  **Cuidado com o que esse registro garante:** coluna nova (`REQUIRED_COLUMNS`,
  `FORBIDDEN_COLUMNS`) reprova o startup de fato; tabela nova
  (`REQUIRED_TABLES`) **não** — o `create_all` roda antes do `check_schema` e
  cria a tabela, então o gateway sobe sem os índices e defaults do `.sql` e sem
  linha em `schema_migrations`, em silêncio. Ver o comentário em
  `gateway/app/db/schema_guard.py` e
  `tests/unit/test_schema_guard.py::test_required_tables_cannot_fire_at_boot_today`.
