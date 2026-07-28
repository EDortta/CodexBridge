# Rollout OAuth para uso amplo no ChatGPT

## Objetivo

Tornar o CodexBridge utilizável por qualquer programador autorizado do ambiente, via ChatGPT, como app/plugin MCP remoto com autenticação suportada nativamente pelo produto.

Estado atual em `2026-07-28`:

* o endpoint MCP já está publicado em `https://codexbridge.inovacaosistemas.com.br:8443/mcp`;
* o `gateway` no `frida` e o executor `devel3` já estão operacionais;
* o `gateway` já expõe metadados OAuth, `authorization endpoint` e `token endpoint`;
* falta concluir a publicação operacional com usuários reais, rotação de credenciais e instruções de uso por equipe.

## Resultado alvo

Ao final do rollout:

* qualquer programador autorizado do ambiente poderá adicionar ou usar o app MCP no ChatGPT;
* a autenticação ocorrerá por OAuth, sem distribuir tokens manuais do gateway;
* o `gateway` reconhecerá a identidade do usuário do ChatGPT;
* as permissões serão avaliadas por usuário, executor, projeto e tipo de ação;
* tarefas sensíveis continuarão exigindo aprovação;
* auditoria e trilha de execução permanecerão vinculadas ao usuário real.

## Topologia operacional

Topologia mantida:

* `frida`:
  * ponto de entrada público;
  * termina TLS;
  * publica `/mcp`;
  * mantém estado, fila, auditoria e políticas;
  * fala com `devel3` pelo canal reverso já implantado.
* `devel3`:
  * único executor de desenvolvimento;
  * contém repositórios e o `codex-cli`;
  * não recebe conexões públicas de entrada.

`dom1` não deve permanecer no caminho de runtime do CodexBridge. Se continuar emitindo ou renovando certificados, isso deve ser tratado apenas como processo auxiliar de certificados, não como proxy ativo do app.

## O que precisa ser feito do nosso lado

### 1. Substituir bearer estático por OAuth no MCP

Hoje o `gateway` protege `/mcp` com bearer token fixo. Isso deve ser trocado por autenticação OAuth compatível com ChatGPT.

Escopo mínimo:

* remover a dependência do cabeçalho `Authorization: Bearer <token-estatico>` para chamadas MCP do ChatGPT;
* aceitar tokens OAuth válidos emitidos por um authorization server controlado por nós;
* validar:
  * `issuer`;
  * `audience`;
  * expiração;
  * escopos;
  * identidade do usuário.

Decisão recomendada:

* usar `OAuth` completo, não `No Authentication`;
* evitar `Mixed Authentication` na primeira versão multiusuário, a menos que discovery sem login seja necessário por decisão explícita.

### 2. Definir o authorization server

Precisamos de um authorization server estável, público e administrável.

Recomendação:

* hospedar no próprio `frida`, sob caminho ou subdomínio dedicado;
* expor:
  * metadata OIDC/OAuth;
  * authorization endpoint;
  * token endpoint;
  * JWKS endpoint.

Pode ser:

* um serviço OAuth próprio mínimo para este projeto; ou
* um IdP maduro já existente no ambiente, desde que permita:
  * usuários do time;
  * escopos customizados;
  * claims suficientes;
  * client registration compatível com o ChatGPT.

### 3. Escolher o modelo de identidade dos programadores

Antes de publicar para mais de um usuário, precisamos decidir quem é “programador autorizado”.

Modelo recomendado:

* cada programador autentica com sua própria conta;
* o token traz um identificador estável, por exemplo:
  * `sub`;
  * `email`;
  * `preferred_username`;
* o `gateway` mapeia esse usuário para papéis e permissões.

Não recomendado:

* conta compartilhada;
* token único por equipe;
* acesso anônimo com tarefas de escrita.

### 4. Introduzir autorização por usuário

Hoje a autorização principal está em executor/projeto/política. Para uso por vários programadores, o `gateway` precisa adicionar uma camada por usuário.

Precisamos armazenar no mínimo:

* usuário;
* papéis;
* projetos permitidos;
* modos permitidos;
* permissão para aprovar tarefas sensíveis;
* estado ativo/inativo.

Regras recomendadas:

* um usuário pode listar apenas os projetos aos quais tem acesso;
* `submit_codex_task` deve validar:
  * usuário;
  * executor;
  * projeto;
  * modo;
  * política sensível;
* `get_task_logs`, `get_task_result` e `continue_codex_session` só devem funcionar para:
  * o autor da tarefa; ou
  * um papel administrativo explícito.

### 5. Modelar escopos OAuth

O rollout multiusuário precisa de escopos, mesmo que simples.

Modelo inicial recomendado:

* `codexbridge.read`
* `codexbridge.task.submit`
* `codexbridge.task.cancel`
* `codexbridge.task.approve`
* `codexbridge.admin`

Mapeamento sugerido:

* leitura de estado e consulta:
  * `executor_status`
  * `list_executors`
  * `list_projects`
  * `get_task_status`
  * `get_task_logs`
  * `get_task_result`
  * `list_recent_tasks`
* escrita:
  * `submit_codex_task`
  * `continue_codex_session`
  * `cancel_codex_task`
* sensível:
  * `approve_codex_task`

### 6. Propagar a identidade do usuário para auditoria

O modelo atual já grava auditoria de tarefas. Para uso amplo, cada evento precisa carregar identidade humana.

Adicionar à auditoria:

* `user_id`;
* `user_email` ou nome equivalente;
* `oauth_client_id` ou origem da conexão;
* `scopes`;
* IP de origem recebido pelo `frida`;
* correlação entre usuário, tarefa e executor.

Sem isso, o plugin não deve ser tratado como pronto para vários programadores.

### 7. Endurecer o fluxo de aprovação

Hoje as tarefas sensíveis já podem cair em `awaiting_approval`, mas o critério ainda é de MVP.

Para rollout multiusuário:

* separar quem envia de quem aprova;
* impedir autoaprovação por padrão;
* registrar justificativa de aprovação/rejeição;
* opcionalmente exigir um grupo específico para:
  * deploy;
  * secrets;
  * migrations;
  * push/PR.

### 8. Persistir credenciais e configuração de forma administrável

Precisamos trocar segredos operados manualmente por configuração administrável.

No `frida`:

* mover toda configuração OAuth para `EnvironmentFile` root-only;
* separar:
  * configuração do authorization server;
  * segredos do client OAuth;
  * JWKS/keys de assinatura, se o IdP for local;
* definir procedimento de rotação.

No `devel3`:

* nada muda para OAuth do ChatGPT;
* o executor continua usando token de máquina próprio para o canal reverso.

### 9. Adequar o MCP às expectativas do ChatGPT

Além do OAuth em si, o servidor precisa se comportar como app MCP bem formado para o ChatGPT.

Checklist:

* `/mcp` público em HTTPS;
* `initialize` consistente;
* `tools/list` com nomes, descrições e schemas claros;
* erros HTTP e erros de ferramenta úteis;
* metadata coerente após refresh;
* sem dependência de header privado/manual do operador.

Também vale revisar descrições de tools para melhorar seleção automática no ChatGPT, especialmente:

* `submit_codex_task`
* `continue_codex_session`
* `cancel_codex_task`
* `approve_codex_task`

### 10. Fechar lacunas do MVP antes do rollout amplo

Antes de abrir para vários programadores, ainda faltam endurecimentos que hoje são aceitáveis só em operação controlada.

Itens mínimos:

* ligar rate limiting HTTP real no `gateway`;
* implementar rotação de credenciais;
* revisar limites de tamanho de resultado e logs;
* revisar concorrência máxima do executor;
* revisar política de cancelamento e recuperação de tarefas;
* testar reconexão do executor durante tarefas ativas;
* validar recuperação do banco após restart do `gateway`.

## Publicação no ChatGPT

Depois do OAuth pronto, o fluxo esperado no ChatGPT passa a ser:

1. habilitar `Developer mode`;
2. criar o app apontando para `https://codexbridge.inovacaosistemas.com.br:8443/mcp`;
3. concluir o login OAuth;
4. revisar as tools descobertas;
5. usar o app em conversas com as permissões atribuídas ao usuário.

Para “qualquer programador do ambiente”, isso exige um destes modelos operacionais:

* app criado individualmente por cada usuário, usando o mesmo endpoint OAuth; ou
* publicação administrativa para um workspace compatível, se a conta/plano do ambiente suportar esse fluxo.

## Checklist de pronto para uso amplo

Não considerar o plugin pronto para vários programadores antes de todos estes itens:

* OAuth implementado no MCP;
* usuário humano identificado no `gateway`;
* RBAC por usuário concluído;
* escopos OAuth definidos;
* auditoria vinculada ao usuário;
* aprovação sensível separada do solicitante;
* rate limiting habilitado;
* documentação operacional de onboarding pronta;
* testes de login, expiração, permissão negada e refresh executados;
* registro no ChatGPT validado por mais de um usuário.

## Ordem recomendada de implementação

1. Implementar suporte OAuth no `gateway`.
2. Introduzir identidade e RBAC por usuário.
3. Adaptar auditoria e políticas para contexto multiusuário.
4. Revisar descrições e metadata MCP.
5. Executar testes de autenticação e autorização.
6. Validar no ChatGPT com uma conta real.
7. Documentar onboarding dos programadores.
8. Liberar uso amplo.

## Decisão prática para a próxima etapa

A próxima etapa recomendada neste repositório é:

* implementar OAuth no `gateway`;
* manter `devel3` como único executor;
* manter `frida` como único ponto de entrada;
* só depois disso registrar o app no ChatGPT do usuário final.
