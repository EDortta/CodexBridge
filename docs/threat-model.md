# Modelo de ameaça

## Ativos protegidos

* repositórios e workspaces do executor (`devel3`; historicamente `T610`)
* credenciais do `codex`, Git e ferramentas locais
* histórico de tarefas, logs e diffs
* disponibilidade do `gateway`
* integridade da fila de tarefas

## Atores

* usuário legítimo do ChatGPT com acesso ao MCP
* operador do gateway
* agente executor legítimo
* atacante externo tentando usar o endpoint público
* repositório malicioso contendo prompt injection

## Ameaças e controles

### Acesso indevido a projeto não autorizado

* controle: `project_id` obrigatório, sem path arbitrário
* controle: allowlist no gateway (`registry.json`) e allowlist redundante no
  agente (`projects.json`); o agente responde `unknown_project` se o id não
  estiver na sua própria lista
* controle: `realpath` do caminho cadastrado antes de executar

Precisão sobre a ancestralidade: `ensure_within_root` existe e resolve `realpath`,
mas hoje é chamada como `ensure_within_root(project.path, project.path)`
(`agent/codex_bridge_agent/service.py`) — raiz comparada contra ela mesma, então a
verificação de ancestralidade sempre passa. Isso **não** é vulnerabilidade no
desenho atual, porque não existe componente de caminho vindo do cliente: o único
path possível é o cadastrado na allowlist local.

A checagem passa a ser necessária de verdade no momento em que qualquer campo de
subcaminho for aceito na tarefa (arquivo alvo, subdiretório, worktree). Quem
implementar isso precisa passar a raiz do projeto e o alvo como argumentos
distintos. Registrado aqui para que ninguém leia "ancestralidade verificada" e
presuma proteção que ainda não está armada.

### Execução de comandos arbitrários

* controle: nenhuma ferramenta MCP genérica de shell
* controle: o agente chama `codex exec` sem shell
* controle: argumentos montados como arrays

### Replay e duplicação de mensagens

* controle: `message_id` por evento
* controle: tabela de deduplicação no gateway
* controle: ACK explícito do agente

### Prompt injection a partir do repositório

* controle: instrução-base anexada pelo agente antes do prompt do usuário
* controle: política explícita proibindo exfiltração, push, deploy e leitura fora do projeto
* controle: bloqueio de tarefas sensíveis sem aprovação
* controle: truncagem e sanitização de conteúdo retornado

### Vazamento de segredos por logs

* controle: sanitização por padrões conhecidos
* controle: limitação de tamanho por chunk e total
* controle: persistência separada de logs e resultado final

### Credenciais herdadas pelo subprocesso `codex exec`

Decisão declarada, não lacuna acidental.

O agente monta o ambiente do subprocesso com uma allowlist de 6 variáveis
(`filtered_environment`, em `agent/codex_bridge_agent/codex_runner.py`):
`HOME`, `PATH`, `LANG`, `LC_ALL`, `CODEX_HOME`, `OPENAI_API_KEY`.

Consequência: o `codex exec` roda com `HOME` do usuário do agente. Com `HOME` vêm,
por alcance de sistema de arquivos, `~/.gitconfig`, credential helpers do Git,
`~/.ssh` e o próprio `CODEX_HOME`. E `OPENAI_API_KEY` é repassada diretamente.

* razão: o `codex` precisa de autenticação e de identidade Git para operar; sem
  `HOME` e sem a chave, o produto não funciona
* risco aceito: instrução vinda do ChatGPT executa num processo que **alcança**
  essas credenciais. Um repositório com prompt injection pode tentar induzir o
  modelo a lê-las e devolvê-las no resultado
* controles que mitigam, sem eliminar: `BASE_PROMPT` proíbe explicitamente
  acessar segredos e diretórios pais; `sanitize_log_line` redige `sk-*`, `ghp_*`
  e `Bearer *` nos logs; o resultado é truncado
* controle que **não** existe: nada impede leitura de `~/.ssh` pelo subprocesso, e
  a sanitização cobre três padrões conhecidos, não chave privada SSH nem token de
  formato novo
* recomendação operacional: usuário Linux dedicado ao agente, com `HOME` próprio,
  sem chaves SSH pessoais e sem credenciais Git de escrita em repositório de
  produção — assim o que o subprocesso alcança é o mínimo que o `codex` exige

A política de sandbox do `codex exec` é explícita, não mais o default herdado
do CLI (issue #34): `read-only` a menos que o `policy_level` da tarefa já
indicasse escrita, com trava adicional por executor
(`AgentSettings.allow_workspace_write`). Ver `docs/development.md`.

### Escalada local no executor

* controle: usuário Linux dedicado e não root
* controle: diretórios autorizados e env allowlist
* controle: `systemd` com endurecimento
* controle: limites de CPU, memória, tarefas e tempo

### Fila inconsistente após reinício

* controle: banco transacional
* controle: recuperação de tarefas `running` para `lost`
* controle: redispatch apenas para tarefas `queued` ou `waiting_executor`

## Premissas

* o `frida` terá TLS válido no reverse proxy
* o executor (`devel3`) possui `codex` autenticado e funcional
* os projetos autorizados são cadastrados explicitamente
* o agente roda em conta sem privilégios administrativos

