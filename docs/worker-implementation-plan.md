# Plano de implementação — CodexBridge Worker

- Data: 2026-10-16
- Work ID: WK-20261016-worker-control-branch-contract
- Estado: **planejado; nenhuma etapa implementada**
- Contrato: [worker-control-branch-contract.md](./worker-control-branch-contract.md)
- Repositório autorizado para alterações: **EDortta/CodexBridge**, exclusivamente.
- Estratégia de branches de implementação: partir de `development`, uma branch por etapa, testes antes de merge; implantar somente com autorização adicional.

## Objetivo prático

Permitir, a partir do ChatGPT Pro, enviar uma ordem pela branch de **controle
do próprio repositório GitHub de cada projeto**, e obter seu resultado sem
precisar ir ao terminal do devel3. A interface MCP permanece disponível como
caminho **complementar** para leitura do estado e das evidências.

O **CodexBridge Worker** é um **serviço instalável em um computador**, com
suporte planejado a **Linux, macOS e Windows**. Pode operar no mesmo computador
que um Bridge Node/Executor ou em outro host. Não é um Executor, nem uma
alternativa ao Gateway: sua função é observar branches autorizadas, receber
ordens declarativas, encaminhá-las ao Gateway e publicar resultados resumidos.

## Ordem de entrega — não inverter

### Etapa 1 — Script Python de ativação (primeiro incremento)

Criar, **dentro do repositório CodexBridge**, um CLI Python para escolher
quais projetos estarão habilitados ao monitoramento. Nome de trabalho
`scripts/workerctl.py` (ajustável antes de implementar).

Interface proposta:

```console
python scripts/workerctl.py enable --project codexbridge
python scripts/workerctl.py enable --project projeto-b
python scripts/workerctl.py enable --project projeto-c
python scripts/workerctl.py list
python scripts/workerctl.py disable --project projeto-b
```

Contrato de ativação:

- **Máximo de três projetos** habilitados ao mesmo tempo; rejeitar o quarto.
- A ativação individual vale **oito horas corridas** desde o instante
  da concessão, usando timestamp UTC no estado e horário local só para exibição.
- A ativação **não se renova automaticamente**, mesmo com atividade contínua.
- `list` deve apresentar projeto, repositório/branch de controle configurados,
  instante de expiração e estado ativo/expirado.
- `disable` encerra antecipadamente o monitoramento do projeto.
- Projetos expiram automaticamente mesmo se o script não for executado
  novamente; nenhuma ativação vencida pode autorizar novos pedidos.
- Um projeto habilitado não autoriza operações arbitrárias:
  **ativação de monitoramento ≠ autorização de execução**.
- O script **não** instala serviço, não aciona Executor, não dispara GitHub Actions,
  não altera branches de projetos externos nem executa comandos arbitrários.
- No primeiro incremento, usar um arquivo de configuração/estado **local ao
  runtime do Worker**; documentar formato e escrita atômica. A futura
  integração ao Gateway não pode tratar esse arquivo como autorização
  suficiente: o Gateway continua validando identidade e permissões.
- Decidir durante a implementação como centralizar o limite de três projetos
  quando houver **mais de uma instalação do Worker**; não permitir que a
  multiplicação de Workers contorne o limite pretendido.

**Aceite da etapa 1:** testes automatizados de três ativações, recusa da
quarta, expiração após oito horas, reativação explícita, desabilitação,
idempotência, arquivo corrompido e relógio/horário. Nenhum servidor em
produção é alterado.

### Etapa 2 — Serviço Worker multiplataforma

Implementar o Worker como processo de serviço de longa duração, com o mesmo
núcleo Python em Linux/macOS/Windows:

- Linux: integração com `systemd`.
- macOS: integração com `launchd`.
- Windows: integração de serviço do Windows (mecanismo técnico a especificar).
- Configuração sem editar código, inicialização/reinício seguros, logs
  estruturados, parada limpa e estado de saúde.
- Respeitar o conjunto ativado pelo script da Etapa 1; não varrer todos os
  repositórios nem todos os projetos cadastrados.
- Monitoramento por polling limitado, com intervalos/backoff configuráveis;
  registrar último item processado, deduplicar e sobreviver a reinício.
- Isolar credenciais do GitHub e do Gateway em configuração protegida por host.
  Nunca enviar tokens ao conteúdo de requests, logs ou prompts.
- Reconciliar perda de conexão sem repetir execução; quando existirem múltiplos
  Workers, usar controle de posse/lease ou mecanismo equivalente.

**Aceite:** mesmo conjunto de testes de contrato em Linux, macOS e Windows,
mais testes de parada/reinício. O instalador não deve iniciar monitoramento
por padrão sem ativação.

### Etapa 3 — Recebimento e encaminhamento pelo Gateway (Frida)

A ordem percorre obrigatoriamente:

```text
ChatGPT Pro -> GitHub (branch de controle do projeto)
            -> Worker (serviço em computador autorizado)
            -> CodexBridge Gateway (Frida)
            -> Executor(es) autorizado(s) no(s) Bridge Node(s)
            -> Gateway -> Worker -> branch de controle
```

Em paralelo, o ChatGPT pode consultar o Gateway por **MCP de leitura**
quando o conector estiver disponível e autenticado. **O Worker jamais envia
diretamente uma ordem a um Executor.**

- O Gateway autentica o Worker, resolve o projeto lógico, valida ativação,
  operador, autorização, operação e vínculos com Nodes e Workspaces.
- Os pedidos indicam **um Node, uma seleção de Nodes ou todos os elegíveis**.
  O Gateway congela a seleção autorizada ao admitir cada solicitação.
- Cada destino executa sobre o **mesmo SHA de commit solicitado**; nenhuma
  escolha implícita de outro Node se o indicado estiver indisponível.
- Uma solicitação cria N execuções independentes e um consolidado com estados
  explícitos, inclusive falha parcial, incompatibilidade e indisponibilidade.
- Apenas operações de catálogo/política são admitidas. **Sem shell arbitrário**,
  mesmo que uma solicitação esteja presente no GitHub.
- O Gateway detém o estado autoritativo e a auditoria. Não transformar a branch
  nem o Worker em orquestrador concorrente ao Gateway.

**Aceite:** um pedido executado num nó, outro em dois nós e outro em todos os
elegíveis; testes de rejeição por autorização, ausência de Node, repetição de
request e expiração da janela de ativação.

### Etapa 4 — Evidências textuais, segregadas e consulta

Cada projeto terá sua branch exclusiva de comunicação, inicialmente sugerida
como `codexbridge-control`. Não é branch de desenvolvimento e **nunca deve
ser mesclada em `development`**.

Estrutura de resultados proposta **dentro da branch de controle de cada projeto**:

```text
.codexbridge/
  requests/<request-id>.json
  results/<request-id>/summary.json
  results/<request-id>/<node-id>--<hostname>/<attempt-id>/result.json
  results/<request-id>/<node-id>--<hostname>/<attempt-id>/tests.txt
```

- Resultados de hosts distintos não colidem. `node-id` é a identidade estável;
  o hostname identifica o computador de forma legível.
- Tentativas distintas não sobrescrevem evidência anterior; o Worker serializa
  ou reconcilia escritas concorrentes na branch.
- O Worker recebe resultados **do Gateway**, não diretamente dos Nodes.
- Publicar somente resumo e evidências **textuais pequenas**, sanitizadas
  e com limites explícitos. **Ficam fora do MVP APKs, builds, binários,
  pacotes, anexos e outros artefatos pesados.**
- A expiração do período de oito horas impede admitir trabalho novo.
  Trabalhos já iniciados podem concluir e ter seu resultado publicado
  sem renovar a ativação.
- Consulta possível pela branch de controle e, quando disponível, por
  ferramentas MCP de **leitura**. O Gateway não consegue iniciar
  espontaneamente uma mensagem em uma conversa ChatGPT fechada.

**Aceite:** dois Nodes produzem relatórios separados na mesma solicitação e
um `summary.json` consistente, sem colisão, vazamento de segredo ou binários.

## Etapas posteriores, fora do primeiro incremento

- Administração das ativações, permissões e resultados no **CodexBridge
  Control** (web no Frida).
- Administração equivalente no **CodexBridge Mobile** pelo mesmo contrato,
  sem nova autoridade ou estado divergente.
- Eventual notificação de conclusão sem depender de manter o chat aberto,
  usando mecanismo explicitamente suportado e autorizado.

## Restrições de execução desta iniciativa

1. Mudanças de código e documentação apenas no repositório **CodexBridge**;
   nenhum outro repositório é alvo destas etapas sem autorização explícita.
2. Toda implementação deve nascer de `development` em branch própria,
   passar por testes e só então receber merge aprovado em `development`.
3. Alteração de gateway, serviço externo, allowlists, credenciais,
   deployment, reinício, instalação em hosts e scripts de sistema exige
   etapa separada e aprovação explícita.
4. A Etapa 1 vem antes do serviço, do protocolo remoto e do fan-out.
5. Este arquivo é **roteiro**, não evidência de implementação, testes nem
   disponibilidade operacional no ChatGPT.
