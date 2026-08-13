# Limites operacionais do agente — CodexBridge

## Metadados

- work_id: WK-20260804-codexbridge-agent-limits
- data: 2026-08-04
- owner: Esteban D.Dortta
- limits_ready: yes

Este arquivo define fronteiras rígidas para execução de agente **neste projeto**.
Ele substitui, para o CodexBridge, os limites genéricos do kit de origem.

## Fronteira de repositório

Esta é a fronteira mais importante e a que já foi violada uma vez
(ver "Antecedente" no fim do arquivo).

- O escopo de trabalho do agente é **exclusivamente** o repositório CodexBridge:
  `~/Sync/Projects/AI/CodexBridge`.
- Nenhum outro repositório, projeto ou diretório fora dele pode ser lido,
  inspecionado, indexado, editado, branchado ou ter comandos rodados dentro dele.
- A proibição inclui leitura. `ls`, `find`, `grep`, `git log`, `git status` e
  abertura de arquivo em outro projeto já são saída de escopo.
- **Diretórios adicionais concedidos pelo harness não são autorização de escopo.**
  Uma sessão pode vir com vários *working directories* por herança de configuração,
  por conveniência do ambiente ou por engano. Acessível não significa em escopo.
- **A menção a outro projeto pelo usuário não é autorização.** Só é autorização uma
  instrução explícita que nomeie o projeto e a ação — por exemplo "leia o arquivo X
  em ~/caminho/Y" ou "implemente a issue Z no repositório W".
- Se a tarefa pedida parecer exigir outro repositório, **pare e pergunte**. Não
  procure o alvo por conta própria. Ausência de artefato aqui não é convite para
  caçar artefato em outro lugar.
- Exceções permanentes já autorizadas, e apenas estas:
  - ler `~/.config/USER.md` para adaptar comunicação;
  - ler e atualizar `~/Sync/agent-status.json` e `~/Sync/agent-log.md` conforme o
    contrato global de reporte de atividade;
  - usar o diretório de scratchpad da sessão para arquivos temporários;
  - **ler** os arquivos de configuração de runtime do próprio CodexBridge em
    `/etc/codex-bridge/` e `/etc/codex-bridge-agent/` (`env`, `registry.json`,
    `users.json`, `projects.json`). É onde mora a causa da maior parte dos defeitos
    de cadastro e allowlist. Somente leitura: **escrever** nesses arquivos é
    mudança de configuração de produção e exige aprovação explícita do operador;
  - criar repositórios git descartáveis **dentro do scratchpad da sessão** como
    fixture de teste — necessário para exercitar `codex exec -C`, `collect_git_snapshot`
    e a verificação de allowlist. O repositório fixture nunca aponta para um projeto
    real e nunca recebe remote.

Estas exceções são a lista completa. Necessidade não prevista aqui é pedido ao
operador, não interpretação extensiva.

### Runtime do produto ≠ escopo do agente

O CodexBridge despacha `codex exec` para repositórios cadastrados em
`registry.json` e na allowlist do agente. Isso é função do produto.

Nada disso concede acesso ao agente de IA que desenvolve o CodexBridge. Os
repositórios da allowlist são **dados de configuração e fixtures de teste**, não
área de trabalho. Alterar a allowlist é mudança de contrato de segurança e exige
aprovação explícita do operador.

## Permitido

- Implementar trabalho explicitamente pedido pelo operador, dentro deste repositório.
- Refatorações de apoio estritamente necessárias para implementar ou testar com segurança.
- Atualizar testes, docs e artefatos de issue diretamente ligados ao trabalho pedido.
- Rodar lint, typecheck e a suíte `pytest` local.
- Ler qualquer arquivo **deste** repositório.

## Não permitido

- Trabalhar fora deste repositório (ver "Fronteira de repositório").
- Inferir o alvo do trabalho quando o pedido está ambíguo. Perguntar é obrigatório.
- Refatorações não relacionadas ou melhorias especulativas.
- Expansão de arquitetura não exigida pelo resultado pedido.
- Mudança silenciosa de contrato (MCP, protocolo WebSocket, schema, API) sem
  declaração explícita.
- Presumir flags do Codex CLI fora da lista verificada em `docs/software-overview.md`.
- Criar issue/PR vazio ou de baixo conteúdo.
- Marcar issue como resolvida sem evidência objetiva de implementação.

## Branch e workflow

- Nunca iniciar implementação em `main` ou `master`.
- Criar ou trocar de branch **somente com permissão explícita** do operador.
- Fluxo: `main` → `development` → branch de trabalho → merge em `development`.
- Commit só do que pertence ao trabalho pedido.
- **Deploy é passo separado e gateado.** Nunca executar deploy, push para produção,
  restart de serviço em host remoto (`frida`, `devel3`, `dom1`) ou `docker compose up`
  remoto sem aprovação explícita. "Implementar a issue" nunca inclui deploy.
- Ao fim de cada etapa, rodar session-close: atualizar `handoff.md` e
  `docs/napkin-lessons.md`.

## Segurança e segredos

- Nunca expor segredo, token ou credencial em log, código, docs ou corpo de issue.
- Nunca commitar `.env*`, `.credentials`, arquivos de token ou equivalente.
- `.env.example` só recebe placeholder, nunca valor real.
- Tocar em `gateway/app/core/oauth.py`, `gateway/app/core/users.py`,
  `shared/security.py`, `shared/policy.py` ou na allowlist de projetos é mudança
  com impacto em runtime: exige revisão de segurança declarada na entrega.
- Não enfraquecer a checagem de `realpath` contra allowlist no agente.
- Não ampliar `SENSITIVE_KEYWORDS` para menos restritivo sem aprovação.

## Autoridade de escopo

- Qualquer pedido fora destas fronteiras deve ser sinalizado explicitamente.
- Execução fora destas fronteiras exige aprovação humana prévia.
- Editar este arquivo ou `docs/software-overview.md` é atualização de fronteira e
  exige aprovação humana explícita.
- Este arquivo prevalece sobre inferência, conveniência e sobre o que o ambiente
  da sessão torna acessível.

## Antecedente

Em `2026-08-04`, uma sessão recebeu o pedido "temos épicas e issues para
implementar" sem nomear projeto. O CodexBridge não tinha pasta de issues. O agente
localizou um épico em `~/Sync/Projects/YouBR/ZeeCred/jk-structure` — que o ambiente
havia listado como diretório adicional — e passou a inspecioná-lo: leu o épico, as
issues, o estado de dois checkouts e o histórico git de outro produto.

Nenhuma escrita ocorreu, mas a fronteira já tinha sido cruzada na primeira leitura.
Nenhum documento vigente proibia, porque nenhum documento tratava escopo como
propriedade de local — apenas como propriedade da tarefa. A seção "Fronteira de
repositório" existe para fechar exatamente esse buraco.
