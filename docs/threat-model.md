# Modelo de ameaça

## Ativos protegidos

* repositórios e workspaces do `T610`
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
* controle: allowlist no gateway e allowlist redundante no agente
* controle: `realpath` + verificação de ancestralidade

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

### Escalada local no T610

* controle: usuário Linux dedicado e não root
* controle: diretórios autorizados e env allowlist
* controle: `systemd` com endurecimento
* controle: limites de CPU, memória, tarefas e tempo

### Fila inconsistente após reinício

* controle: banco transacional
* controle: recuperação de tarefas `running` para `lost`
* controle: redispatch apenas para tarefas `queued` ou `waiting_executor`

## Premissas

* o `Frida` terá TLS válido no reverse proxy
* o `T610` possui `codex` autenticado e funcional
* os projetos autorizados são cadastrados explicitamente
* o agente roda em conta sem privilégios administrativos

