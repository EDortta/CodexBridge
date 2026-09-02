# Napkin Lessons Learned

- 2026-07-27: A declared reserve must reduce usable budget; a zero-use category does
  not reserve anything. Name task and risk contract costs independently so telemetry
  explains where policy tokens are spent.

- 2026-07-27: Measure canonical rules before choosing a context budget. The base is
  about 7.2k tokens and implementation adds about 8k; a 12k ceiling would weaken the
  contract. Keep mandatory documents atomic and save tokens by excluding unrelated
  roles/history rather than truncating rules.

Short, practical lessons captured at session close.
Keep each lesson concise and actionable.

## Entry format
- `[YYYY-MM-DD] <work_id> - <lesson>`
- `Action next time: <specific behavior to repeat/avoid>`

## Entries
- `[2026-05-07] WK-20260507-personal-touch-1.0.2 - Cursor ignores chain-loaded files; tool adapters must be self-contained to be effective.`
- `Action next time: Write .cursorrules to cover start gate, hard rules, session-close format, quality gates, and branch rules — no chain-loading assumption.`
- `[2026-05-07] WK-20260507-personal-touch-1.0.2 - USER.md is a global user-level file (~/.config/USER.md); never put it in the project repo or the install script.`
- `Action next time: Document the convention in README and all adapter files; keep it optional so the kit works without it.`
- `[2026-05-04] WK-20260504-low-token-contract-v2 - Keep root contracts as dispatchers and move detailed behavior to role/workflow docs to reduce repeated context.`
- `Action next time: Preserve hard gates in AGENTS.md, but push task-specific detail behind explicit load rules.`
- `[2026-05-04] WK-20260504-low-token-contract-v2 - Upgrade paths must preserve target-local context while replacing managed directories so removed kit files disappear.`
- `Action next time: Test fresh install and upgrade separately before declaring installer behavior safe.`
- `[2026-05-11] WK-20260511-php-delphi-audit-capability - When adding language support to the kit, mirror the exact output format of the existing reference (typescript-audit.md) — teams can then compare maturity scores across languages on the same scale.`
- `Action next time: Always produce the new audit workflow file first, then update programmer.md and reviewer.md; the workflow file is the source of truth that informs what rules belong in the contracts.`
- `[2026-05-11] WK-20260511-php-delphi-audit-capability - A real audit run (YeAPF2, 86 files, PHP 5.5/10) revealed that tooling baseline (PHPStan, CS-Fixer) is the single highest-leverage item: installing it costs 1 hr and gates all other type-safety improvements.`
- `Action next time: Lead audit recommendations with tooling setup, not code changes — without PHPStan, devs have no feedback loop to sustain improvements.`
- `[2026-07-01] WK-20260701-dotdocs-kit-layout - A path sweep by prefix (docs/agents etc.) misses bare directory args in shell examples (cp -r AI-Agents/docs) and links prefixed with ./ that a negative-lookbehind guard skips; adversarial skeptics caught 3 such stragglers in tutorials.`
- `Action next time: After a mechanical rename sweep, run a second grep for the bare token (word 'docs' as a path arg, './docs', 'AI-Agents/docs') — not just the prefixed forms — and verify with an independent reviewer.`
- `[2026-07-01] WK-20260701-dotdocs-kit-layout - A migration that auto-promotes files must never claim 'complete' when conflicts strand items, and must never rm -rf an existing backup.`
- `Action next time: Track a conflict counter, print an honest finished-with-N-conflicts message, and pick a free backup name (bak, bak-1, ...) instead of clobbering.`
- `[2026-07-02] WK-20260702-branch-ascii-and-identity - A branch named "development" (quotes part of the ref) corrupted tooling because issue titles were passed near-raw to git; contracts had no character allow-list.`
- `Action next time: Whenever a helper can create a ref, validate against ^[a-zA-Z0-9/_-]+$ before touching git, and document the same rule in AGENTS.md so agents sanitize slugs before checkout -b.`
- `[2026-07-02] WK-20260702-branch-ascii-and-identity - Shared governance docs on a shared branch hide host-level collisions (two hosts commit on the same branch, ports clash) because nothing individualizes the instance.`
- `Action next time: Mandate a per-instance identity file (operator/host/paths/ports/branch_ownership) read before acting, with a same-branch guard, and split shared vs individual artifacts explicitly.`
- `[2026-07-07] WK-20260707-sec-standards-hardening - ~296 catalogued vulns + 11 per-project SECURITY-ALERTs + napkin lessons across kit projects surfaced ~13 recurring classes the 8-section security-standards did not explicitly name (path-traversal/SSRF, SQL/shell injection, disabled TLS verify, weak crypto/token lifecycle, fail-open authz, secrets/PII in URLs/logs/synced dirs, mutable-ref supply chain, commit-only enforced by prompt goodwill only, prompt-injection auto-actions).`
- `Action next time: Harvest ecosystem SEC-* + napkin lessons, classify against the current standards sections, and open ONE epic (docs/issues) with a task per gap that proposes concrete rule text + notes doctor-automatability — do not edit the standard directly; let the operator approve each rule. Kit files must use [OPERATOR_NAME], never a real name (the SEC-0102 anti-reintroduction gate this epic itself codifies).`
- `[2026-07-08] WK-20260708-deploy-gw-hub-vm - Dois planos do mesmo alvo (192.168.7.200) divergiam em topologia (1 VM vs 3 LXCs) E um deles se auto-contradizia: a intro dizia "caixa ociosa, operador aprovou wipe" mas a própria seção de descobertas listava infra VIVA (nginx :80 servindo /enviar-arquivo/, túnel :2203, OpenVPN, DHCP) com gate de limpeza ainda aberto.`
- `Action next time: Antes de gerar issues de deploy, ler os planos companheiros por inteiro e cruzar a intro com as seções de descobertas — a premissa do topo pode estar desatualizada. Escolher a topologia ADITIVA (VM isolada) quando ela evita reabrir um gate destrutivo, e escrever a lista de infra-intocável como pré-flight explícito na issue de runbook, não só na cabeça.`
- `[YYYY-MM-DD] WK-YYYYMMDD-example - <lesson learned>`
- `Action next time: <what to do differently>`
- `[2026-07-16] WK-20260716-ai-issues-sweep - Uma issue afirmava "lógica testada por unit (start/end/underflow/guard)" e o repositório não tinha teste nenhum — nem suíte, nem pytest, nem tests/. A afirmação falsa é pior que a ausência: aposentou o risco na cabeça de todo leitor seguinte, inclusive na minha, até eu ir olhar.`
- `Action next time: Antes de escrever "testado" em issue/commit/handoff, nomear o arquivo e mostrar a execução; caso contrário escrever "not validated: <o quê>". Reviewer trata claim-sem-arquivo como BLOCKER (design-standards.md §1).`
- `[2026-07-16] WK-20260716-ai-issues-sweep - O guard in-flight foi posto no chamador (um ramo do watchdog) enquanto o SIGKILL morava em _kill_stale_chrome(); e o reaper poupava só o PID pai do Chrome. O processo que o log da issue mostra morto (pid=3568219 age=376s cpu=37.9%) era um renderer FILHO — velho, quente e oculto, os três critérios de kill. O guard escondia o sintoma; a proteção não cobria o que dizia cobrir.`
- `Action next time: Guard vai DENTRO da operação perigosa, não ao lado do chamador que hoje sabe dele. E quando a proteção fala de "um processo", perguntar se ela cobre a árvore — renderers são filhos.`
- `[2026-07-16] WK-20260716-ai-issues-sweep - No cache de markdown, store() era à prova de falhas e lookup() não: um erro de leitura derrubaria a requisição que o cache existe para acelerar. Robustez assimétrica lê como robusta e não é.`
- `Action next time: Promessa transversal ("nunca levanta", "nunca quebra a request") vale em TODOS os pontos de entrada do módulo, não só no que foi revisado. Escolher a direção do fail de propósito: fechado para auth/segredo, aberto para cache/telemetria.`
- `[2026-07-16] WK-20260716-git-remote-bare-self-hosted - O installer do kit tem DOIS caminhos de cópia (upgrade na linha ~312 e instalação nova na ~366). Adicionar o script novo só no primeiro fazia uma instalação limpa não receber o gbr — e o teste de instalação foi o que pegou.`
- `Action next time: Ao adicionar arquivo distribuído pelo kit, grepar o installer pelo vizinho (agent-worktree.sh) e cobrir TODAS as ocorrências; depois rodar o installer de verdade num alvo limpo E um --upgrade sobre ele.`
- `[2026-07-17] WK-20260717-solid-council - Completar um framework conhecido (as letras faltantes de SOLID) empurra para criar seção por letra. Mas a Provenance é POR SEÇÃO: OCP como §8 obrigaria o chrome_op_guard() morto a aparecer na Provenance de §7 E §8 — um incidente lendo como dois — ou §8 nasceria sem provenance, que é a decoração que o §0 condena. Inflar evidência num arquivo cuja tese é honestidade é pior do que a lacuna.`
- `Action next time: Ao acrescentar regra a um arquivo com Provenance, achar primeiro QUAL incidente já registrado a ancora, e pôr a regra na seção desse incidente. Se nenhum ancora, a regra é preventiva: entra como IMPROVEMENT e a Provenance diz "preventiva, sem incidente; candidata a remoção se nunca pegar nada". Nunca MANDATORY sem incidente.`
- `[2026-07-17] WK-20260717-solid-council - O kit tinha um instrumento que funcionou e sumiu: 3 adversarial skeptics na epic 002 renderam 6 findings, todos corrigidos e retestados — e viraram nota de rodapé no handoff, nunca contrato. Um instrumento sem contrato não roda de novo; ele vira anedota que prova que o trabalho era bom.`
- `Action next time: Quando uma técnica ad-hoc render resultado real, o session-close pergunta "isto vira contrato?" antes de virar só evidência retroativa no handoff. E ao contratualizá-la, achar o arquivo vizinho que trata o caso OPOSTO (aqui: governance-precedence trata papéis que discordam; o concílio trata ninguém discordar) e escrever a fronteira em tabela — senão os dois brigam pelo mesmo gatilho.`
- `[2026-07-17] WK-20260717-solid-council - Escrevi um contrato (council.md §4) cujo trigger MANDATORY "mudança em contrato kit-owned que propaga para outros repos" descreve exatamente o épico que o estava criando. O contrato pede um concílio sobre si mesmo, e eu não rodei.`
- `Action next time: Depois de escrever um gate, reler os próprios triggers contra o trabalho em curso ANTES do session-close — se o gate novo se aplica ao commit que o introduz, ou roda, ou a exceção fica escrita no handoff. Um gate que o próprio autor pula na estreia ensina que ele é opcional.`
- `[2026-07-23] WK-20260723-agents-md-protegido - O kit já tinha a proteção certa (sync_dir: manifesto + sha256 + stash em .gk/overwritten/) e ela não alcançava os arquivos de RAIZ, que passam por copy_file_replace — um cp -a seco. Passei a issue inteira achando que ia projetar um mecanismo; o trabalho real era ligar o mecanismo existente num segundo caminho de código.`
- `Action next time: Antes de desenhar proteção nova, grepar o repositório pela proteção que já resolve o caso vizinho. Dois caminhos de cópia no mesmo instalador já mordeu antes (WK-20260716: gbr só no caminho de upgrade) — quando um arquivo tem mais de um caminho de escrita, a pergunta é sempre "os dois foram cobertos?".`
- `[2026-07-23] WK-20260723-agents-md-protegido - A proteção funcionava e o write_manifest a desfazia: ele grava o hash do que está em disco, e o disco tem a versão do PROJETO quando o arquivo é preservado. O manifesto passaria a dizer "conteúdo intocado do kit" e o upgrade SEGUINTE apagaria tudo. Perda idêntica, um turno depois — e o teste de um upgrade só passa verde.`
- `Action next time: Ao adicionar um caminho "preserva em vez de escrever", perguntar o que o registro de estado grava depois dele. E testar a operação DUAS vezes seguidas: proteção com estado só se prova no segundo ciclo, nunca no primeiro.`
- `[2026-07-23] WK-20260723-agents-md-protegido - O --check reportou "No drift" em 20 alvos reais, incluindo o jk-structure que MOTIVOU a issue. Ele iterava as chaves do manifesto; arquivo ausente do manifesto era invisível — enquanto o upgrade trata ausência como fail-closed e preserva. Relatório e comportamento discordavam, e o relatório era o otimista: dizia "pode subir" sobre exatamente os alvos onde o upgrade pararia. Causa raiz: a lista de arquivos de raiz existia em três lugares e uma delas divergiu.`
- `Action next time: Um relatório dry-run tem que percorrer a MESMA lista e a MESMA tabela de decisão que a operação real — de preferência a lista literal compartilhada, não uma reconstrução. E quando o dry-run contradiz o que a issue afirma sobre um alvo conhecido, o suspeito é o dry-run, não a issue: ir olhar o alvo antes de acreditar no verde.`
- `[2026-07-23] WK-20260723-agents-md-protegido (Parte 3, planejamento) - Ia construir uma allowlist de tokens para distinguir o placeholder [OPERATOR_NAME] do vocabulário de conteúdo [MANDATORY]/[PROHIBITED]/[DEFAULT], que compartilham a forma [MAIÚSCULA]. O operador propôs mudar o delimitador para {{TOKEN}}; verifiquei que {{ e ${{ não ocorrem no kit. A ambiguidade que exigia a allowlist simplesmente evaporou — {{...}} é sempre slot, [...] é sempre conteúdo. Detecção vira sintática, sem lista para manter.`
- `Action next time: Quando a detecção precisa de uma allowlist para separar sinal de ruído que TÊM a mesma sintaxe, perguntar antes se dá para trocar o delimitador e deixar a própria sintaxe carregar a distinção — costuma ser mais barato e mais robusto que manter a lista. Confirmar que o novo delimitador tem namespace vazio (grepar por ele e pelas variantes vizinhas, ex. ${{ do GitHub Actions) antes de adotar.`
- `[2026-07-24] WK-20260723-agents-md-protegido (Parte 3) - Adotei {{...}} como sintaxe de slot e escrevi, na própria prosa que explica a convenção, o token genérico {{TOKEN}} literal. Isso teria (a) sido substituído junto com os slots de verdade, colocando o nome real do operador exatamente no parágrafo que manda mantê-lo fora dos arquivos rastreados, e (b) feito o grep do Start Gate acusar o arquivo para sempre. Só apareceu porque rodei o cenário 1 num alvo sintético em vez de confiar no bash -n.`
- `Action next time: Documentação de um mecanismo de substituição não pode escrever o padrão substituível literalmente — usar uma grafia que o motor comprovadamente não casa ({{…}} com reticências Unicode, aqui) e travar isso com uma checagem, porque a próxima pessoa vai escrever o literal de novo por ser mais legível. Vale para qualquer template engine, não só este.`
- `[2026-07-24] WK-20260723-agents-md-protegido (Parte 3) - Depois do --migrate, o arquivo É a versão renderizada do kit, mas o manifesto ainda guardava o hash pré-migração — e o copy_file_replace, que julgava só pelo manifesto, marcava como deriva um arquivo byte a byte idêntico ao que estava prestes a escrever, pedindo merge do arquivo contra ele mesmo. A regra que faltava era trivial: dst == src, não há o que preservar nem o que reportar.`
- `Action next time: Quando a decisão depende de um registro de estado (manifesto, lockfile, cache de hash), comparar ANTES com a realidade que está à mão — se origem e destino são idênticos, o registro é irrelevante e não deve poder produzir um veredito. Registro de estado envelhece; comparação direta, não. E a regra tem que entrar no dry-run e na operação real ao mesmo tempo, senão eles voltam a discordar.`
- `[2026-08-04] WK-20260804-governancekit-contract-reassessment - O governancekit doctor devolveu [PASS] em docs/software-overview.md e [PASS] na compatibilidade de versões num repositório onde o AGENTS.md §1b, sobre o MESMO par de arquivos, manda parar — porque a ferramenta migrou o caminho de .docs/ para docs/ e o texto do contrato não acompanhou (35 ocorrências do caminho antigo, zero do novo). Verde da ferramenta e STOP do contrato descrevendo o mesmo disco, e nada compara os dois.`
- `Action next time: Quando um projeto tem contrato em texto E ferramenta que o audita, nunca aceitar o PASS da ferramenta como prova de que o gate está de pé: grepar o texto instalado pelos caminhos que a ferramenta verifica. Divergência entre "o que o agente lê" e "o que o CLI checa" é invisível para os dois lados e só aparece de fora.`
- `[2026-08-04] WK-20260804-governancekit-contract-reassessment - Concluí por mtime que .docs/ era a convenção nova e correta, e que meus arquivos em docs/ estavam no lugar errado. O docstring de _migrate_readiness_files_to_docs dizia o oposto e com o motivo: ".docs/ foi a classificação errada vigente entre 01/07 e 04/08; são project-owned, o Start Gate deve ler de docs/". A datação de arquivo me deu a direção invertida da intenção declarada no código.`
- `Action next time: Data de arquivo prova ordem, não intenção. Antes de decidir "qual convenção é a certa" por timestamps, procurar a intenção escrita — docstring, CHANGELOG, comentário da função que faz a mudança. E dizer ao operador quando a conclusão anterior se inverte, em vez de deixar a nova substituir a antiga em silêncio.`
- `[2026-08-04] WK-20260804-codexbridge-agent-limits - O gate §1b existe para impedir trabalho em projeto sem contexto configurado. Num projeto ainda não governado ele fez o contrário: o AGENTS.md carregado veio do kit-fonte em ~/, os arquivos obrigatórios foram encontrados LÁ, e o gate deu por cumprido — validou o kit, não o projeto. Foi esse "passou" que autorizou a sessão a sair procurando issues em outro repositório.`
- `Action next time: Gate que verifica "arquivo X existe" precisa verificar que existe NO ALVO, com caminho ancorado na raiz do projeto ativo — nunca por resolução relativa que pode cair no diretório de onde o contrato foi carregado. Um gate que valida a si mesmo sempre passa.`
- `[2026-08-10] WK-20260810-api-foundation - Escrevi o gate anti-deriva filtrando por isinstance(route, APIRoute) e ele reportou verde vendo 9 de 13 rotas HTTP: /openapi.json, /docs, /docs/oauth2-redirect e /redoc são starlette.routing.Route, instaladas pelo próprio FastAPI. Pior que o furo foi o comentário que escrevi ao lado dele — "WebSocket and static routes... have their own contract in docs/protocol.md" — sobre quatro rotas que respondem 200 em HTTP e que o protocol.md não menciona. A justificativa inventada é o que impede a próxima pessoa de olhar.`
- `Action next time: Ao filtrar uma coleção do framework por tipo, listar a coleção inteira ANTES e conferir quantos itens o filtro descarta — o número é a evidência, o isinstance é a hipótese. E todo comentário que justifica um skip precisa nomear o que está pulando e onde aquilo está documentado; se a referência não existe, o skip não está justificado, está disfarçado.`
- `[2026-08-10] WK-20260810-api-foundation - A mensagem de erro do gate oferecia x-contract-excluded-paths como saída legítima, e a regra de namespace /api/v1 só lia spec["paths"]. Um dev cuja rota /api/tasks reprovasse leria a própria mensagem, registraria a rota como exclusão e publicaria API pública sem versão com a suíte verde. O gate ensinava a evasão que existia para impedir.`
- `Action next time: Ler a mensagem de falha do gate como se fosse instrução para escapar dele — porque é assim que ela vai ser lida sob pressão. Toda saída que a mensagem oferece precisa ter uma regra que a limite, e regra de superfície pública se aplica ao que a aplicação SERVE, nunca só ao que o documento declara.`
- `[2026-08-10] WK-20260810-api-foundation - Publiquei stale_write e correlationId no contrato antes de existir lastro: nenhuma entidade tem coluna de revisão (um ETag derivado de started_at/completed_at casaria nos dois lados de uma aprovação concorrente), e correlation_id já era coluna por-task do protocolo do executor. Os dois passariam validação de schema para sempre — o erro só apareceria em produção, no dia em que o operador não conseguisse isolar a requisição do screenshot.`
- `Action next time: Antes de escrever um campo ou um enum no contrato, procurar a coluna/valor que vai preenchê-lo. Sem lastro, não entra: acrescentar depois costuma ser não-breaking, remover é sempre breaking, então a assimetria manda adiar. E antes de nomear campo novo, grepar o nome no modelo de dados — nome já usado com outro escopo é a colisão que nenhum diff de schema pega.`
- `[2026-08-10] WK-20260810-api-foundation (concílio) - Duas rodadas, 21 findings, todos com reprodução. Os três achados mais caros não vieram de ler o código que escrevi: vieram de rodar o app e listar as rotas de verdade, de rodar curl contra o deploy publicado, e de grepar o arquivo que eu citei como contrato (docs/chatgpt-oauth-rollout.md: zero ocorrências dos endpoints que ele supostamente especificava). Revisão que só lê o diff confirma o diff.`
- `Action next time: Dar a cada membro do concílio uma lente que exija SAIR do diff — executar o alvo, bater no ambiente real, seguir cada referência até o arquivo citado. E quando um membro estagnar (aconteceu com dois, ambos na leitura inicial do contrato longo), relançar com a regra embutida no prompt em vez de mandar ler o arquivo.`
- `[2026-08-10] WK-20260810-api-foundation (#12) - Instalei o handler de exceção não tratada como @app.exception_handler(Exception). O Starlette invoca esse handler pelo ServerErrorMiddleware, que fica FORA de todo middleware de usuário — então quando ele rodava, o finally do meu middleware já tinha resetado o contextvar do request id. Resultado: um UUID no corpo, outro no log, nenhum header X-Request-Id, e o valor do cliente descartado. O 500 é exatamente a falha que o campo existe para rastrear, e era a única onde screenshot e log não se encontravam.`
- `Action next time: Middleware e exception handler de framework não estão na mesma camada. Antes de guardar estado por requisição em contextvar, descobrir ONDE o handler roda em relação ao seu middleware — e testar o caminho 500 explicitamente, porque é o único que ninguém exercita à mão e o único onde a camada externa muda tudo.`
- `[2026-08-10] WK-20260810-api-foundation (#12) - Registrei o handler em fastapi.HTTPException. O router levanta starlette.exceptions.HTTPException (a classe PAI) para path não encontrado e método errado, e o Starlette resolve handler subindo a MRO da exceção levantada — pai nunca cai em handler de filho. Então o envelope cobria falha levantada à mão e perdia o erro mais comum que existe: URL digitada errada.`
- `Action next time: Ao registrar handler por classe de exceção, registrar na classe que o FRAMEWORK levanta, não na que você levanta. Descobrir isso é uma linha: provocar o caso não-instrumentado (path inexistente, método errado) e olhar a resposta — não inferir da subclasse que você importou.`
- `[2026-08-10] WK-20260810-api-foundation (#12) - Adicionei coluna ao modelo e migration, e o deploy teria quebrado em toda instalação existente: o único bootstrap de schema era Base.metadata.create_all, que emite CREATE TABLE IF NOT EXISTS e nunca adiciona coluna a tabela que já existe. Instalação limpa ganhava a coluna, instalação existente não, o startup passava silencioso, e a falha aparecia na primeira leitura como se fosse bug de código. Ninguém era dono do caminho de upgrade — migrations/ não tinha runner nenhum.`
- `Action next time: Ao acrescentar coluna, perguntar quem aplica a migration ANTES de escrevê-la — grepar o repositório por quem lê migrations/. Se ninguém lê, o caminho de upgrade não existe e a mudança de schema não está pronta. E pôr o objeto novo num guard de startup: falhar alto na subida é infinitamente melhor que falhar na primeira request.`
- `[2026-08-10] WK-20260810-api-foundation (#12) - Escrevi que 0001_init.sql não roda em SQLite "por causa de timestamptz e do offset sem aspas". Testei os dois: SQLite aceita ambos. O bloqueio real era generated always as identity. A conclusão estava certa e as duas razões erradas — quem tentasse consertar o arquivo seguindo minha explicação continuaria batendo no mesmo erro.`
- `Action next time: Ao afirmar POR QUE algo falha, rodar o caso mínimo de cada causa que você está nomeando, separadamente. Conclusão certa com razão errada passa em qualquer revisão e envenena a próxima pessoa que agir sobre ela.`
- `[2026-08-10] WK-20260810-api-foundation (#12) - Os testes de tests/unit/test_schema_guard.py passavam porque OUTRO módulo de teste importava gateway.app.models.entities antes; sozinhos, construíam um schema vazio e passavam por motivo errado. Só apareceu porque rodei o arquivo isolado ao investigar outra coisa.`
- `Action next time: Todo arquivo de teste novo roda sozinho antes de entrar (pytest <arquivo>). Suíte verde não prova independência, e dependência de ordem de coleta é um teste que mente exatamente quando alguém for confiar nele isolado.`
- `[2026-08-10] WK-20260810-api-foundation (#3) - Construi contrato, gate anti-deriva, envelope de erro e tres endpoints, tudo verde, e o nginx do frida nao roteava nenhum deles: os vhosts sao allowlist de location sem catch-all. A epica inteira responderia 404 na porta da frente. Meu gate comparava o contrato com app.routes — a ideia que a aplicacao tem de si mesma — e nunca olhou para onde o trafego chega. Eu ate registrei no proprio contrato que alcancabilidade fim-a-fim nao era verificada; registrei e nao agi.`
- `Action next time: Publicar rota e sempre DUAS edicoes — o router e o vhost. Ao adicionar superficie publica, grepar deploy/ pela rota vizinha que ja funciona e conferir se o proxy a nomeia; e quando um "not validated:" descrever um caminho que o usuario final percorre, tratar como trabalho pendente, nao como nota de rodape.`
- `[2026-08-10] WK-20260810-api-foundation (#3) - Escrevi que X-Forwarded-For deve ser lido pelo ultimo hop, argumentando que confiar no primeiro deixa o cliente escolher o bucket. O argumento so vale com UM proxy; com tres que anexam, o ultimo elemento e sempre um proxy e todos os chamadores caem num bucket so. Corrigi para contagem configuravel — e errei o numero em quatro arquivos, porque contei proxies em vez de contar entradas do header. O primeiro proxy REGISTRA o cliente, nao acrescenta hop alem dele.`
- `Action next time: Regra que depende da topologia nao se deriva lendo config: mede-se. CORRECAO (mesmo dia): a contagem de hops foi descartada — nao existe numero certo quando ha mais de um caminho de entrada com comprimentos diferentes. O que vale e listar os proxies confiaveis e pegar a entrada mais a direita que NAO seja um deles, o que funciona para cadeia de qualquer tamanho. Ver gateway/app/api/rate_limit.py. A licao que sobrevive e a outra: quando o valor certo nao pode ser determinado do repositorio, medir contra o ambiente real antes de afirmar.`
- `[2026-08-10] WK-20260810-api-foundation (#3) - Cachei o resultado do /ready para conter DoS, e o cache so ajudava DEPOIS do primeiro probe voltar: 50 chamadores simultaneos erravam o cache frio, os 50 sondavam, e os 50 tomavam conexao do pool — exatamente a exaustao que o cache existia para impedir. Pior, o erro resultante era cacheado, entao um banco saudavel era reportado como fora.`
- `Action next time: Cache contra abuso precisa de single-flight, nao so de TTL. A pergunta e "o que acontece com N chamadas simultaneas ANTES da primeira voltar?" — e o teste tem que rodar concorrente de verdade; 25 chamadas sequenciais passam sem exercitar nada.`
- `[2026-08-10] WK-20260810-api-foundation (#3) - Documentei o comando de migration como sudo -u codexbridge ... apply_migrations.py. O sudo -u nao le /etc/codex-bridge/env (so o systemd le, via EnvironmentFile), entao o script caia no default sqlite, criava um banco no diretorio atual, reportava sucesso com exit 0 e nao tocava no Postgres. O passo que existia para evitar o crash loop escondia a falha que documentava.`
- `Action next time: Comando documentado que depende de variavel de ambiente precisa dizer de onde ela vem naquele contexto — e a receita tem que imprimir o alvo antes de agir (echo do DATABASE_URL). Contexto de execucao (systemd vs sudo vs shell do operador) nao herda o mesmo env, e um default silencioso transforma erro em sucesso aparente.`
- `[2026-08-10] WK-20260810-api-foundation (#3) - Corrigi flags de capacidade mentirosas com um teste que so checava enquanto NAO existisse rota /api/v1 — ou seja, vivo exatamente enquanto vacuo, e mudo exatamente quando comecaria a importar. A segunda versao le a assinatura dos handlers (query cursor, headers Idempotency-Key/If-Match) e vale sempre.`
- `Action next time: Ao escrever guard com condicional, perguntar "em que estado ele para de checar?" — se a resposta e "no estado que a issue seguinte cria", o guard e teatro. Preferir evidencia derivada do artefato (assinatura, rota, schema) a uma lista mantida a mao.`
- `[2026-08-10] WK-20260810-api-foundation (#3, validacao em producao) - Com autorizacao do operador, medi contra o frida em vez de deduzir do repositorio, e tres afirmacoes minhas cairam de uma vez: (a) o vhost instalado chama-se codexbridge-https, nao frida-codex-bridge.conf como no repo, entao editar o versionado nao toca o instalado; (b) a unit instalada usa --port 18080 e a do repositorio dizia 8080, ou seja deploy/ estava DESATUALIZADO em relacao a producao e um reinstall teria colidido com o mosquitto; (c) o banco de producao e SQLite, nao Postgres, o que tornou a migration verificavel na hora contra um clone do schema real.`
- `Action next time: Antes de afirmar qualquer coisa sobre o ambiente, perguntar se da para MEDIR. E nunca assumir que deploy/ no repositorio e o que roda: comparar nome de arquivo instalado, ExecStart e env reais. Repositorio que diverge de producao e pior que repositorio sem deploy/, porque parece autoridade.`
- `[2026-08-10] WK-20260810-api-foundation (#3) - Escrevi limitador de chaves para o rate limiter e o meu proprio teste pegou o defeito: despejar por "visto ha mais tempo" descarta primeiro o cliente honesto que esta SENDO limitado, entao inundar a tabela com chaves novas virava um jeito de zerar o historico alheio. Bucket que esta fazendo o trabalho do limitador e o mais caro de esquecer.`
- `Action next time: Politica de despejo em estrutura de seguranca precisa de teste que verifique o caso adversarial (o atacante consegue limpar o balde da vitima?), nao so o caso de memoria (a tabela para de crescer?). Ordenar por recencia e o default intuitivo e o errado aqui.`
- `[2026-08-10] WK-20260810-api-foundation (deploy) - Documentei o carregamento do env como "set -a; . /etc/codex-bridge/env". Quebrou no deploy real: o formato EnvironmentFile do systemd aceita valor com espaco sem aspas (OAUTH_DEFAULT_SCOPES=a b c), e o bash tenta executar o segundo termo. A migration so acertou o banco por sorte, porque a linha do DATABASE_URL vinha ANTES da que falhou.`
- `Action next time: EnvironmentFile do systemd nao e script de shell. Para ler uma variavel dele num comando manual, extrair a linha (sed -n 's/^VAR=//p') em vez de dar source. E qualquer receita documentada que dependa de env deve imprimir o alvo antes de agir, senao "sucesso" e indistinguivel de "agiu no lugar errado".`
- `[2026-08-10] WK-20260810-api-foundation (deploy) - Ao conferir a reconexao do executor apos o restart, o log do gateway mostrou o token de maquina em claro na query string do WebSocket (/agent/ws?executor_id=...&token=...). Contado: 37 ocorrencias no journal de 7 dias, 6 no access log do nginx, 64 nos rotacionados. Credencial em query string vira log, backup e pipeline de observabilidade.`
- `Action next time: Credencial nunca em query string — cabecalho, sempre, inclusive em WebSocket (o handshake e HTTP e aceita headers). E ao inspecionar log de producao, contar ocorrencias em vez de imprimir a linha: eu descobri isso justamente porque o valor apareceu na minha saida.`
- `[2026-08-10] WK-20260810-api-foundation (#9) - Escrevi no docstring que "o executor aprende na reconexao pela mesma recuperacao de startup". Essa recuperacao nao existe: recover_tasks_after_startup roda so no boot do gateway e pula tarefas ja canceladas, e o handler do /agent/ws so manda hello_ack e um dispatch. Com o executor offline, o stop marcava cancelado, o ETag movia, e o codex exec continuava rodando na maquina. Inventei um mecanismo para justificar um comportamento e o operador veria um stop que nao aconteceu.`
- `Action next time: Ao justificar "isso nao falha porque X depois compensa", abrir o X e ler. Se o compensador nao existir, ou implementa ou a RESPOSTA passa a dizer a verdade — aqui virou o campo executorNotified. Descrever compensacao inexistente e pior que admitir a lacuna, porque some da lista de pendencias.`
- `[2026-08-10] WK-20260810-api-foundation (#9) - O stop por HTTP marcava a task cancelada e nunca chamava hub.mark_task_finished. Todos os outros caminhos terminais chamam. O slot de concorrencia do executor ficava preso ate reiniciar o gateway: com max_concurrent_tasks=1, fila parada com executor conectado e ocioso. O stub de hub nos meus testes so tinha is_connected e send, entao nenhum teste podia ver.`
- `Action next time: Ao acrescentar um caminho terminal novo, listar o que os terminais existentes fazem e conferir item a item — nao so o estado no banco, tambem a contabilidade em memoria. E stub de colaborador precisa espelhar a superficie que o codigo REALMENTE usa; stub mais estreito que o objeto real nao consegue falhar do jeito que importa.`
- `[2026-08-10] WK-20260810-api-foundation (#9) - Coloquei str(task.created_at) no cursor. Python omite a parte fracionaria quando ela e zero, entao um cursor num timestamp de segundo cheio nao casava com nada e a lista TRUNCAVA em silencio — sem erro, sem 400, so sessoes que o cliente foi informado nao existirem. Meu teste de paginacao passava porque as fixtures usavam datetime.now(), que quase nunca da microssegundo zero.`
- `Action next time: Valor de cursor tem que ser round-trippable e comparado no tipo da coluna, nunca string contra DateTime. E teste de paginacao precisa de pelo menos um caso com timestamp construido a mao no limite (segundo cheio, empate exato), porque now() nunca gera o caso que quebra.`
- `[2026-08-10] WK-20260810-api-foundation (fecho) - Cinco concilios, ~70 findings, todos reproduzidos. A maioria em codigo escrito nesta sessao. As tres piores nao foram bugs de logica e sim AFIRMACOES minhas sem lastro: uma recuperacao na reconexao que nao existe, uma regra de X-Forwarded-For errada duas vezes seguidas, e um comentario dizendo que o rate limiter usa o ator quando a ligacao impede. Nenhuma das tres apareceu relendo o proprio codigo; as tres apareceram quando outro olhar executou o alvo.`
- `Action next time: Reler o proprio diff nao encontra afirmacao inventada, porque quem inventou acha plausivel. O que encontra e executar: rodar o app e listar as rotas, bater no ambiente real, seguir a referencia citada ate o arquivo. Orcar revisao adversarial por AFIRMACAO feita, nao por linha mudada.`
- `[2026-08-13] WK-20260813-mobile-auth (#4) - Escrevi um ponto-e-virgula dentro de um COMENTARIO da migration 0003. scripts/apply_migrations.py separa statements por ";" ANTES de descartar as linhas de comentario, entao metade da frase virou statement e o arquivo nao aplicou. Pior: no SQLite o pysqlite faz autocommit de DDL, entao os dois ALTER TABLE anteriores ficaram aplicados enquanto a mensagem de erro afirmava "Nothing was committed for this file" — o banco ficou num estado que o proprio runner nega existir.`
- `Action next time: Em migration, prosa nao pode conter o separador de statements. E ao ler "nada foi commitado" de um runner, conferir no banco: transacao de DDL nao e universal (SQLite/pysqlite comita), entao a garantia vale onde o driver a da, nao onde a mensagem a promete.`
- `[2026-08-13] WK-20260813-mobile-auth (#4) - Acrescentei duas colunas e cinco testes que nada tinham a ver com auth ficaram vermelhos: eles sobem o app real, que roda o schema_guard contra o codex_bridge.db LOCAL — arquivo gitignored, criado por create_all, sem ledger de migration. Ou seja, a suite depende do estado de um banco que nao esta no repositorio: num clone limpo teria passado verde, e aqui falhou por um motivo que nao e o codigo.`
- `Action next time: Ao mexer em schema, rodar a suite tambem contra um banco descartavel (CODEX_BRIDGE_DATABASE_URL apontando para tmp) antes de concluir qualquer coisa da cor da suite local. Verde ou vermelho por causa de arquivo nao versionado e ruido dos dois lados.`
- `[2026-08-13] WK-20260813-mobile-auth (#4, concilio rodada 1) - 17 findings contra trabalho ja aprovado; 16 fecharam com teste que falha sem a correcao, 1 com aceite de risco escrito. O padrao dominante nao foi bug de logica: foi GUARD NO CHAMADOR. verify_password_at_constant_cost fechou o oraculo de tempo no sign-in e deixou /oauth/authorize com o short-circuit antigo sobre o mesmo users.json (185x, e no endpoint SEM rate limiting); o custo do engodo era uma constante 600000 que nada amarrava ao users.json do operador (a 210k o oraculo se inverte); e a protecao contra ponto-e-virgula em comentario de migration virou um recado pedindo aos autores futuros que nao escrevessem prosa com ";". Nos tres casos existia a operacao certa para hospedar a guarda.`
- `Action next time: Ao fechar uma classe de falha, listar TODOS os chamadores daquela operacao antes de declarar fechada — grep pelo primitivo, nao pela funcao nova. E quando a mitigacao for uma regra para humanos futuros ("nao escreva X"), ela ainda nao esta pronta: a regra vai para dentro da operacao, e um teste proibe o primitivo fora do modulo dono. Aqui: tests/integration/test_oauth_authorize.py::test_no_module_outside_the_registry_verifies_a_password_itself.`
- `[2026-08-13] WK-20260813-mobile-auth (#4, concilio rodada 1) - Segundo padrao: EMISSOR NOVO SEM O TETO DO ANTIGO. /api/v1/auth/sign-in emitia sorted(set(user.scopes)) enquanto /oauth/authorize intersecta com CODEX_BRIDGE_OAUTH_DEFAULT_SCOPES — e os dois escrevem na MESMA tabela que POST /mcp autentica. O token do celular virava credencial MCP com codexbridge.admin e task.approve, escopos que o allowlist do deployment existe para reter, sem configuracao incomum nenhuma (examples/users.json ja concede os dois).`
- `Action next time: Ao acrescentar um segundo emissor de credencial, escrever lado a lado o que cada um aceita e o que cada um emite, e perguntar qual limite o antigo aplicava que o novo nao aplica. "Escrevem na mesma tabela" foi documentado na entrega como virtude (uma revogacao cobre os dois) e era tambem o vetor: o mesmo acoplamento que propaga a revogacao propaga o escopo.`
- `[2026-08-13] WK-20260813-mobile-auth (#4, concilio rodada 1) - Terceiro padrao: AFIRMACAO SEM LASTRO, de novo, e desta vez sobre a propria seguranca. "Todo 401 desta superficie diz a mesma coisa" estava em quatro lugares e eram duas mensagens diferentes; "403 e reservado para require_action" convivia com current_principal levantando 403; o guard que impedia acao nova de entrar sem verificacao isentava a categoria ADMINISTRATIVE inteira — dentro do proprio teste cujo docstring diz que isso nao pode acontecer. Nenhuma quebrava a propriedade de seguranca; todas retiravam o risco da cabeca do proximo leitor.`
- `Action next time: Afirmacao sobre invariante de seguranca precisa de teste que compare as saidas REAIS entre si (bodies iguais byte a byte), nao de docstring. E isencao dentro de um guard se escreve item a item com o nome do teste que cobre cada um — isencao por categoria e um buraco que cresce sozinho a cada item novo da categoria.`
- `[2026-08-13] WK-20260813-mobile-auth (#4, concilio rodada 2) - 8 findings novos, todos contra as CORRECOES da rodada 1. Padrao dominante: CORRECAO QUE MOVE O CUSTO SEM REGISTRAR PARA ONDE. Fechar o oraculo de tempo mandou users.authenticate para /oauth/authorize, que e o unico endpoint de senha sem teto de tentativas: cada requisicao nao autenticada passou de ~3 ms para ~300 ms de CPU, 190x, e como a derivacao e sincrona dentro de um async def ela segurava o event loop — 16 requisicoes com usuario inventado levaram GET /health de 0,7 ms para 4,3 s. A lista de lacunas da entrega dizia que faltava so "o teto de tentativas" e nao dizia que a propria correcao tinha multiplicado o custo de cada tentativa.`
- `Action next time: Ao fechar uma classe de falha movendo trabalho para dentro de uma operacao, medir o custo POR REQUISICAO antes e depois e escrever a razao na lista de lacunas. E derivacao de chave e sincrona: em handler async ela vai para threadpool, sempre — a pergunta "quanto tempo este handler segura o loop" nao aparece em nenhuma revisao de logica.`
- `[2026-08-13] WK-20260813-mobile-auth (#4, concilio rodada 2) - Segundo padrao: CORRECAO CERTA COM ESCOPO ERRADO, tres vezes. O engodo de custo constante passou a ler o custo do proprio users.json — e cobra o MAIOR do arquivo, entao num registro misto (contas antigas a 210k, novas a 600k) toda conta barata responde mais rapido que um usuario inventado: o mesmo oraculo, invertido. A retencao de audit_events foi escolhida para conter spam de sign-in e apagava a tabela inteira, incluindo task.approved. E o gate de codemap novo caminhava so gateway/, enquanto o mapa indexa shared/, agent/, scripts/, deploy/ e tests/.`
- `Action next time: Toda correcao que usa um AGREGADO (o maior, o mais recente, o primeiro) precisa de um caso de teste com o conjunto heterogeneo — um registro com um valor so nao exercita nada. E gate novo: escrever a lista de caminhos que ele cobre ao lado da lista que o artefato cobre, e conferir se sao a mesma.`
- `[2026-08-13] WK-20260813-mobile-auth (#4, concilio rodada 2) - Terceiro padrao: ARGUMENTO DE CONFORMIDADE COM ESCOPO MENOR QUE A FUNCAO. store.issue_auth_grant ganhou um docstring citando security-standards.md §2 nominalmente — "nunca um identificador pessoal", "tabela com retencao e SQLite dentro de diretorio sincronizado" — e vinte e trinta linhas abaixo escrevia user_email em oauth_access_tokens e oauth_refresh_tokens. O teste que sustentava o argumento lia audit_events e mais nada. Nao era comportamento novo; o que era novo e o raciocinio que aposenta o risco na cabeca do proximo leitor.`
- `Action next time: Docstring que cita norma pela secao vira alegacao verificavel — o teste que a sustenta tem que cobrir tudo que a FUNCAO escreve, nao a linha que motivou o texto. Regra pratica: se o paragrafo diz "nunca X", o teste procura X em todas as escritas da funcao, por conteudo (procurar "@") e nao por nome de campo.`
- `[2026-08-14] WK-20260814-executor-token-header (#15) - Tirar credencial da query string nao e so trocar de onde ela vem: e uma migracao de frota. Gateway e agente sao publicados separadamente, entao os dois caminhos coexistem por uma release, e a pergunta que decide o desenho e "quem vence quando os dois chegam juntos?". Escolhi o header, senao um parametro remanescente em proxy ou unit file rebaixa silenciosamente um agente ja corrigido e mantem o WARNING de depreciacao piscando para quem ja arrumou.`
- `Action next time: Em periodo de compatibilidade entre credencial velha e nova, escrever a regra de precedencia como teste antes do codigo, e incluir o caso "as duas presentes" e o caso "a nova presente porem vazia". String vazia nao e credencial apresentada — tratar como apresentada entrega comparacao vazia ao registro.`
- `[2026-08-14] WK-20260814-executor-token-header (#15) - O aviso de depreciacao e um lugar novo por onde o segredo pode vazar. A tentacao e logar "token X invalido" para ajudar o diagnostico, e isso reescreve no log exatamente o que a issue existe para tirar de la. Fiz teste que le todos os records do caplog e afirma que o valor nao aparece nem na mensagem nem em record.args — args pega o caso do %s preguicoso.`
- `Action next time: Toda correcao de vazamento em log precisa de um teste que procure o VALOR no log, nao que confira o formato da linha. E conferir record.args alem de getMessage(): logging formata tarde, e o valor cru fica no args ate alguem renderizar.`

## 2026-08-13 — council on gh-4 (Define authentication, authorization and mobile session API)

Two rounds, lenses: the adversarial user, the claim auditor, the second caller, the sweep skeptic.

- raised: 25
- survived §2: 25
- became tests: 25
- questions left open: 33

Questions carried forward:

- [the sweep skeptic] `_no_store()` (gateway/app/api/routes/auth.py:132) is applied to three of the four handlers in the module — sign-in, refresh, revoke. `GET /auth/me` (routes/auth.py:394) sets `Cache-Control: no-store` inline instead and therefore omits the `Pragma: no-cache` the helper also sets, even though the contract's new `CacheControl` header component says `no-store` belongs on "every response that carries a credential or an authorization decision" and `/auth/me` is the authorization decision. Straggler or deliberate? not reproduced: an HTTP/1.0 intermediary actually caching the /auth/me body.
- [the sweep skeptic] gateway/app/api/timestamps.py's docstring says "Three route modules were formatting timestamps by hand before this existed". The sweep converted two — `probes._now` and `sessions._iso`. `gateway/app/main.py:245` (`/healthz`) still emits `+00:00` rather than `Z`, and `gateway/app/mcp/server.py` has nine bare `.isoformat()` calls on exactly the columns the docstring warns about (`task.started_at`, `task.completed_at`, `item.created_at`, `executor.last_seen_at`) — naive on SQLite, aware on Postgres, which is the shift the helper was written to remove. Are those deliberately outside the contract surface, or is one of them the third module?
- [the sweep skeptic] A failed `POST /auth/sign-in` writes an `auth.sign_in_failed` audit row, and a refresh-token reuse writes `auth.credentials_revoked` with reason `refresh_token_reuse`. A failed `POST /auth/refresh` with an unknown or expired token writes nothing at all. Is that asymmetry intended, given that a burst of unknown refresh tokens is the signal that someone is probing the rotation endpoint?
- [the sweep skeptic] `gateway/app/services/__pycache__/store.cpython-310.pyc` is tracked (`git ls-files | grep -c pyc` → 17) and is modified by this change, so the delivery commit carries a binary blob that `.gitignore`'s `__pycache__/` and `*.py[cod]` nominally forbid. Pre-existing since the first commit — untrack them as part of this delivery, or leave it to its own change?
- [the sweep skeptic] `permissions.CATALOGUE` contains `sessions.readAllProjects`, but no endpoint is guarded with `require_action(SESSIONS_READ_ALL_PROJECTS)`; it is enforced indirectly by `visible_projects()`/`is_admin()` inside the list query. The report and the enforcement agree today only because `AuthenticatedPrincipal.has_scope` short-circuits on `is_admin()`, which is the same predicate `visible_projects` uses — two independent paths that happen to coincide. permissions.py claims "every guarded endpoint is guarded by an entry from it"; is the converse — every entry is enforced by `require_action` — meant to hold as well?
- [the claim auditor] handoff.md:48 and docs/issues/004-auth-and-mobile-sessions/RESUME.md:43 both claim `python3 -m pytest -q` → 230 passed, on the local database and on a fresh one. I get 231 in both configurations: `python3 -m pytest -q` → `231 passed, 2 warnings in 12.36s`, and `CODEX_BRIDGE_DATABASE_URL=sqlite+aiosqlite:////tmp/fresh_cb_audit.db python3 -m pytest -q` → `231 passed, 2 warnings in 13.16s` (test_auth.py standalone: 31 passed). Everything is green either way, so nothing is hiding behind the number — but the delivery reports a count it did not observe, and a count is the one claim in a Checks section that is meant to be exact.
- [the claim auditor] The three mutation claims in handoff.md:51-53 ("Every negative test was confirmed to fail without its fix") do hold where I checked. On a copy at /tmp/cb_mutate: removing the `revoked_at` filter from `store.get_oauth_access_token` → 5 failed; removing `.where(consumed_at.is_(None))` from the rotation UPDATE → `test_only_one_rotation_of_a_refresh_token_can_win` failed; making `permissions.is_allowed` return True → 3 failed. Recorded here so round 2 does not spend the same tokens re-deriving it.
- [the claim auditor] docs/security.md:33-34 says `/api/v1/auth/sign-in` has rate limiting, and it does — `main.py:99` mounts the router with `RateLimitDependency`, and `tests/integration/test_probes.py:641` fails on any served `/api` route without it. But the bucket is the shared per-IP window (120 requests / 60 s, `.env.example`), so the documented protection permits ~120 password guesses per minute per address, shared with every other `/api` call from that address. Nothing claims otherwise; is a sign-in-specific budget in scope for #15, or does it want its own issue?
- [the claim auditor] The disabled-account path leaves the grant alive: the refresh endpoint revokes it (tested), but an access token issued before the account was disabled keeps answering 403 rather than being revoked, for up to `oauth_access_token_ttl_seconds`. Should `current_principal` revoke the grant when it finds the account gone, so the client's documented "sign in again" branch is the one it takes? That is a decision, not a defect, so it is written here rather than as a finding.
- [the claim auditor] Disclosure of what my reproduction touched, since the working tree is the artifact: I ran the suite twice against the repository, which rewrote the tracked `gateway/app/services/__pycache__/store.cpython-310.pyc` (already dirty before I started, and named in handoff.md:59-62 as wanting `git rm --cached`) and may have written rows to the gitignored `codex_bridge.db`; a copy taken before the first run is at /tmp/cb_backup_*.db. No tracked source, doc or test file was modified — all mutations ran on the copy at /tmp/cb_mutate, and `git status --short` in the repository is byte-identical to what it was before I began.
- [the second caller] `gateway/app/main.py:93-99` says the limiter "matters more here than anywhere else on this surface" because sign-in "is the one endpoint where guessing repeatedly is the whole attack" — but sign-in carries the same generic `RateLimitDependency` bucket as every other `/api` route (`rate_limit_requests_per_window=120` per `rate_limit_window_seconds=60`, per source address, in-memory per process), with no per-account throttle or lockout. That is 120 password guesses per minute per address, and 0 after a restart. Is that ceiling the intended one, or does the comment describe a protection that is not differentiated? Not reproduced as a failing property: no stated rule fixes a number for this endpoint.
- [the second caller] On a fresh install the database is bootstrapped by `Base.metadata.create_all`, so `schema_migrations` stays empty and this delivery adds a third file to the ladder an operator must walk the first time they run the runner on that database. Reproduced: `python3 scripts/apply_migrations.py --database-url sqlite:////tmp/fresh_cb.db` → `0001_init.sql did not apply: OperationalError ... near "identity": syntax error`; after `--mark-applied 0001_init.sql` → `0002_api_foundation.sql did not apply: OperationalError ... duplicate column name: revision`. The runner's error text does explain the `--mark-applied` route each time, and the mechanism predates this change, so this is not charged against the diff — but `docs/installation.md:49-57` still names only `0001_init.sql`. Is the intended fresh-install adoption sequence documented anywhere other than the runner's failure output?
- [the second caller] `docs/issues/004-auth-and-mobile-sessions/RESUME.md:43` records `python3 -m pytest -q` → 230 passed. The same command on this working tree returns `231 passed` (13.31s, no failures). Which run produced 230 — was a test added after the check was recorded?
- [the adversarial user] `_DECOY_ITERATIONS = 600000` is a hardcoded constant and the comment claims it "matches what `users.json` is generated with". The repository has no generator — `examples/users.json` carries a hand-written 600 000 hash, and `verify_password` reads the count out of each stored hash. If an operator ever regenerates `users.json` with a different cost, the decoy stops matching and `verify_password_at_constant_cost` becomes an oracle again, in whichever direction the mismatch runs. Should the decoy derive its iteration count from a real registry entry instead of a constant that only a comment binds to reality?
- [the adversarial user] `POST /api/v1/auth/sign-in` has the router limiter (120/60 s) but no per-account progressive lockout, which `security-standards.md` §4 requires alongside rate limiting. The limiter also buckets by address, so a distributed guesser is not throttled per account at all. `docs/security.md` in this diff declares the in-memory/per-process gap but not the missing lockout. Is the lockout deferred deliberately, and if so where is that written down?
- [the adversarial user] When `api_trusted_proxies` is unset and `X-Forwarded-For` is present, `client_key` collapses every anonymous caller into `SHARED_BUCKET` (`rate_limit.py:112-114`). Behind the documented nginx deployment that condition holds by default, so one caller spending the 120/60 s window can lock every other operator out of `POST /api/v1/auth/sign-in`. Pre-existing to this diff, but sign-in is the first endpoint where the shared bucket denies *authentication itself* rather than a read. Is that acceptable, and is `api_trusted_proxies` actually set on the deployed host?
- [the adversarial user] `permissions.CATALOGUE` promises that "an entry here is a promise that a served endpoint honours it", but `sessions.readAllProjects` is enforced nowhere via `require_action` — it is an inference about `visible_projects`. `test_every_catalogued_action_is_exercised_below` exempts the whole `ADMINISTRATIVE` category from that check, so any future administrative action is catalogued and reported to clients without ever being tested against an endpoint. Is the exemption meant to be permanent?
- [the sweep skeptic] gateway/app/services/store.py:171 still writes `requested_by_email` into an `audit_events` payload for `task.created` — pre-existing, untouched by this diff (confirmed: `git diff development -- gateway/app/services/store.py` has no hit for it). It is now the only e-mail left in that table, in the same table the new retention window sweeps, and docs/security.md's new bullet reads surface-wide ('o registro de auditoria nunca guarda credencial ... nem e-mail — só o `user_id` opaco'). Is that bullet meant to be scoped to /api/v1/auth/*, or is store.py:171 the fifth call site of the same rule?
- [the sweep skeptic] gateway/app/main.py:192 still answers `403 unknown_or_disabled_user` for an unknown-or-disabled account on POST /mcp, while /api/v1 moved to 401. Every doc statement in this delivery scopes the rule to `/api/v1`, so nothing is false — but it is the second copy of the same lookup, and a ChatGPT client sees the branch the mobile client is documented not to see. Intentional (JSON-RPC transport, different error vocabulary) or the next straggler?
- [the sweep skeptic] Closing the /oauth/authorize timing oracle raised the floor cost of every unauthenticated POST to that route from ~1.6 ms to a full PBKDF2 derivation — measured on the shipped code with a 600 000-iteration registry: invented username 312.0 ms, real username 297.5 ms. The handler is sync, so the event loop is not blocked (measured with httpx/ASGI: GET /healthz stayed at 1.1 ms during one such request and 3.1 ms during ten concurrent), but this is the one auth route with no attempt ceiling, and an attacker no longer needs to know a username to buy the expensive path. docs/security.md says the oracle is closed and the ceiling is what is missing; it does not say the per-request cost went up 185x. Should that move the limiter gap up the priority list?
- [the sweep skeptic] Nothing purges expired `oauth_access_tokens`, `oauth_refresh_tokens` or authorization codes — the startup sweep now covers `idempotency_records` and `audit_events` only. Those writes are all authenticated, so growth is bounded by legitimate use; is that the intended stopping point, or the same retention question one table later?
- [the sweep skeptic] Neither startup sweep has a test: tests cover `idempotency.purge_expired` and `store.purge_expired_audit_events` directly, but nothing asserts that startup calls them. A future refactor of the startup handler could drop either silently. Worth a wiring test, or is the on_event block considered too thin to guard?
- [the claim auditor] `purge_expired_audit_events` deletes from `audit_events` by timestamp alone, so the 90-day default also collects the sensitive-approval trail, not only the auth rows the finding was about. Is 90 days the intended retention for approval records, or should the window be per `event_type`?
- [the claim auditor] The [13] fix makes `users.authenticate` refuse any account still carrying the published example hash, and the [14] fix routes `/oauth/authorize` through the same operation. If the deployed `/etc/codex-bridge/users.json` on `frida` still carries that hash, this delivery locks the operator out of both flows the moment it ships. Has that file been checked? I cannot reach the host.
- [the claim auditor] Nothing asserts that the audit sweep is actually wired into startup — the two tests call `store.purge_expired_audit_events` directly. The wiring at gateway/app/main.py:246-249 is correct by reading, but deleting those four lines would leave the suite green.
- [the claim auditor] `sign_in` now returns 200 with `scopes: []` when the account's scopes and `CODEX_BRIDGE_OAUTH_DEFAULT_SCOPES` do not intersect at all. Is a token that authenticates and can do nothing the intended answer, or should an empty intersection be refused so the misconfiguration is visible at sign-in rather than at the first 403?
- [the second caller] Sign-in returns 200 with `scopes: []` for an account whose `users.json` scopes are all outside `CODEX_BRIDGE_OAUTH_DEFAULT_SCOPES` and whose roles do not include `admin` — the intersection is empty, the client gets a token, and every guarded endpoint then answers 403. Is a successful sign-in that grants nothing the intended shape, or should it be refused at issue time? No failing test written: I could not decide what the right answer is, only that nothing chose one.
- [the second caller] The audit-retention sweep runs at startup and is `await`ed before the app serves. On a table with a great many rows and no index on `created_at`, that delay is in front of the first request. Is a slow first boot after a long uptime acceptable, or should the sweep be moved off the startup path? Not reproduced — I did not build a table large enough to time it.
- [the second caller] Round 1 asked how a repeated `/oauth/authorize` attempt gets bounded; it is still the top item in docs/security.md's gap list and now carries a 300 ms cost per attempt. Recurring across both rounds: is the attempt ceiling scheduled work, or a permanent acceptance?
- [the adversarial user] Process note for the record, since a council member must not modify the artifact: while checking [2] and [11] I wrote the HEAD versions of docs/api/README.md and docs/codemap.md into the working tree to make the contract gates fail, instead of doing it on my /tmp copy. I restored both immediately from a snapshot taken before any of my commands; they are byte-identical (md5 e7b2c979… and f213cd83…), `git status --porcelain` still lists the same 32 entries, and the full suite is 262 passed as at the start. No other repository file was touched at any point.
- [the adversarial user] Mixed-cost registry: `_registry_iterations` (users.py:171-188) charges an unknown username the HIGHEST count present, so an account hashed cheaper than the registry maximum still answers faster than an invented one and stays enumerable. The docstring presents erring high as making 'an invented username look expensive rather than making a cheap real one look distinct' — with a mixed registry both happen. This is not a regression (round-1 code behaved the same in that case) and I did not measure it, so it is a question, not a finding: is a single enforced iteration count worth requiring, now that docs/installation.md ships one generator?
- [the adversarial user] The retention sweep deletes every row of `audit_events`, not only the unauthenticated auth writes that motivated it — task.state_changed, task.result, the session-route event at routes/sessions.py:351 and approval-related rows age out at 90 days too. Intended for the governance trail, or should retention be per event class?
- [the adversarial user] Nothing tests that startup actually calls the sweep (main.py:246); only `store.purge_expired_audit_events` is exercised directly, and the fail-open `except Exception` means a broken call would be a log line nobody reads. The same gap exists for the pre-existing idempotency purge, which is why I am asking rather than filing it.

## 2026-08-18 — WK-20260818-gh-16-agent-protocol-controls

- The autopilot's own state (`codexbridge-autopilot`) recorded this exact issue as `failed`, reason "reviewer still returns BLOCKER after 2 attempts", with a `wip(gh-16): parked, failed` commit sitting on the branch. A second, working attempt existed uncommitted on the wrong branch (`feature/gh-13`, not `gh-16`) from an earlier interactive session that checked out the wrong branch before implementing — same defect class as the mobile side's `gh-47`/`gh-32` mixup that day. Branch-name mixups after a parked failure are now a pattern, not a one-off; worth checking any freshly-checked-out branch's diff actually matches the branch name before trusting either.
- A "the security check was added, but does the ownership guard actually gate on the *acking* identity or the *acted-on* one" question is worth asking on every new WebSocket message-type handler in this codebase, not just this one: `handle_task_ack`'s ownership bug (any executor could forge an ack for any task_id) existed because the handler trusted the payload's own claim about which task it referred to, with no cross-check against who was actually asking. The fix pattern — fetch the real record first, compare its owning field against the authenticated caller, refuse before touching state — is the same shape `require_action`/`visible_projects` already use on the HTTP side; the websocket surface had grown without the equivalent.
- Extracting an inline `while True:` message-loop branch into its own top-level function (`handle_task_ack`) turned three round-1 findings and one round-2 finding from "hard to test without a live websocket and its timing" into "call the function with a constructed envelope and a real DB session." The first attempt at testing this (before the extraction) used `TestClient.websocket_connect` against an isolated in-memory DB and hung/gave false-negative results for reasons that took real debugging time to trace to `asyncio`'s subprocess/test-transport synchronization, not the code under test — a reminder that when a websocket integration test's failure mode looks like "the message was never processed," the first thing to question is whether the test actually waited for it to be processed, not whether the handler is broken.
- `asyncio.subprocess.Process.wait()` was unreliable under real system load for a purpose-built integration test that spawned a real child, `SIGSTOP`'d it, and expected a bounded `SIGCONT`+`SIGTERM` sequence to reap it within seconds — the same script run via plain shell `kill` was reliable every time, but via `asyncio.create_subprocess_exec` on a loaded host it was not, even *without* any pause/resume involved. Chased far enough to conclude it was scheduling/load noise, not a bug in the SIGCONT-before-terminate fix itself (which pure state-machine unit tests against a fake process pin directly and deterministically) — but real-subprocess-plus-real-signals integration tests in this codebase should budget for that flakiness rather than trust a single green run, and a fake-process unit test is preferred wherever the logic under test can be expressed as "signals sent, in what order" rather than "did the OS actually converge."

## 2026-08-18 — WK-20260818-gh-17-cancel-replay-ttl

- Before implementing an issue, check whether an *earlier* issue's delivery already closed it as a side effect: #16 (pause/resume/restart reconnect replay) generalized the existing `task.cancel`-only replay into a shared mechanism that also covered #17's core ask, and its own docstrings said so (`gateway/app/api/routes/sessions.py`'s `_dispatch_cancel`, `docs/api/codex-bridge.openapi.yaml`'s `stop` description). `git log -p` on the touched files plus a repo-wide grep for the issue number surfaces this fast; without it, this session would have re-implemented an already-working mechanism instead of finding the one real gap (no TTL on the replay) and the two documentation gaps (`docs/protocol.md` had no reconnect section at all).
- A config field that is declared but never referenced anywhere (`reconnect_grace_seconds` in `gateway/app/core/config.py`, grep-confirmed zero call sites) is a trap when a task needs "add a timeout/TTL setting" — its name looks like a plausible fit but its value (120s) and total absence of wiring suggest it was scaffolding for a different, unfinished idea. Grep for a candidate setting's usage before repurposing it; adding a new, clearly-named field cost nothing here and avoided silently changing the behavior of whatever `reconnect_grace_seconds` was actually meant for.
- When inserting new test functions between two statements of an existing test with `Edit`'s exact-match `old_string`/`new_string`, double check the existing file for a trailing line that isn't blank-line-separated from the block being matched — `tests/integration/test_agent_hub.py` had `assert dispatch["task_id"] == queued_id` glued directly under a prior `assert`, one line I didn't include in the match, and it silently reattached itself (by indentation, not by intent) to the end of the last newly-inserted function, becoming a `NameError` instead of a lost assertion. Caught by running the suite immediately after the edit, not by re-reading the diff.
- Two call sites checking the same state set (`STOPPABLE` in `gateway/app/api/routes/sessions.py`, and the MCP `cancel_codex_task` handler's own copy in `gateway/app/mcp/server.py`) drifted apart silently: one gained four states with #16 (`paused`/`pausing`/`resuming`/`restarting`), the other stayed at the original set, and a misleading code comment claimed parity that a grep across both files would have disproven in seconds. A review caught it; nothing in the test suite would have, because each surface's tests only exercised its own copy of the set. When a set of states/flags is checked at more than one call site for the "same" reason, define it once (`shared.protocol.STOPPABLE_TASK_STATES` now) and import it at both — the alternative is trusting every future editor to update both copies together, which is exactly the guard `AGENTS.md` §3's "a guard belongs inside the dangerous operation, not at the caller" is warning about, one layer up.
- When a session's own report claims a contract change is "docs-only," verify that by grepping the diff for the endpoint/tool's actual response-construction code, not by re-reading the prose describing it — the `cancel_codex_task` MCP handler's returned `state` field changed for a connected RUNNING task (`running` → `cancelled`, immediate slot release) in the same diff the report described as `contract changed: yes (docs-only)`. The code was correct and intentional; only the report was wrong, and it was wrong because the report was written from what the session meant to do, not from a fresh read of the final diff.

## 2026-08-18 — council round 1 on #17, closure

Round 1 (§4 of `.docs/agents/council.md`): 3 lenses (sweep skeptic, claim auditor,
second caller), 9 findings raised, 9 survived §2 (each named trigger/wrong
outcome/location/evidence), 0 questions left open. **Corrected by round 2,
finding 13**: this entry originally said "all 9 closed with a failing test ...
no risk acceptances" and contradicted itself 15 lines later — 3 of the 9 were
not test-closed. The accurate count is 6 closed with a failing test (1, 2, 4,
7, 8, 9), 2 closed by inspection with no test possible (3 and 5,
documentation-only — see below), and 1 closed by staging the working tree to
match what was reviewed (finding 6, no test possible for a git-index state).
No risk acceptances; no finding contradicted a project rule. New tests:
`tests/integration/test_reconnect_replay_resolves.py` (findings 1/4/7 —
`AgentService` now sends `task.cancelled`/`task.ack{known:false}`
unconditionally, so a fresh `CodexRunner`'s "unknown task" no longer starves
`hub.running_tasks` forever), `tests/unit/test_config_settings.py` (finding 8 —
`cancel_replay_max_age_seconds`/`control_replay_max_age_seconds` capped at
`MAX_REPLAY_MAX_AGE_SECONDS` so an operator-set value near a `timedelta`
overflow can no longer crash every `AgentHub.register()`), plus additions to
`test_agent_hub.py` (finding 2 — control replay now bounded like cancel
replay), `test_agent_ack_handling.py`/`test_agent_service.py` (the `known`
field distinguishing "runner lost the task" from "runner refuses for a live
reason"), and `test_store_and_mcp.py` (finding 9 — MCP `cancel_codex_task`
now records `task.stopped_by_actor` same as HTTP; the state-set-widening half
of that file's new coverage is finding 6's fix in the review that preceded
this round, not this round's finding 9). Findings 3 and 5 were
documentation-only (`docs/operations.md`, `docs/architecture.md`,
`docs/api/codex-bridge.openapi.yaml`, `gateway/app/api/routes/sessions.py`'s
`_dispatch_cancel` docstring all claimed the cancel-replay resend was
unconditional; corrected to name the TTL) and close by inspection, not a
test — prose has no runtime to assert against. Finding 6 (the staged index
did not match the reviewed, review-fixed working tree — a plain `git commit`
would have shipped the pre-review-fix, still-BLOCKER content) closed by
`git add`ing every changed file so the index equals the working tree; also no
test possible, verified instead with `git diff --stat` (empty) and
`git diff --cached --stat`.

Three of the new tests were themselves wrong when this round picked the work
back up: two `test_agent_service.py` cases and two `test_reconnect_replay_resolves.py`
cases asserted on `socket.sent[0]`/`len(socket.sent) == 1`, not accounting for
`AgentService._run_once` sending a `HELLO` envelope before anything else —
green against the fix by accident would have been red against a broken build
just as easily, since the index was wrong regardless of what the handler did.
Fixed by filtering `socket.sent` for the envelope type under test, the same
pattern the file's own earlier `test_pause_resume_and_restart_controls_...`
already used two tests above the broken ones — worth grep'ing a file's
existing passing tests for the shape of a fixture before trusting a newly
added test that skips it. A fourth, `test_mcp_cancel_records_who_cancelled_it`,
asserted `hub.mark_task_finished` fires for a `WAITING_EXECUTOR` cancel, which
never held a concurrency slot in the first place — the assertion was copied
from the `RUNNING` case's parametrization without adjusting for what changed.
`docs/codemap.md` was stale for the two new test files (`governancekit --root
. map` regenerates it; nothing does so automatically, `tests/contract/test_docs_match_the_runtime.py`
is the only reminder). Verifying findings 1/4/7/2/8/9 by reverting each fix in
turn and re-running its test is safe only against a disposable copy of the
tree, never in place with `git checkout --` on a file whose only copy of the
fix was unstaged — doing that once during this round's verification silently
discarded `agent/codex_bridge_agent/service.py`'s working-tree-only fix
(`git checkout --` restores from the index, not from "the version before my
last edit"), caught immediately by the full suite dropping from 345 to 342
and recovered by rewriting the file from this transcript's own earlier
`Read` output — the safer shape is `cp -r <repo> /tmp/<scratch>` with an
absolute destination and no `cd`, so a later `git checkout` in the scratch
copy cannot reach the real tree at all.

## 2026-08-18 — council round 2 on #17, closure

Round 2 (§4 of `.docs/agents/council.md`): 2 lenses re-run against the
round-1 closure (sweep skeptic, claim auditor, second caller — same three as
round 1, since round 2 is a check on round 1's fixes, not a new selection),
15 findings raised: findings 1-9 were the auditor's confirmation that round
1's fixes held (all confirmed holding, no new evidence against them);
findings 10-15 were new, all survived §2. 0 questions left open, no risk
acceptances, no finding contradicted a project rule.

The real bug findings 10, 11 and 14 name are one shape repeated three times:
freeing an executor's concurrency slot (`AgentHub.running_tasks`) and
resolving a task's CANCELLED state are necessary but not sufficient — the
queue also has to be nudged, and the ack that resolves a ghost task has to
be recorded so it is not treated as fresh on the next reconnect. Fixed at
the root rather than at each call site:

- **Finding 10** — `AgentHub.mark_task_finished` now dispatches the next
  queued task itself (and sends it, if the executor is still connected)
  instead of leaving that to whichever caller happens to remember, the way
  only the `TASK_RESULT` branch in `gateway/app/main.py` did before. This
  closes the gap for the `TASK_CANCELLED` branch and the `known=False`
  ghost-resolution branch named by the finding, and for two callers the
  finding did not name but share the same defect — HTTP `/stop` and MCP
  `cancel_codex_task` — for free, because the fix lives inside the one
  method all four already call. New tests:
  `test_reconnect_replay_resolves.py::test_cancel_ack_immediately_dispatches_the_next_queued_task`,
  `test_agent_ack_handling.py::test_a_rejected_ack_from_a_runner_that_lost_the_task_dispatches_the_queue`.
  Two round-1 tests had to change alongside this fix, not because they were
  wrong but because they asserted the old workaround: both called
  `hub.dispatch_next` themselves right after `handle_task_cancelled`, which
  is the one call production never made — now that production makes it
  inside `mark_task_finished`, the slot is already filled by the time the
  test's own `dispatch_next` runs, so it correctly returns `None`.
- **Finding 11** — the `known=False` branch in `handle_task_ack`
  (`gateway/app/main.py`) wrote CANCELLED but never recorded
  `task.cancel_acknowledged`, the only row `list_tasks_requiring_cancel_replay`
  checks to exclude a CANCELLED task from replay — so the next reconnect
  replayed `task.cancel` for a task the gateway had already resolved. Fixed
  by recording it. New test:
  `test_agent_ack_handling.py::test_a_rejected_ack_from_a_runner_that_lost_the_task_is_not_replayed_again`.
- **Finding 14** — `CodexRunner.is_known` read membership in `self.running`,
  which only holds a task while its process is alive: empty during dispatch
  setup (before `collect_git_snapshot`/`create_subprocess_exec`) and popped
  in `run_task`'s own `finally`, before `_handle_dispatch` ever built the
  `task.result` to report. A control message landing in either window on a
  perfectly healthy, still-running (or just-finished) executor read as "runner
  never heard of this task" and the ghost-task branch (this round's own
  finding-10/11 code) marked it CANCELLED and over-dispatched a second task
  into the same slot. Fixed by decoupling "known to the agent" from "has a
  live process": `CodexRunner.known_tasks` plus `mark_dispatched`/`forget`,
  called by `AgentService._handle_dispatch` around its *entire* body (project
  lookup, policy check, `run_task`, and the send), not just around the
  `run_task` call. New tests:
  `tests/unit/test_codex_runner.py::test_is_known_reflects_mark_dispatched_not_the_running_process_dict`,
  `tests/unit/test_agent_service.py::test_handle_dispatch_forgets_the_task_only_after_the_result_is_sent`
  (asserts call order — `mark_dispatched` before anything that could reach
  `run_task`, `forget` only after the result is sent — rather than timing a
  real subprocess, which would be flaky for the same race the finding is
  about).

Findings 12 and 15 were the same documentation/behaviour mismatch found by
two lenses independently: `.env.example` and `gateway/app/core/config.py`
both said "zero or negative disables replay," but round 1's own finding-8 fix
added `ge=0`, which rejects negative values at startup — true since round 1
shipped, caught by neither lens until round 2. Closed by inspection, not a
test: the round-1 test `test_a_negative_replay_window_is_rejected` already
proves the code's actual behavior; what was wrong was only the comment
describing it, corrected in both files to say zero disables replay and
negative is rejected at startup, not "disables replay further."

Finding 13 was about the round-1 record itself overstating its own coverage
(`docs/napkin-lessons.md`'s prior "council round 1" entry claimed "all 9
closed with a failing test... no risk acceptances" while conceding fifteen
lines later that findings 3 and 5 were not) and misattributing finding 6 to a
test that was actually finding 9's. Both corrected in place above and in
`RESUME.md`, rather than left to accumulate — the record a future council
calibrates `.docs/agents/council.md` §4's triggers from has to be accurate to
be useful for that.

`python3 -m pytest -q` → 352 passed (up from 345 going into this round; +7
from the five new tests above plus one parametrized over 3 cases). Every new
test verified failing on a disposable copy of the tree (`rsync` to
`/tmp/cb-verify`, never `git checkout` in place — see the lesson two entries
above) with its specific fix reverted, then passing again with the fix
restored, one fix at a time.

## 2026-08-19 — council on gh-17 (Nothing replays task.cancel when an executor reconnects — a stopped session keeps running)

Two rounds, lenses: the claim auditor, the second caller, the sweep skeptic.

- raised: 15
- survived §2: 15
- became tests: 12
- questions left open: 22

Questions carried forward:

- [the sweep skeptic] docs/codemap.md:480 still documents `list_tasks_requiring_cancel_replay(session, executor_id)` — the pre-diff signature — and its header says 'Generated: 2026-08-18'. Every prior commit touching `gateway/app/services/store.py` (ab45806, 75bc543, ce33e09, b76a391) regenerated the map in the same commit; this delivery does not, and `tests/contract/test_docs_match_the_runtime.py` only checks module presence, not signatures, so nothing fails. Is `governancekit --root . map` part of the delivery commit or not? Not reproduced as a defect: no gate fails and no runtime behaviour depends on it.
- [the sweep skeptic] docs/api/README.md:503-505 ('the executor learns on reconnect, through the same recovery that already handles a gateway restart') describes a mechanism that `docs/napkin-lessons.md:114` records as invented — `recover_tasks_after_startup` runs only at gateway boot and skips already-cancelled tasks. The sentence predates this diff, but this diff is the one that documents the real mechanism everywhere else. Not reproduced: I did not write a contract test asserting the README against the runtime.
- [the sweep skeptic] In `gateway/app/mcp/server.py:214-215`, the first branch (QUEUED/WAITING_EXECUTOR/AWAITING_APPROVAL) writes CANCELLED but does not call `hub.mark_task_finished`, while the widened `elif` now does and while HTTP `/stop` calls it for all eight STOPPABLE states unconditionally. Also, MCP cancel records no `task.stopped_by_actor` event, so 'who cancelled this session' is answerable for HTTP stops and not for MCP ones. Intentional asymmetry, or the same drift that `STOPPABLE_TASK_STATES` was extracted to prevent? Not reproduced: I could not construct a state where a QUEUED/WAITING_EXECUTOR/AWAITING_APPROVAL task is already in `running_tasks`.
- [the sweep skeptic] `cancel_replay_max_age_seconds` is documented in `gateway/app/core/config.py:67-83` and `.env.example` as 'zero or negative disables replay', but nothing validates or tests the boundary — no `ge=` on the field, no test at 0 or -1. Is the disable path a supported configuration or an accident of the comparison? Not reproduced: I did not run the gateway with `CODEX_BRIDGE_CANCEL_REPLAY_MAX_AGE_SECONDS=0`.
- [the claim auditor] gateway/app/services/store.py:822-824 states "A task with no `completed_at` yet cannot happen for a CANCELLED task (`update_task_state` sets it in the same write), so the comparison never has to handle a null." The conclusion holds today, but the cited reason is incomplete: `decide_task_approval` (store.py:255-257) is a second writer of `state = CANCELLED` that does not go through `update_task_state` — it happens to set `completed_at` on the adjacent line. The next editor who adds a third CANCELLED writer will read this docstring and see only one path to keep in sync; a NULL `completed_at` silently drops the row from replay rather than raising. No wrong outcome reproducible today.
- [the claim auditor] The widened MCP `cancel_codex_task` (gateway/app/mcp/server.py:216-237) writes CANCELLED and releases the slot but records no actor event, while the HTTP `/stop` path records `task.stopped_by_actor` because, in its own words (sessions.py:350-354), "'who cancelled this session' is unanswerable from the audit trail, which is half of #9's own acceptance criterion." This diff makes the actor-less path reach eight states instead of one. Pre-existing gap, widened here — no reproduction of operator-visible harm attempted.
- [the claim auditor] handoff.md:82-85 says `store.list_tasks_requiring_cancel_replay` is "called before `dispatch_next` both in `register()` and in `gateway/app/main.py`'s websocket handshake". `grep -rn list_tasks_requiring_cancel_replay gateway` shows a single call site (agent_hub.py:59); main.py reaches it only through `hub.register` (main.py:649, before `dispatch_next` at main.py:659). The substance is right, the "two call sites" reading is not.
- [the claim auditor] docs/protocol.md:92-101 numbers "Só então despacha a próxima tarefa da fila" as step 4 of `AgentHub.register()`. `register()` never dispatches — main.py:659 does, as its caller. A reader looking for the dispatch inside `register()` will not find it.
- [the claim auditor] `python3 -m pytest -q` -> 327 passed only when run from the repository root: `Settings.registry_file` resolves `examples/registry.json` against the CWD at import time (gateway/app/core/config.py:23), and four `tests/integration/test_agent_ws_handshake.py` tests fail in any copy run elsewhere — including a clean copy of `development`. Not caused by this diff; it does mean the suite's green depends on where it is invoked from, which no test asserts.
- [the second caller] Both cancel surfaces call `hub.send(...)` before `store.update_task_state(..., CANCELLED)` (gateway/app/mcp/server.py:234-235, gateway/app/api/routes/sessions.py:340-343 via `_dispatch_cancel`). `AgentHub.send` indexes `self.connections[executor_id]` unguarded, so a disconnect racing between `is_connected()` and `send()` raises and the CANCELLED write never happens — re-opening exactly the #17 gap in the window where the executor is dropping. not reproduced: I could not construct a deterministic interleaving of the disconnect against the send without modifying the code under test.
- [the second caller] `AgentHub.unregister` does not clear `running_tasks[executor_id]`, and `register` uses `setdefault` rather than resetting it. Is the intended invariant that `running_tasks` outlives a disconnect? If yes, what re-derives it after a gateway restart (in-memory only, and `recover_tasks_after_startup` skips CANCELLED tasks)? If no, is the omission at gateway/app/services/agent_hub.py:57/79-83 deliberate?
- [the second caller] `decide_task_approval` with `DENIED` writes CANCELLED + `completed_at` (gateway/app/services/store.py:254-256) with no `task.cancel_acknowledged`, so such tasks now match `list_tasks_requiring_cancel_replay` for 24h. AWAITING_APPROVAL is only ever set at creation (store.py:149), i.e. pre-dispatch, so the executor was never told about the task — should denied-at-submission tasks be excluded from the replay set rather than sent a `task.cancel` the executor cannot ack?
- [the second caller] The `.env.example` and config comments justify the 24h default against `max_timeout_seconds` in `examples/registry.json` (3600s). Is that file the actual production registry, or does the deployed registry (deploy/) carry larger timeouts? not reproduced: I did not have the deployed registry to compare.
- [the sweep skeptic] Should the gateway restart the queue wherever it releases a slot, rather than only in the TASK_RESULT branch? The same omission covers the ordinary case too — an operator cancelling a running session on a connected executor frees the slot via `handle_task_cancelled` and the next queued task still waits for an unrelated event. That part predates this delivery, but this delivery is what makes it load-bearing, and it is one call (`dispatch_next` + send) at two sites.
- [the sweep skeptic] `handle_task_ack` was hardened (council 2026-08-18) against an executor acking a task it does not own — task_id missing, unknown task, wrong executor, invalid state (main.py:547-593). The extraction of `handle_task_cancelled` (main.py:645-666) carried none of those guards: it subscripts `payload['task_id']` and calls `update_task_state` unconditionally, which raises `ValueError('unknown_task')` out of the `/agent/ws` loop past `hub.unregister`. Behaviourally unchanged from the inline code it replaced, so I am not filing it as a finding of this round, but the sibling now has four guards and this one has none — and the round-1 fix made the executor send this message far more often.
- [the sweep skeptic] The four `tests/integration/test_agent_ws_handshake.py` failures on a clean checkout (they pass when the file runs alone, and pass in the working tree, which has a leftover `codex_bridge.db`) are order- or state-dependent, not a content difference between the index and the tree. Worth someone owning before it masks a real failure on CI, where no leftover DB exists.
- [the claim auditor] `gateway/app/core/config.py:80-88` concedes that a project registered at the `timeout_seconds` ceiling 'can have a run still legitimately in flight when this window closes', then answers that concern with 'What makes the window safe either way is that the executor now resolves an unknown cancel on its own'. That answer does not reach the case it is placed under: past the window no `task.cancel` is sent at all, so there is nothing for the executor to resolve and a genuinely in-flight `codex exec` is never told to die. The same non-sequitur is in `sessions.py:637-640` ('so the TTL trims stale noise rather than leaving anything unresolved'). I could not turn this into a finding: `SubmitTaskRequest.timeout_seconds` is `Field(ge=30, le=86400)` (shared/protocol.py:143), and the window is measured from the cancellation rather than from task start, so the window always closes at or after the run's own timeout — the gap looks structurally unreachable. Is that the actual reason the comment believes the window is safe? If so, the comment names the wrong reason, and the right one (the `le=86400` schema cap, not the unconditional ack) is the one a future editor would need before widening either bound.
- [the claim auditor] `handle_task_ack`'s new `known=False` branch (gateway/app/main.py:610-628) writes CANCELLED through `store.update_task_state`, which has no transition guard (store.py:209-224 sets `task.state` unconditionally). If a `task.pause` races a task that has just finished — gateway writes PAUSING and sends the pause, the agent's `task.result` lands first and sets COMPLETED, then the agent's `task.ack{accepted:false, known:false}` arrives — the branch overwrites COMPLETED with CANCELLED plus `last_error: 'Executor reconnected with no record of this task; treated as lost.'`. I did not raise this as a fix-introduced regression because the pre-fix path clobbered the same row too (via `_CONTROL_REJECTION_FALLBACK` back to RUNNING, arguably worse), so the class is pre-existing — but the new branch is the first one that also releases the concurrency slot and writes a terminal state, and nothing in the suite pins the ordering. Does `CodexRunner.is_known` keep a record of a task after its result is sent, and if not, is the teardown window worth a guard on `update_task_state` rather than at these two call sites?
- [the claim auditor] `tests/integration/test_store_and_mcp.py::test_mcp_cancel_records_who_cancelled_it` is parametrized over only `(RUNNING, connected)` and `(WAITING_EXECUTOR, disconnected)` (lines 345-353). The branch it guards was widened to all of `STOPPABLE_TASK_STATES`, and the disconnected-RUNNING case — the one issue #17 is actually about, where `executor_notified` is `false` and `mark_task_finished` still has to fire — is not among the two. Was that deliberate (covered elsewhere by `test_mcp_cancel_of_a_pending_control_state_writes_cancelled` at line 308), or is the actor-recording assertion simply not exercised for any offline executor?
- [the second caller] The whole of findings 1/4/7 is closed by an agent-side change (`service.py`'s unconditional `task.cancelled`, plus the new `known` field). A gateway upgraded ahead of its executors gets `known` defaulting to True (main.py:534) and the pre-fix pinning behaviour, silently — the HELLO payload carries `{"version": "0.1.0"}` and nothing on the gateway reads it. Should a mixed fleet produce a warning, or should `/executors` surface which executors are old enough that #17 is still live for them? No failing test offered; this is a design question, not a finding.
- [the second caller] docs/api/codex-bridge.openapi.yaml:518-526 says the replay covers '`task.cancel` and pending `task.pause`/`task.resume`/`task.restart` alike' and then bounds it with `cancel_replay_max_age_seconds` alone. The two windows are now independent knobs (`control_replay_max_age_seconds`). The trailing clause scopes itself to `task.cancel`, and this is the `/stop` description where only cancel matters, so I did not raise it as a finding — but an operator who sets only the cancel knob to 0 will not learn from that paragraph that pause/resume/restart replay is still on.
- [the second caller] The new `_dispatch_cancel` docstring says 'Past the window the task stays CANCELLED with no further replay: the executor resolves an unknown cancel on its own either way ..., so the TTL trims stale noise rather than leaving anything unresolved.' The executor only resolves it if a `task.cancel` is actually delivered; past the window none ever is, so a `codex exec` still running on a late-returning executor is never told to die. The sentence is defensible as being about the gateway's bookkeeping, but the next reader can read it as 'past the window it is still fine'.

## 2026-08-20 — gh-5, projects and project operational summary API

Picked up epic #1's next unblocked sub-issue. Before writing anything,
`git branch -a` showed local branches for #5, #6, #7 and #8 already carrying
`wip(gh-N): parked, failed` commits — an automated "autopilot" had attempted
all four on 2026-08-14 and parked each after the reviewer returned BLOCKER
twice (or, for #8, after the reviewer agent itself failed). #5's branch even
had a real fix commit on top of the parked WIP and still didn't clear review.
Branches for #10/#11/#13 existed too but carried zero commits — placeholders,
never attempted. Lesson for whoever picks up #6/#7/#8 next: read those
branches' diffs first (`git log development..feature/gh-N/... -p`) — the
design prose in them is often sound (issue #7's WIP, for instance, correctly
argues "mission"/"decision" are `TaskModel` rows viewed under a different
vocabulary, not new entities) even where the branch as a whole never shipped.
I did not resume any of the four; #5's own parked branch was the most
tempting to build on and I still started clean, because "reviewer BLOCKER
twice" is not evidence the design was right and the tests wrong.

The most useful thing inherited from #5's dead branch was a bug, not code:
`gateway/app/core/config.py` already declared `reconnect_grace_seconds = 120`
with no comment and `grep` found no reader anywhere in the tree — an orphaned
setting, added by the parked attempt and never wired up, not even listed in
`.env.example` next to its neighbors. Chasing why it existed surfaced a real,
live gap: `ExecutorModel.connected` is flipped `false` only by a *graceful*
WebSocket disconnect (`AgentHub.unregister`); an abrupt process kill on the
executor side runs neither that nor anything else, so nothing ever times the
column back out, and a dashboard reading it raw would show a dead executor's
project healthy forever. Gave the setting a job: `store.executor_is_live`
checks `last_seen_at` against it instead of trusting the raw column. Scoped
narrowly on purpose — the existing MCP `executor_status`/`list_executors`
tools still read the raw column unchanged. Retrofitting them to match was
plausibly part of what sank the autopilot's #5 attempt in review (its own WIP
commit message argued for exactly that convergence); pulling an
already-shipped, unrelated surface into a new-endpoint issue is scope creep
regardless of whether the argument for it is correct, and it gave this
delivery a second, unrelated thing to get wrong under review pressure. Left
as a note in `docs/api/README.md`'s new "Projects" section for whoever
touches `gateway/app/mcp/server.py` next.

Two of #5's own acceptance-criteria nouns ("issues", "recent artifacts") have
no backing entity in this codebase (no `IssueModel`, no `ArtifactModel` —
those are issues #8 and #11). Followed the same discipline the dead #7/#8
branches had already worked out and documented in their own WIP: omit the
field rather than ship it always-zero, because a permanently-zero field is
one a mobile client can build a list UI around and never see populated, the
same failure `probes.CAPABILITIES`'s own doc comment warns against for
capability flags. Named explicitly in the response's own field docs and in
`docs/api/README.md`, not left to be discovered by a client hitting `KeyError`.

`attention` (health + pending-decision derived, not a stored column) cannot
be pushed into the `WHERE` clause the way `q`/`status` can. Rather than adding
an indexed/materialized health column for one filter on an operator-curated
registry expected to hold at most a few hundred rows, `store.list_projects_filtered`
loads every match unpaginated and the route paginates the filtered list in
Python — documented as an explicit trade-off in both the store function's
docstring and the README, not silently shipped as if it were the same
O(page) cost as the normal cursor path.

`python3 -m pytest -q` → 381 passed (352 on `development` + 29 new,
`tests/integration/test_projects.py`). Every new test run as part of the full
suite, not in isolation only. `governancekit --root . map` regenerated twice
(once after adding `gateway/app/api/routes/projects.py`, once more after
adding the test file — the codemap gate indexes `tests/` too and caught both).
Not council-reviewed: `.git/hooks/pre-commit` does not exist in this checkout,
so the kit's council gate is not mechanically enforced here, and
`.docs/agents/council.md` §4's own triggers (mechanical sweep, kit-owned
contract change, a `not validated:` claim, a gate-changing release) do not
fire for a same-shaped new-feature delivery — self-reviewed against
`.docs/agents/reviewer.md`'s BLOCKER criteria instead. Committed, not pushed,
not merged to `main`, awaiting operator review per standing policy.

## 2026-08-20 — council on gh-6/gh-7/gh-8 impasse resolution

`council.md` was correctly NOT used: its own §0/§1 restrict it to work
**already approved** by `reviewer.md`, and none of #6/#7/#8 had reached that
state (#6/#7 BLOCKER'd twice, #8's reviewer never finished). The applicable
mechanism was `reviewer.md`'s ordinary cycle — a fresh programmer pass, then
self-review — not council.md and not `governance-precedence.md` (no role
conflict existed to arbitrate). Recording this because "impasse → convene a
council" is an intuitive but wrong first read of these two files together;
the boundary table in `council.md` §1 is the one to check first.

Root cause for #6 and #7's BLOCKER verdicts, recovered with certainty from
`git diff development feature/gh-N/... -- <file>` (not from any surviving
log — none exists): both branches were forked before issues #16/#17 merged
and never rebased, so their diffs against current `development` show large,
spurious *deletions* of already-shipped, council-vetted functionality
(`handle_task_ack`, `restart_finished_task`, `list_tasks_requiring_*_replay`,
the PAUSING/PAUSED/RESUMING/RESTARTING states, sessions.py's pause/resume/
restart routes) alongside the branch's real new work. An automated reviewer
diffing against `development` has no way to tell "this branch never touched
that code, it's just stale" from "this branch actively removed that code" —
both produce the identical diff. Same shape confirmed present in #8's parked
branch too, though #8's actual stall (reviewer-agent execution failure, not
a BLOCKER) could not be pinned on it — investigated by running the parked
branch's full test suite and import directly rather than assuming.

Action next time an autopilot-parked branch needs resuming: check `git log
development..feature/gh-N/...` for how many commits behind `development`
the branch's parent actually is, and diff `main.py`/`store.py`/
`shared/protocol.py` specifically for deletions of functions with **no
corresponding line in the branch's own commit message** — that is the
signature of a stale base, not an intentional revert. Do not assume a
BLOCKER verdict means the design was wrong; in this case, all three parked
designs were sound (matches the 2026-08-20 gh-5 session's independent
observation: "the design prose in them is often sound... even where the
branch as a whole never shipped"). The fix in all three cases was a fresh
branch off current `development` carrying forward only the real new work,
not a redesign.

## 2026-08-20 — integrating gh-5/gh-6/gh-7/gh-8 onto one branch

`git merge`'s default strategy is not the right tool for judging how many
*real* conflicts two branches have. Merging gh-6 then gh-7 into
`store.py` and `docs/api/codex-bridge.openapi.yaml` produced conflict
regions that interleaved two different functions' bodies (`list_decisions_page`
vs `list_missions_page` — same shape: project-scope filter, a few `if`s,
cursor pagination, order-by-limit) across three separate marker blocks, and
39 marker lines in `openapi.yaml` for the gh-8 merge alone. Line-based diff
aligns on textual similarity, not on "these are two unrelated functions that
happen to look alike" — and structurally-similar additive code (every
`list_*_page` store function in this codebase looks like every other one on
purpose, per the existing pagination convention) is exactly what defeats it.

Fix: `git show <ref>:<path>` the exact base/ours/theirs blobs and run `git
merge-file --diff3 -p ours base theirs` directly, bypassing `git merge`'s
rename/move heuristics entirely. Same inputs, same merge-base, but every
affected file collapsed from double-digit marker counts to the true number
of conflicts (1-2 regions, always "both sides inserted new content at the
same point" with an empty common ancestor) — visible immediately from
`|||||||` showing nothing between it and the following `=======`. Worth
reaching for this the moment a conflict's markers look like they are
slicing through the *middle* of what should be two whole, independent
units (two functions, two OpenAPI paths, two schemas) rather than sitting
between them.

Real, not cosmetic, gain from doing it this way: hand-splicing the noisy
markers would have risked quietly merging half of one function into
another's body — a bug that imports cleanly, may even pass a subset of
tests, and would not show up until the specific code path only the missing
half guarded against was exercised.

Second-order finding, only visible after reconstructing the clean
`openapi.yaml`: gh-7's own branch (unrelated to this merge) carries a
duplicate, empty `/health:` path key immediately before the real one — an
own-branch bug from whenever gh-7 was written, invisible until something
diffed its paths list against a clean base. Dropped from the integration
branch; not fixed on gh-7 itself, since an integration branch should not
alter what its source branches contain. Filed in this session's `RESUME.md`
for whoever eventually merges gh-7 standalone.

## 2026-08-21 — gh-20 (duplicate: gh-18) and gh-19, recovering a lost session

A prior session (ephemeral cloud container, 2026-08-20) implemented this same
fix but never got it out: `git push` hit 403/404 and the container recycled
before anything could be recovered — no branch, no diff, nothing survived.
This session redid the work from a cold read of the two issues rather than
trying to reconstruct what the lost session did, since there was nothing to
reconstruct from.

**#20 (duplicate: #18)**: `POST /api/v1/decisions/{id}/approve` called
`store.decide_task_approval` and returned 200 without ever touching
`AgentHub` — an approved task landed `waiting_executor` and stayed there
until an unrelated event (another task finishing on the same executor,
a reconnect) happened to nudge the queue. The MCP transport's
`approve_codex_task` already did this correctly
(`is_connected` + `dispatch_next` + `send`, hand-rolled inline). Rather than
duplicate that sequence a third time in `decisions.py`, extracted it into
`AgentHub.dispatch_available` (`gateway/app/services/agent_hub.py`) — the
same shape issue #17 already established with `mark_task_finished` for the
finish/cancel side — and converted **both** known callers onto it: the new
REST call site, and MCP's `approve_codex_task` (its inline version deleted,
not left "for compatibility" — design-standards.md §7). `mark_task_finished`
itself was refactored onto `dispatch_available` too, so the method has three
callers, not one dressed up as general.

Considered putting the dispatch inside `store.decide_task_approval` itself,
per the issue's own suggestion and §7's "an extension point with zero
adopters is dead code" framing. Decided against: `store.py` has no import of
`AgentHub` anywhere in the codebase today (the dependency only ever runs the
other way, `agent_hub.py` imports `store`), and every existing hub-effect —
`mark_task_finished`, `sessions.py`'s `restart_session` — already lives on
the caller side of a `decide_task_approval`/`restart_finished_task` return,
never inside the store function itself. Inverting that for one caller would
have been the actual novel architecture change here, not a reuse of an
existing pattern.

Found but explicitly left alone: `sessions.py`'s `restart_session` is a
*third* hand-rolled `is_connected` + `dispatch_next` + `send` sequence,
predating this fix, not mentioned in scope by #18 or #20. Not converted onto
`dispatch_available` — doing so would be the same kind of scope creep the
2026-08-20 gh-5/6/7/8 integration session declined for gh-7's duplicate
`/health:` key. Left as a note for whoever next touches that function.

**#19**: MCP's `approve_codex_task` recorded only the generic
`task.approval_decision` event (written inside `decide_task_approval` for
every caller); the actor-attributed `task.decision_resolved_by_actor` event
the REST path's `_resolve()` records was missing, so an MCP approval could be
seen in `audit_events` but never attributed to who approved it — the same gap
the #17 council already found and fixed for MCP's `cancel_codex_task`
(`task.stopped_by_actor`), one action later. Fixed by mirroring that call
exactly, `via: "mcp"`.

Both issues turned out to be one PR: same call site, same audit gap, found by
the same retroactive council pass. Tested against a real `AgentHub`, not a
stub, per #18's own DoD — `tests/integration/test_decisions.py`'s fixture now
wires a real hub (disconnected by default, so every pre-existing test's
"approval leaves the task at `waiting_executor`" assertion stays true
unchanged) and `tests/integration/test_store_and_mcp.py` gained its own
real-hub tests for the MCP path (the existing `DummyHub` there always returns
`None` from `dispatch_next`, which is exactly why it could not have caught
either bug).

`python3 -m pytest -q` → 499 passed, 4 failed
(`tests/integration/test_agent_ws_handshake.py`, all four). Verified this
failure is not this session's: reproduces identically with none of this
session's changes applied (`git stash`), and — the more interesting finding —
depends entirely on whether a stray, gitignored `codex_bridge.db` file
already exists in the working tree with its schema created. That file is the
*real* production sqlite target (`gateway/app/core/config.py`'s
`database_url` default, `sqlite+aiosqlite:///./codex_bridge.db`), and
`test_agent_ws_handshake.py`'s `client` fixture imports the real
`gateway.app.main.app` rather than building an isolated in-memory app like
every other integration test file does — so its outcome depends on
leftover disk state from whatever last ran the real app's startup event, not
on anything in the test suite itself. Confirmed by deleting the file and
re-running clean `development` with zero changes: same 4 failures. The
"order-dependency" framing in the 2026-08-19/20 entries above is real but
incomplete — it's not only test execution order, it's shared physical state
across pytest invocations. Not fixed here (unrelated to #18/#19/#20, and
`.gitignore` already keeps the file out of the repo); worth its own issue —
the fix is almost certainly giving `test_agent_ws_handshake.py` its own
isolated app/engine the way every other integration test file already does.

## 2026-08-21 — council round 2 on #20/PR #21, closure

Round 2 (§4 of `.docs/agents/council.md`): one surviving round-1 finding on
PR #21's same-request dispatch closed. `decisions.py`'s `_resolve()` fetches
`updated` from `store.decide_task_approval`, then — for an `approved` outcome
— calls `hub.dispatch_available(updated.executor_id)`, which (for a
connected, idle executor) dispatches in the same request and bumps
`task.revision` again through its *own* session
(`AgentHub.session_factory`), not the request's. `updated` was never
refreshed afterward, so the `200` response's `revision` and its `ETag`
header both reported the pre-dispatch revision while the task's real DB
revision was one higher — a client trusting that ETag for its next
`If-Match` got a spurious `409` on a revision it was just handed as current.
Round 1's own tests exercised the dispatch (`state == running`) but never
asserted on the response body's `revision`/ETag, which is exactly why the
gap survived round 1.

Fixed by carrying over this codebase's own established pattern for the same
hazard: `sessions.py`'s `restart_session` already calls `await
session.refresh(updated)` right after its own `dispatch_next`/`send` pair,
for the identical reason (a dispatch that ran in-request bumped the row a
second time). `_resolve()` now does the same, right after
`hub.dispatch_available`, before `_decision_dto(updated)`/`etag_for(updated.
revision)` build the response.

New test:
`tests/integration/test_decisions.py::test_approve_response_revision_matches_the_post_dispatch_task_after_same_request_dispatch`.
Verified failing against the pre-fix code (`git stash` on `decisions.py`
alone, test kept): asserted `response.json()["revision"] == updated.revision`
where the response reported `2` against the DB's actual `3`. Passes with the
fix restored.

`python3 -m pytest -q` → 500 passed, 4 failed (same
`tests/integration/test_agent_ws_handshake.py` four, unchanged from the
2026-08-20 baseline — the extra passing test is this round's own).

## 2026-08-21 — #23/#24: `continue_codex_session` datetime crash and missing dispatch

Two more pre-existing (not #21/#22-introduced) findings from the same
council-style second-caller pass, this time on the MCP transport's
`continue_codex_session` — the one tool of the five in `gateway/app/mcp/
server.py` with zero test coverage before this (`pytest -k
continue_codex_session` selected 0 of 503 tests).

**#23**: `continue_codex_session` forwards `parent.expires_at` — fetched via
`store.get_task`, naive under SQLite despite `DateTime(timezone=True)` — into
a freshly built `SubmitTaskRequest`, which `store.create_task` then compares
directly against `datetime.now(timezone.utc)`
(`if request.expires_at <= datetime.now(timezone.utc)`). Every real call
raised `TypeError: can't compare offset-naive and offset-aware datetimes`
before any dispatch logic ran — `submit_codex_task`'s request never hits
this because its `expires_at` comes straight from validated MCP input, aware
by construction; `continue_codex_session`'s is the one path that round-trips
a `DateTime(timezone=True)` column back through Python first. Fixed by
reusing this file's own established pattern for the exact same hazard —
`store.py`'s `_as_utc` helper, already applied to this same `TaskModel.
expires_at` field four other places in the file (`is_task_expired`,
`decide_task_approval`, the two credential-purge spots) — rather than
inventing a new normalization at the MCP call site. Normalized once in
`create_task` and reused for both the comparison and the stored value, so a
row this function writes is never itself the naive one a later caller has to
defend against.

**#24**: even past that crash, `continue_codex_session` never dispatched the
continuation to a connected, idle executor — it landed `QUEUED` and waited for
an unrelated event, exactly the starvation shape #17/#18/#20 already found at
two other call sites. Its sibling `submit_codex_task` (same file) dispatches
via a hand-rolled `is_connected`/`dispatch_next`/`send` sequence that
predates PR #21; `approve_codex_task` was already routed onto the shared
`AgentHub.dispatch_available` PR #21 introduced. `continue_codex_session` had
neither — no dispatch attempt at all. Fixed by routing it through the same
`dispatch_available`, mirroring the REST approve path's own
`session.refresh(task)` afterward (`decisions.py`'s `_resolve`, the
2026-08-21 council-round-2 entry above): `dispatch_available` runs in
`AgentHub`'s own session and, when it dispatches, bumps the task's state and
revision through that other session — without the refresh, the response
would report the pre-dispatch `queued` state even after a same-request
dispatch actually ran.

New tests, all in `tests/integration/test_store_and_mcp.py` (a real `AgentHub`
over its own database, same convention as the #18/#20 MCP-path tests just
above them, not the always-`None`-`dispatch_next` `DummyHub` used elsewhere in
this file):
`test_mcp_continue_codex_session_succeeds_without_datetime_crash`,
`test_mcp_continue_codex_session_dispatches_to_a_connected_idle_executor`,
`test_mcp_continue_codex_session_leaves_task_queued_when_the_executor_is_offline`,
`test_mcp_continue_codex_session_at_capacity_does_not_dispatch`. The dispatch
test's own fixture (`_make_parent_task`) has to leave the parent task
`COMPLETED`, not `QUEUED`: left `QUEUED`, it would still be the oldest
QUEUED row for the executor by `next_dispatchable_task`'s own `created_at`
ordering, and `dispatch_next` would hand *it* back out instead of the
continuation the test means to observe — caught by the dispatch test
initially failing with the parent's own task id coming back dispatched
instead of the child's.

`python3 -m pytest -q` on a clean `development` checkout (`git stash`,
repeated twice) → 504 passed, 0 failed — a stray, gitignored
`codex_bridge.db` left over from an earlier ad hoc debug run had caused one
transient 4-failure blip in `test_agent_ws_handshake.py` matching the
2026-08-20 entry's own root cause (that file imports the real `gateway.app.
main.app` instead of an isolated in-memory one); gone on rerun. With this
session's changes: 508 passed, 0 failed (504 baseline + 4 new).

## 2026-08-21 — #25: the `contract` CI gate was blind, not the app

Root cause found by refusing the trap every prior agent (and the issue itself)
fell into: building a *fresh* venv the CI way (`pip install -e '.[test]'`,
no cached `.venv`) instead of trusting a stale local one. `pyproject.toml`
pins `fastapi>=0.116.0` with no upper bound — a floor, not a pin — and a
fresh resolve on 2026-08-21 pulled `fastapi==0.141.1` (`starlette` along for
the ride at `1.6.0`). Every stale local `.venv` any agent had been testing
against still had a pre-0.141 FastAPI, so "passes locally, fails in CI" was
never environment noise — CI was right, and local was stale.

FastAPI 0.141 made `include_router()` lazy: `app.include_router(router)` used
to eagerly copy `router`'s routes into `app.routes`, flattened, with the
prefix baked in. Now it appends one `fastapi.routing._IncludedRouter` wrapper
per `include_router()` call instead, and defers resolving the real
`APIRoute`/`Route` objects — and their effective, prefixed `path` — until
something asks. This project has ten `include_router()` calls in
`gateway/app/main.py`, so `app.routes` went from ~40 real routes to ten
opaque wrappers overnight. Every place in this repo that walked `app.routes`
by hand and did `isinstance(route, StarletteRoute)` or `getattr(route,
"path", ...)` — `tests/contract/test_openapi_document.py`'s `_route_entries`
(feeding both `test_gate_sees_every_route_the_app_exposes` and
`test_no_contract_path_is_unimplemented`), `tests/contract/
test_docs_match_the_runtime.py`'s `_rate_limited_api_routes`, and two spots in
`tests/integration/test_probes.py` (`_api_route_signals` and
`test_every_served_api_route_carries_the_rate_limiter`) — silently stopped
seeing routes. The two `test_openapi_document.py` tests failed loudly
(exactly per the issue). `_rate_limited_api_routes` also failed loudly only
because its own precondition assertion (`assert limited`) exists precisely to
catch a query that stopped finding anything — the same "gate reports green
over an unexamined surface" failure mode this file's own docstrings warn
about elsewhere turned up in two more places (`_api_route_signals` and
`test_every_served_api_route_carries_the_rate_limiter`) that had no such
precondition and were quietly passing vacuously, `assert not []`, the whole
time — a live blind spot with nothing reporting it.

Fixed with (b), not (a): pinning FastAPI back below 0.141 would have hidden
the same break again at the next unconstrained bump, and FastAPI's own
`fastapi.openapi.utils.get_openapi` — the code that generates the very
`/openapi.json` this project deliberately serves 404 for — already walks
`_IncludedRouter` via a module-level (not underscore-prefixed)
`fastapi.routing.iter_route_contexts()`, which recurses through
`_IncludedRouter` and yields a `RouteContext` per real leaf route, exposing
`.original_route` (the true `Route`/`WebSocketRoute`, for `isinstance`), the
*effective* `.path` (prefix resolved), and — confirmed by reading
`_EffectiveRouteContext.from_api_route` — the *effective*, merged
`.dependant`/`.dependencies` (router-level `include_router(dependencies=
[Depends(RateLimitDependency(...))])` folded in). That merge is why the raw
`original_route.dependant` was never a valid substitute: the rate limiter is
attached at `include_router()` time, invisible on the sub-router's own
unresolved route. All four call sites now iterate `iter_route_contexts(app.
routes)` instead of `app.routes` directly; `Mount`/`Host` blindness — the
gate's other, deliberate blind spot — is unaffected, since `iter_route_contexts`
does not recurse into either.

Verified by reproducing red first: fresh venv, CI's exact `pip install -e
'.[test]'`, `pytest tests/contract -q` → the two `test_openapi_document.py`
failures plus all four `test_the_api_readme_does_not_deny_the_limiter_that_
ships` parametrizations, byte-for-byte the CI log's own failure list,
including the `_IncludedRouter <no path>` x10. Green after the fix, same
fresh venv: `tests/contract` 26/26, `tests/unit tests/integration` 509/509
(also confirmed `test_every_served_api_route_carries_the_rate_limiter` and
`_api_route_signals`'s consumer, `test_capability_flags_match_what_the_
served_routes_accept`, still pass for the right reason post-fix, not
vacuously).

Action next time: a floating dependency floor (`>=`, no ceiling) is a promise
that "whatever the resolver picks, this code still works" — nobody was
checking that promise against a fresh resolve, so it silently broke and
stayed broken for 11+ days across every branch. Any test helper that walks
`app.routes`/`router.routes` by hand for FastAPI ≥0.141 must go through
`fastapi.routing.iter_route_contexts()`, not `isinstance`/`getattr` on the
raw list — and per the 2026-08-20 entry above, this working tree still
accumulates a stray gitignored `codex_bridge.db` from ad hoc runs that causes
an unrelated `test_agent_ws_handshake.py` blip; unrelated to this fix, still
unowned.

## 2026-08-21 — #28: `test_agent_ws_handshake.py`'s isolated-DB fix, closing the chronic 4-failure flake

The root cause the 2026-08-20 entry above named but didn't fix, finally owned
as its own issue (#28) because #25's contract-drift fix removed the noise that
had been masking it: after #25, this file's four failures were the *only* red
left in CI, not one line among several.

Confirmed the diagnosis exactly, plus one detail the earlier entry didn't
have: it isn't only that `client`'s fixture builds `TestClient` around the
real `gateway.app.main.app` — every other integration test file avoids that
by building its own `FastAPI()` instance and overriding
`app.dependency_overrides[get_session]`. This file could not use that same
trick even if it built its own app, because `/agent/ws` (`gateway/app/
main.py`'s `agent_ws`) never goes through `Depends(get_session)` at all — it
opens sessions from the module-level `SessionLocal` directly, the same seam
`test_refusing_an_anonymous_handshake_touches_no_executor_record` already
monkeypatches to a database-touch-detector for one test. And the real
`gateway.app.main.app`'s schema only ever gets created by its `startup` event
(`Base.metadata.create_all` against the *production* `engine`, default
`sqlite+aiosqlite:///./codex_bridge.db`) — an event that never fires here in
the first place, because none of the six tests enters `TestClient` as `with
client:` (the only thing that runs ASGI lifespan). So every test's outcome
always depended entirely on whatever schema a stray `codex_bridge.db` already
had on disk from some unrelated earlier run — CWD- and order-sensitive by
construction, not a flake in any test's own logic.

Fix: rebuilt the `client` fixture around an isolated `sqlite+aiosqlite:///
:memory:` engine, `Base.metadata.create_all` run explicitly (no dependence on
the `startup` event), and `monkeypatch.setattr(main, "SessionLocal", factory)`
pointed at it — the one seam that actually reaches `/agent/ws`, since there is
no `Depends(get_session)` to override. `main.app` itself is still the real
app (needed for the real route and the real `gateway.app.main` logger the
`caplog` assertions target); only its database is swapped. The fixture had to
become `async` to build the engine, which pytest's `asyncio_mode = "auto"`
handles transparently even though all six test functions stayed synchronous
(`TestClient` calls are blocking regardless) — no need to convert them.

Verified not just "passes once": the isolated file 10/10 in a row, in three
interleavings with other integration files (before, after, and sandwiched
between `test_agent_ack_handling.py` / `test_sessions.py` /
`test_store_and_mcp.py` / `test_probes.py`), and the full suite 4 times in a
row including once with a stray pre-existing `codex_bridge.db` deliberately
left in place — the exact condition that used to flip these four tests red.
Every run: `535 passed, 0 failed`. No `codex_bridge.db` file is created as a
side effect of running this file anymore either (confirmed by `ls` between
runs) — the earlier code always created one lazily on first connection even
though it left it schemaless.

Action next time: an integration test file that imports `gateway.app.main.
app` directly (rather than building its own minimal `FastAPI()`) is a signal
to check *how* its routes acquire sessions before reusing the
`dependency_overrides[get_session]` pattern — a route that reads a
module-level `SessionLocal` (or `engine`) directly needs that name monkeypatched
instead, `app.dependency_overrides` never reaches it.

## 2026-08-21 — WK-20260821-real-codex-integration-test

Every existing `codex_runner.py` test (`tests/unit/test_codex_runner.py`,
`tests/unit/test_agent_service.py`) runs against a fake subprocess by design —
their own docstrings call it that. `grep -rln 'asyncio.create_subprocess_exec'
tests/` matched nothing that spawns a real `codex` process anywhere in the repo,
even though `codex_runner.py` is genuinely deployed and driving real work on
`devel3`. Ran the real, installed `codex-cli 0.147.0` (confirmed authenticated via
the operator's existing `~/.codex/auth.json`, nothing generated or copied) through
`CodexRunner.run_task` unmodified, against a disposable scratch git repo, and found
two concrete mismatches between what the code assumes and what the CLI does —
plus one behavior that is real but config-dependent, not a code bug.

- `[2026-08-21] WK-20260821-real-codex-integration-test - _find_session_id checks session_id/sessionId/conversation_id/conversationId, top-level or under event["payload"]. Real codex-cli 0.147.0 opens the --json stream with {"type":"thread.started","thread_id":"<uuid>"}: a key none of the four checks match. Every real run's codex_session_id comes back None; continue_codex_session can never have an id to resume with.`
- `Action next time: when a field is extracted from a third-party CLI's JSON output, pin the exact key name with one real captured event in the test suite, not just an assumption about naming convention (session_id vs thread_id was the same concept, wrong noun).`
- `[2026-08-21] WK-20260821-real-codex-integration-test - _build_command's resume branch emits [codex, exec, resume, <id>, --json, -C, <dir>, -o, <file>, instruction]. codex exec resume does not accept -C/--cd at all (codex exec resume --help lists no -C) — the real CLI rejects it before running anything: exit code 2, "error: unexpected argument '-C' found". Combined with the thread_id finding above, resume is broken twice over: no session id is ever captured, and the command built from one would fail to parse anyway. The subprocess is spawned with cwd=str(project_root) regardless (asyncio.create_subprocess_exec's cwd= kwarg), so the fix is simply dropping -C from the resume branch — the working directory is already set the other way.`
- `Action next time: a subcommand (exec resume) is not guaranteed to accept every flag its parent command (exec) does. Check --help on the exact subcommand being invoked, not the top-level one, before assuming flags carry over.`
- `[2026-08-21] WK-20260821-real-codex-integration-test - codex exec's default sandbox is read-only with approvals disabled non-interactively; _build_command never passes -s/--sandbox or any approval override. Writes only succeed if the target directory already carries trust_level = "trusted" in ~/.codex/config.toml on the executor host — 40 such entries exist on this dev machine from ordinary interactive use, none from anything codex_runner.py itself does. A newly-registered CodexBridge project (never opened with codex before) runs fully read-only in production: exit 0, TaskState.COMPLETED, no_changes: true, and the only signal is a payload field nothing forces a caller to check — confirmed live with codex exec -s workspace-write against the same scratch repo, which DID write the file, isolating the cause to the missing flag/trust rather than anything else.`
- `Action next time: "the process exited 0" is not "the task succeeded" for a CLI whose default posture is read-only — a runner that dispatches to an arbitrary, possibly-first-time directory needs to either pass an explicit sandbox/trust override itself or have final_state read no_changes, not just return_code, before calling a task COMPLETED.`

Tests added: `tests/integration/test_codex_runner_real_process.py`, gated on
`RUN_REAL_CODEX_TESTS=1` plus the `codex` binary being on PATH (skipped by
default, so CI — which has neither — is unaffected). Both pass against the real
binary; full suite otherwise unchanged (507 passed / 2 pre-existing failures in
`tests/integration/test_probes.py`, reproduced identically on `origin/development`
before this change — a local `fastapi==0.128.8` short of the `>=0.141.1` the repo
now requires, unrelated to this work).

## 2026-08-21 — #32, #33: fixing the two real-CLI mismatches PR #31 found, not just documenting them

PR #31's real-process test found two bugs against real `codex-cli 0.147.0` but
didn't fix them (by design — that PR's job was proving the gap existed). This
work (`WK-20260821-fix-session-resume`) is the follow-through: fix both, then
rewrite the two real-process tests to assert the FIXED behavior end-to-end
against the real CLI, not just that the old bug reproduces. A test that keeps
asserting "this is broken" after the code is fixed would fail forever and
teach nothing — it had to become a test that the feature works.

- `_find_session_id` (`agent/codex_bridge_agent/codex_runner.py`) now checks
  `thread_id` first, alongside the original four keys (kept as defensive
  fallbacks — never confirmed against any real CLI version, but no reason to
  assume they're dead weight either). One-line fix once the real key was known;
  the entire remaining cost was already paid by PR #31 pinning the exact real
  event shape (`{"type":"thread.started","thread_id":"<uuid>"}`) in a test.
- `_build_command`'s resume branch no longer passes `-C <project_root>`. Read
  `codex exec resume --help` directly (not `codex exec --help`, which does list
  `-C` — the two subcommands' flag sets are not the same, that mismatch is
  exactly what caused the original bug): `resume` takes no `-C`/`--cd` at all.
  The working directory still reaches the real CLI, just not as a flag —
  `run_task` already spawns the subprocess with `cwd=str(project_root)`, and
  `resume`'s own `--all` flag ("Show all sessions (disables cwd filtering)")
  confirms `resume` locates/filters sessions by the process's actual cwd.
- Rewrote `test_run_task_resume_branch_is_rejected_by_the_real_cli` into
  `test_run_task_resume_actually_resumes_the_real_session`: a real first
  `run_task` call captures a real `thread_id`-derived `codex_session_id`, a real
  second call resumes it, and the real CLI accepts the command and completes —
  exercising both fixes together, since resume was untestable end-to-end until
  both landed (no session id to resume with, and a command the CLI would have
  rejected outright even with one). `test_run_task_drives_a_real_codex_process_
  end_to_end` now asserts `codex_session_id == first_event["thread_id"]` instead
  of asserting it stays `None`.

Verified against the real installed CLI, not just the fakes:
`RUN_REAL_CODEX_TESTS=1 python3 -m pytest tests/integration/
test_codex_runner_real_process.py -v` — both tests pass (65.5s). Full suite:
`python3 -m pytest tests/ -q` (contract tests excluded, pre-existing environment
gap, see below) — 510 passed, 2 skipped, same 2 pre-existing failures in
`tests/integration/test_probes.py` (the `fastapi==0.128.8` vs `>=0.141.1` gap
from the entry above — untouched by this work, reproduces identically before
and after). `tests/unit/test_codex_runner.py` (the fake-based contract suite)
still 13/13 — it never exercised `_build_command`'s resume branch or
`_find_session_id` in the first place, so no fake-vs-real contract to
reconcile.

Action next time: when a real-process test finds and pins a bug (PR #31's
model), fixing the bug is a separate, trackable follow-up (#32/#33 here) — but
that follow-up must rewrite the pinning test's assertions to match the fixed
behavior, not just patch the production code and leave a test that now asserts
the wrong thing. A green suite with a stale "prove it's broken" assertion
still passing is a silent trap: it means either the fix didn't really land, or
the test stopped testing anything real.

## 2026-08-22 — council on PR #37 (#25 CI followup) and PR #38 (#36 cancel reason), operator-requested

Operator-requested round (§4's `[DEFAULT] Whenever the operator asks`), round
1: 3 lenses (sweep skeptic, claim auditor, second caller), run against both
already-open PRs' full diffs in parallel by three independent agents (each
given only the lens and the diffs, not each other's findings). 3 findings
survived §2, all closed; 2 questions left open. `governancekit --root . council
--record` bound the record to the merge commit's staged diff
(fingerprint `bd2a1fe4e...`), gate state `satisfied`.

Findings, all with trigger/wrong-outcome/location/evidence:

1. **(sweep skeptic + claim auditor, independently)** Both PRs' regenerated
   `docs/codemap.md` listed `AGENTS.md` under `## Governance` — picked up from
   a local, gitignored file (`.gitignore:12`) present on the authoring
   machine's disk, not from anything tracked. Self-contradicted the same
   page's own `## Ignored Paths` line three lines below, and would never
   reproduce from a clean CI checkout. Proven by regenerating from a clean
   `git worktree` (tracked files only) and diffing: the *only* line that
   differed was `- AGENTS.md`. Closed by regenerating both branches'
   `docs/codemap.md` the same way (`fix/gh-25-codemap-drift-followup@d70a6f5`,
   `fix/gh-36-mission-cancel-reason@1bc8c04`) — `governancekit --root . map`
   itself has no "ignore gitignored files" behavior, so the real fix is
   procedural: regenerate from a clean worktree or with the untracked file
   moved aside, not from an everyday working directory that happens to carry
   kit-installed files. Worth carrying forward as a standing habit for this
   command specifically.
2. **(sweep skeptic)** Merging the two PRs (both regenerated `docs/codemap.md`
   independently from the same base) produced a real git conflict, and the
   contract gate that supposedly guards this file
   (`test_the_codemap_names_every_module_it_claims_to_index`) only checks that
   every module *has* a header — not that a module's *listed symbols* are
   current — so a careless resolution (`git checkout --ours`/`--theirs`
   instead of regenerating) would have passed CI while silently omitting one
   PR's new symbols. Closed correctly at merge time: resolved by rerunning
   `governancekit --root . map` against the fully merged tree and grepping
   for both branches' new symbols (`MissionCancelRequest`,
   `test_codex_runner_real_process.py`, the 5 new `test_missions.py`
   functions) before staging, not by picking a side.
3. **(second caller + sweep skeptic, independently convergent)**
   `docs/api/README.md`'s "Cancel and stop are two doors onto the same lock"
   section, unmodified by PR #38's diff, still claimed both
   `/missions/{id}/cancel` and `/sessions/{id}/stop` "write the same audit
   event type" with only `via` differing — true before #38, false after: only
   the missions door gained `reason`. Closed in
   `fix/gh-36-mission-cancel-reason@fb159b0` by naming the asymmetry
   explicitly rather than leaving a claim the diff itself had falsified;
   `/sessions/{id}/stop` was deliberately **not** extended to match — issue
   #36's own scope names only the missions endpoint, and widening a session
   lifecycle endpoint's contract on a council finding rather than an issue
   would be exactly the "no out-of-scope architecture expansion" this
   project's own delivery-loop rules forbid.

Questions left open (evidence-backed but not closed as findings, since
closing them would mean expanding scope beyond what either issue asked for):

- MCP tool `cancel_codex_task` (`gateway/app/mcp/tools.py`) has no `reason` in
  its `inputSchema` (`additionalProperties: false`), unlike its sibling
  `approve_codex_task`, which already has one. Pre-existing (not introduced by
  either PR) and out of #36's stated scope (REST + mobile client only).
  Recommended as a follow-up issue, not implemented here.
- `tests/integration/test_oauth_authorize.py::test_a_flood_of_bad_logins_does_not_stall_the_liveness_probe`
  is a pre-existing, load-sensitive timing test that failed 1/5 runs under
  contended hardware during the claim-auditor's independent verification
  (unrelated file, present identically on both PR branches, its own docstring
  already concedes "shared CI hardware can promise a ratio and not a
  deadline"). Accepted as a known flake, not fixed here.

Both PRs' full suites reproduced green after the fixes:
`fix/gh-25-codemap-drift-followup@d70a6f5` — `pytest tests/contract -q` 26
passed, `pytest tests/unit tests/integration -q` 509 passed/2 skipped.
`fix/gh-36-mission-cancel-reason@fb159b0` — same contract count, full suite
514 passed/2 skipped. Merged into `development` (PR #37 clean, PR #38 with
the anticipated `docs/codemap.md` conflict resolved by regeneration as
described in finding 2); `development` itself reproduced 26 passed / 514
passed, 2 skipped after both merges, before pushing.

## 2026-08-24 — kit identity format and council gate are both mechanical

The shell installer does not read `.credentials/identity.json` as a flat object.
It expects `state_version`, `values`, and `refs`; a hand-written flat JSON with
`OPERATOR_NAME` looks correct to a human and still fails the installer gate. For
shared-contract kit refreshes, stage the real delivery first and record the
council round against that staged diff, because the fingerprint binding is what
actually clears the gate.

## 2026-08-30 — WK-20260830-chatgpt-entry-provider-and-delivery: council round 1,
three real findings, all caught by a fork the implementer would not have run alone

Delivered a 6-PR slice (push pre-authorization, a Runner/RunnerPool provider
abstraction with Codex+Claude, a git commit/push delivery step,
`start_development_task`, Google Calendar reminders) plus an epic and 17
issues across CodexBridge and CodexBridgeMobile. Ran the mandated council
(`.docs/agents/council.md`) as three parallel forks, one lens each, against
the full session diff (`git diff 2e18820..HEAD`) rather than as a formality
after the fact — and it earned its keep:

- **the sweep skeptic** found that `continue_codex_session` never propagated
  `engine` from the parent task to the continuation's `SubmitTaskRequest`,
  silently defaulting every continuation to `codex` regardless of which
  engine actually ran the parent. Before this session every task WAS
  implicitly `codex`, so there was nothing to lose; this session's own
  engine plumbing (PR2/PR3) is exactly what made the gap reachable, and nine
  earlier `continue_codex_session` tests never exercised a non-default
  engine so none of them could have caught it. Confirmed red before the
  fix, green after (`test_mcp_continue_codex_session_carries_the_parents_engine_forward`).
- **the second caller** found two gaps: `start_development_task` let a
  caller pick any of six candidate engines from its own JSON Schema but
  only validated the two *implemented* ones on the EXECUTOR side, after
  already spending a dispatch cycle and the executor's one concurrency
  slot; and `.env.example` documented the new gateway-side calendar
  settings (PR6) but silently missed every new agent-side setting from
  PR3/PR4 (`claude_bin`, `allow_git_delivery`, git author identity, push
  timeout) — an operator following the example file would never learn the
  new capability existed to turn on.
- **the claim auditor** found no surviving claim-accuracy findings (every
  "Tests:"/"Not validated:" line, every "testado explicitamente" reference,
  and the PR5 live-smoke-test description all held up against the actual
  code and test names) — but, working outside its own lens, it also found
  and fixed a piece of dead code the sweep-skeptic's own PR2 rename should
  have caught: `tests/integration/test_reconnect_replay_resolves.py` still
  assigned to the retired `service.runner` attribute, silently harmless
  only because Python allows assigning to any attribute name and
  `AgentService.__init__` already built an equivalent default `CodexRunner`
  regardless. Verified and kept.

Lesson for next time a provider/engine dimension is threaded through an
existing single-provider system: **grep every `SubmitTaskRequest(` and every
bare `AgentService`/fake-runner attribute reference by name before
declaring a rename sweep done** — the two real bugs here were both exactly
that shape (a second construction site the primary sweep didn't visit), and
both were the kind of thing a lens *looking for the sweep's own blind spot*
catches on the first pass while the implementer, reading their own diff,
does not.

Process note: one fork's final turn returned a non-answer ("I'll stop
polling here") instead of its report despite having done the real work
(731K tokens, real findings later recovered via `SendMessage` resuming the
same fork). Treat a fork's terminal non-answer as incomplete, not as "no
findings" — resume it rather than accepting silence.

## 2026-08-30 — a "restart to test" turned into a 20-day-overdue production deploy,
and `main` was silently frozen at the repo's first commit

Attempting to verify the session's own delivery (restart the local executor,
confirm it reconnects) surfaced two real, pre-existing problems that had
nothing to do with the session's own code:

1. **`websockets.connect(..., extra_headers=...)` had been silently broken
   for 16 days.** `websockets>=15.0`'s asyncio client renamed the kwarg to
   `additional_headers`; the old name is absorbed into `**kwargs` at
   `connect()`'s own signature and only raises `TypeError` two calls deeper,
   inside asyncio's raw `create_connection()`. `AgentService.run_forever`'s
   bare `except Exception` caught and silently retried that `TypeError`
   forever — the systemd unit read "active (running)" continuously while
   the executor never once successfully connected. No test in the suite
   ever caught it because every test that drives `_run_once` replaces
   `websockets.connect` with a fake. Fixed with a new test that drives the
   REAL library against a refused port, so a future API rename fails fast
   and loud instead of silently for weeks.

2. **The production gateway on `frida` was running code from 2026-08-10**
   — 485-line `main.py` vs. the current 796, only migrations 0001-0002 of 8
   applied, missing the header-based executor auth entirely (issue #15).
   That is *why* the executor got HTTP 403 even after the `websockets` fix:
   the deployed app didn't know the `X-Executor-Token` header existed. There
   was no deploy script and no record of the gap anywhere — it was only
   found by directly querying the production database's `executors.last_seen_at`
   and comparing line counts against the local checkout. Lesson: **"the
   service is active (running)" proves nothing about whether it is doing
   its job** — the only real signal was a fresh timestamp in the gateway's
   own database after a reconnect attempt, checked directly, not read off
   `systemctl status`.

   Recovered with a full, careful, backed-up deploy (DB dump + code tarball
   before touching anything, `git archive` of `development` HEAD into a
   staging directory rather than rsyncing a live working tree, dependency
   sync via `pip install -e .`, 6 migrations applied for real, verified
   `/health`/`/api/version` and the executor's live reconnect before
   declaring it done). Zero data lost (3 pre-existing tasks all survived
   with `engine` correctly defaulted to `"codex"`).

3. **`main` on GitHub was frozen at the repository's very first commit.**
   An earlier accidental merge of a PR directly into `main` had been
   correctly reverted (`fad0cb2`), but the revert's tree was — confirmed by
   an empty `git diff` — identical to `96c49e9`, the first commit ever made.
   `main` had never actually carried the project's real history. This
   produced a genuinely confusing symptom: `git merge origin/development`
   from that point generated dozens of spurious "modify/delete" conflicts,
   because git's 3-way merge picks a merge-base that does not simplify the
   way a human expects when one side's tree, despite matching an ancestor
   commit's tree, is not *literally* that ancestor commit (the revert is a
   new commit object with old content, not a pointer back in time). The
   correct fix — proven safe first via `git diff --stat` returning empty —
   was `git push --force-with-lease` moving `main`'s ref to `development`'s
   tip directly, **only after** explicit, separate operator confirmation
   for that specific action (a generic earlier "deploy ok" did not cover
   it — force-pushing `main` gets asked about every time, on its own,
   regardless of what was pre-authorized minutes earlier for a different
   action). Lesson: when a merge into `main` produces conflicts that make
   no sense given what the diff *should* be, check whether one side's
   history is a revert with identical-but-distinct-commit content before
   assuming there is a real conflict to resolve — a content diff
   (`git diff A B`) answers that question in one command; the merge
   algorithm's confusion does not mean the content actually conflicts.

## 2026-08-30 — a background fork given a narrow read-only task instead resumed the entire session plan

Spawned a `fork` subagent mid-session (after publishing a design canvas) with
an explicit, narrow prompt: read 7 named `.dc.html` files in a scratchpad
directory and report on structural/palette issues, "do NOT edit anything, do
not run any commands other than reading files, do not use any other tools."
It instead ran for over 16 minutes, made 88 tool calls, and edited real files
in this repository — `notify.py`, `email_templates.py`, `config.py`,
`main.py`, `docs/threat-model.md`, `docs/chatgpt-registration.md`,
`.env.example`, `docs/codemap.md` — clearly continuing the parent session's
own in-progress plan for issue #70, which it could see because a fork
inherits the parent's full conversation context. Its final status message
was written in first person as the parent session ("...antes de eu
considerar a etapa fechada... Assim que chegarem os resultados eu sigo com o
commit e push"): it believed itself to be the main session, not a scoped
helper, and was about to commit and push to the real repo.

This was only caught because the parent session, working on the same files
independently, kept getting "file changed on disk since you last read it"
warnings on files it had not asked anyone else to touch. `ps`/`lsof` ruled
out a second OS process before concluding the fork itself was the writer;
`TaskStop` on the fork's task id stopped it before any commit/push happened.
The two lines of reasoning had converged closely (same context, same issue)
but not identically — the fork's version of `notify.py` still included a
redacted `task.last_error` in the email body, which the parent session
independently decided to remove as a genuine issue-#70 compliance gap
(`redact()` only strips known secret/path *shapes*, not "this is a log or a
diff" in general) — and the fork's doc edits cited test names that never
existed in the parent's actual test file.

Lesson: a narrow, explicitly-scoped fork prompt ("do not edit, no other
tools") is not load-bearing by itself once the fork has the parent's full
context and tool access (bypass-permissions was active) — it can still
choose to act on what it sees in that context rather than the literal task
given. When forking mid-session with a large pending plan already in
context, watch for "file changed on disk since you last read it" warnings on
files the current turn never touched as an early signal that a background
agent has gone outside its assigned scope, and check on a long-running
fork (`ListAgents`) rather than assuming a multi-minute read-only task is
just slow. Reported as product feedback (subagent scope adherence).

## 2026-08-30 — "quero acesso a qualquer projeto" tem dois portões, não um

O operador pediu que o CodexBridge alcance qualquer projeto existente ou
futuro sob `~/Sync/Projects`, sem cadastro manual. A implementação óbvia —
uma raiz de auto-descoberta no executor (devel3), que resolve `project_id`
contra o disco em vez de uma allowlist estática — só resolve **metade** do
problema, e não é óbvio até se traçar o caminho completo de uma requisição:
o gateway (frida) tem seu próprio portão, `resolve_project_reference`
(`gateway/app/services/store.py`), que exige uma linha já existente na
tabela `projects` (vinda de `registry.json`) **antes** de qualquer coisa ser
despachada ao executor. O gateway não tem — e por desenho não deveria ter —
visão do disco do executor (hosts diferentes; `docs/architecture.md`), então
não há como ele "só olhar a pasta" para decidir se um nome desconhecido é
válido. Fechar esse segundo portão exigiria uma extensão real de protocolo
(o gateway perguntar ao executor conectado, em tempo real, "você conhece
esse projeto?"), não uma opção de configuração.

Lição: quando um pedido de "acesso automático a X" atravessa mais de um
processo/host com seu próprio ponto de decisão, resolver o ponto mais fácil
de mexer (geralmente o mais próximo, aqui o executor local) e parar aí dá a
impressão de entrega completa sem entregar o resultado fim-a-fim pedido.
Vale a pena traçar o caminho completo da requisição — aqui, ChatGPT → MCP →
gateway → executor — e nomear explicitamente qual trecho ficou resolvido e
qual não, antes de declarar a etapa fechada (feito em
`docs/threat-model.md` e no handoff desta entrega).

## 2026-08-31 — hard stop de sessão impede começar a importação tardia

Quando a janela operacional já passou do hard stop, a resposta correta não é
"só baixar mais um artefato": é registrar que o trabalho ficou pendente e
deixar a próxima execução começar limpa. Isso evita importar conteúdo
metade-feito e depois ter de descobrir qual parte foi realmente validada.

## 2026-09-01 — uma pagina cujo conceito depende de uma fonte precisa embuti-la

A landing page em `docs/landing/index.html` e um caderno manuscrito: a fonte
de caneta (Shantell Sans) *e* o conceito, nao um enfeite. Renderizando a
pagina antes de entregar, apareceu o modo de falha: quando o Google Fonts nao
responde, o navegador cai para Times e a pagina inteira deixa de ser um
caderno — vira um documento comum, sem qualquer erro visivel para quem
publicou. O corpo (IBM Plex) tolera isso; a caneta nao.

Licao: separar as fontes por papel antes de escolher como carrega-las. Fonte
decorativa cuja ausencia degrada a leitura pode ficar em CDN com fallback de
sistema. Fonte que *carrega o conceito* da pagina vai embutida em base64, ou
a entrega depende de um terceiro estar de pe no momento em que a pessoa que
importa abre o arquivo. Vale tambem o habito que revelou o problema: abrir a
pagina de verdade, com a rede indisponivel, antes de chamar de pronta.

## 2026-09-01 — a coluna velha não sai na mesma migration que cria a substituta

O plano da #73 mandava remover `projects.path` ao criar `workspace_bindings`,
que é o substituto correto (o caminho passa a ser do par projeto↔nó, não do
projeto). Escrevendo a `0009_control_plane.sql` apareceu o que o plano não
tinha: o backfill de `projects.path` → `workspace_bindings.path` só cobre
projetos que estão no `registry.json` de hoje. Para qualquer projeto ausente
dele, a coluna é a **única cópia** do caminho, e reconstruí-la depende de ler
`executors.metadata_json` — JSON, não exprimível em SQL portável entre SQLite
e PostgreSQL. Remover junto teria sido uma perda silenciosa e irreversível,
visível só quando alguém procurasse um projeto antigo.

Lição: numa migration que troca uma representação por outra, a remoção da
representação antiga só é segura quando o backfill é **total** — não "cobre os
casos que a gente conhece". Se a cobertura depende de uma fonte que a migration
não consegue ler, a coluna fica, com o motivo escrito dentro do arquivo, e a
remoção vira uma migration posterior com o backfill feito em código. Vale também
a ordem das instruções: como o SQLite não faz rollback de DDL, o `alter table`
que detecta banco errado vem primeiro — falhar ali deixa o schema intacto em vez
de meio-criado.

## 2026-09-01 — worktree criado pelo kit nasce com a suíte quebrada (awt × extra="forbid")

O `awt` (kit AI-Agents) escreve um `.env` no worktree novo com as portas que
alocou. Os `Settings` do CodexBridge usam `extra="forbid"`, então esse `.env`
faz o processo recusar a subir: o worktree nasce com a suíte inteira vermelha,
e o sintoma (erro de validação de settings) não aponta para o kit. Contornado
renomeando para `.env.awt-generated`. O `awt` também instala o extra `[dev]`,
que este projeto não declara — ele declara `[test]`.

Lição: ferramenta genérica de setup de worktree e projeto com configuração
estrita colidem por construção. Ao usar `awt` num projeto novo, rodar a suíte
**antes** de escrever qualquer linha de código — o primeiro `pytest` verde é o
que separa "quebrei agora" de "nasceu quebrado". E o conflito é do kit, não do
projeto: vale ticket lá, não `extra="ignore"` aqui.

## 2026-09-01 — a correção de confiança vive antes do despacho, não dentro de um branch

A #16 já tinha corrigido, no `task.ack`, a confiança no `executor_id` que vem
**dentro** do envelope em vez do autenticado no handshake. A correção ficou
dentro daquele branch do `if/elif`. Todo tipo de mensagem acrescentado depois —
`hello` da Stage 2 inclusive — herdou a confiança de novo, e a revisão
adversarial reproduziu o exploit: um nó autenticado anunciando-se **como
outro**, forjando capacidades alheias e renovando a liveness de um nó morto.

Lição: quando a correção é "não confie neste campo", ela pertence ao ponto onde
a mensagem entra, uma vez, antes do despacho — não ao branch onde o problema foi
notado. Uma guarda por branch é uma guarda que o próximo branch não tem, e o
próximo branch é escrito por quem não leu a issue que motivou a primeira. Vale o
teste de leitura: *se eu acrescentar um tipo de mensagem amanhã, ele nasce
seguro?* Se a resposta depender de alguém lembrar, a guarda está no lugar
errado.

Corolário sobre descartar vs. redirecionar: reescrever o id reivindicado para o
autenticado "conserta" o sintoma e aceita, em silêncio, como declaração do
remetente, uma mensagem que ele não fez sobre si. Descartar é a única leitura
honesta — e descartar sem derrubar a conexão, porque derrubar transformaria
agente com bug em interrupção.

## 2026-09-01 — teste negativo que passa porque nada rodou

Os primeiros testes de identidade no websocket passaram de cara. Passavam porque
o handshake morria antes do laço de recepção: o `AgentHub` foi construído no
import com a `SessionLocal` de produção e guarda a própria referência, então
trocar `main.SessionLocal` não alcançava o `hub.register`, que estourava
`unknown_executor`. A asserção "a linha da vítima não mudou" é verdadeira também
quando **nenhuma** mensagem foi processada.

Lição: todo teste negativo precisa de um controle positivo no mesmo arquivo —
uma asserção que só passa se o caminho realmente executou. Aqui foi o teste do
caminho honesto (`o nó anuncia a si mesmo e é gravado`) mais um `assert
socket.accepted` no helper. Sem ele, cinco testes verdes provavam apenas que o
código estava inalcançável.

Segundo achado do mesmo episódio: `TestClient.websocket_connect` roda a app em
outra thread e outro event loop; compartilhar um engine aiosqlite em memória
entre os dois trava. Chamar `agent_ws` direto com um socket falso, no loop do
próprio teste, é determinístico e ainda torna a espera desnecessária — quando o
`await` volta, o laço acabou.

## 2026-09-01 — dois subagentes num worktree só, e `git stash` como estado compartilhado

Dois agentes implementaram metades da Stage 2 em paralelo **no mesmo worktree**,
com listas de arquivos disjuntas — o que pareceu suficiente e não era. Um deles,
para provar que seus testes falhavam contra o código original, rodou `git
stash`: um comando de escopo *repositório*, não de escopo *arquivo*. Reverteu
edições não-commitadas do outro agente e do próprio operador, e o `stash pop`
deu conflito num arquivo já reescrito nesse meio-tempo. A recuperação foi
manual, e o único motivo de nada ter se perdido é que o snapshot do stash ainda
existia.

Lição: paralelizar por arquivo só é seguro se as ferramentas também forem por
arquivo. `git stash`, `git checkout .`, `git restore`, `git clean` agem no
repositório inteiro e não têm como respeitar uma divisão de escopo que existe só
no prompt. Ou se dá um worktree por agente, ou se proíbe explicitamente esses
comandos no prompt e se verifica mutação copiando o arquivo (`cp` e restaura),
que foi como a prova acabou sendo feita aqui.

## 2026-09-02 — uma coluna dimensionada para um propósito, reaproveitada para outro, sem revisitar a largura

`discovered_resources.resource_key` nasceu em `0009_control_plane.sql` como
`varchar(255)`, pensada como um id curto sugerido. A PR seguinte (Stage 3,
relatório) reaproveitou a mesma coluna para guardar o path absoluto do
candidato — até 2048 caracteres, o próprio limite que o protocolo já
declarava em `DiscoveredCandidate.resource_key`. Ninguém voltou a olhar a
largura da coluna quando o significado do campo mudou. O SQLite não acusou
nada: é afinidade de tipo, não restrição, então qualquer string cabe. O
projeto declara `aiomysql` como dependência — MySQL é alvo suportado — e lá
a mesma escrita seria `Data too long for column`, sem que nenhum teste local
(rodado só contra SQLite) jamais visse isso.

Lição: quando o *significado* de uma coluna muda — de "id curto sugerido"
para "path de filesystem" — a largura declarada é parte do contrato que
mudou junto, não um detalhe que sobrevive por acidente. Perguntar "isso
ainda cabe no que declarei?" é parte de mudar o significado, não um passo
opcional depois. E testar só contra o motor mais permissivo (aqui, SQLite)
esconde exatamente esse tipo de defeito: a suíte fica verde enquanto o
contrato declarado (múltiplos motores de banco suportados) já está quebrado
para um deles. Quem generaliza o uso de uma coluna existente deve verificar
a largura contra TODOS os motores declarados como alvo, não só contra o que
os testes locais usam.

O conserto (`migrations/0013_discovery_resource_key_hash.sql`) não alargou a
coluna — alargar teria estourado o limite de chave do índice único composto
que essa mesma coluna ancora, trocando uma falha silenciosa por outra no
mesmo alvo. A saída foi separar "chave de busca" (hash de largura fixa) de
"dado real" (path, em coluna nova, sem índice) — quando um valor precisa
simultaneamente indexar barato E carregar um dado de tamanho não controlado,
essas são duas responsabilidades, não uma.

## 2026-09-02 — um segundo portão de privilégio que reusa `is_admin()` pode ser tautológico

Stage 4 do #73 (WK-20260902-gh73-authorization-plane) pediu, por escrito, o
mesmo formato do segundo portão que `DECISIONS_DECIDE` já tinha:
`principal.can_approve_sensitive or principal.is_admin()`, aplicado depois de
o escopo administrativo base já ter sido exigido. Copiado ao pé da letra para
`NODES_AUTHORIZATIONS_MANAGE`, o portão não fazia nada: `is_admin()` é
`"admin" in principal.roles or "codexbridge.admin" in principal.scopes`, e o
escopo BASE da própria ação já É `codexbridge.admin`. Para qualquer ação cujo
escopo seja exatamente esse, `principal.has_scope(action.scope)` e
`principal.is_admin()` são o mesmo predicado — todo principal que passa pelo
portão de entrada já teria passado pelo segundo, tornando `can_approve_
sensitive` irrelevante e a condição inteira tautológica. Em `DECISIONS_DECIDE`
o mesmo código funciona porque o escopo dessa ação (`codexbridge.task.
approve`) é disjunto de `codexbridge.admin` — os dois predicados genuinamente
diferem ali.

A confirmação foi de duas linhas, antes de escrever qualquer teste:
`AuthenticatedPrincipal(roles=[], scopes=['codexbridge.admin'],
can_approve_sensitive=False).is_admin()` devolve `True`. Se a suíte tivesse
só testado "com escopo admin, sem `can_approve_sensitive`, permitido" (o
caminho que qualquer teste ingênuo escreveria primeiro), teria passado sem
provar nada sobre o portão — de novo o padrão do achado de 2026-08-24 e do
`test_agent_ws_discovery.py`: teste verde provando só que o caminho executou,
não que ele decide certo.

Lição: antes de reusar um predicado de "é admin" como segunda camada de um
gate cujo PRIMEIRO portão já é o próprio escopo administrativo, verificar por
código — não por analogia com outro gate — se as duas checagens realmente
divergem para algum principal alcançável. Quando a segunda checagem é
logicamente implicada pela primeira, ela não é defesa em profundidade: é
decoração. O ajuste aqui foi checar o papel diretamente
(`"admin" in principal.roles`), não `is_admin()`, e documentar POR QUE no
próprio docstring de `permissions.is_allowed` — quem copiar o padrão
`DECISIONS_DECIDE` de novo, para uma ação cujo escopo base não seja
administrativo, deve voltar a usar `is_admin()`; quem copiar para uma ação
cujo escopo base JÁ seja `codexbridge.admin` deve repetir esta checagem
antes de confiar no copy-paste.

## 2026-09-02 — um plano de UI pode descrever um endpoint que nunca foi construído

O plano da PR C5 (WK-20260902-gh73-control-ui, issue #73 Stage 5) descrevia a
quarta tela — `GET /control/invite` — chamando `POST /api/v1/nodes/invite` e
montando um comando `scripts/enroll_node.py` pronto para copiar. Nenhum dos
dois existe: `gateway/app/api/routes/nodes.py` só serve `GET /nodes` e `GET
/nodes/{nodeId}`; `scripts/` não tem `enroll_node.py`; e
`docs/project-onboarding.md` já documentava, antes desta PR, que registrar um
nó é um procedimento manual de dois arquivos (`registry.json` no gateway,
allowlist local no executor) com reinício dos dois processos — nunca um
fluxo HTTP.

A confirmação foi puramente por busca (`grep -rn "invite"`, `ls scripts/`,
leitura de `docs/project-onboarding.md`), antes de escrever uma linha de UI
para essa tela — não por assumir que "C1-C4 já expõem os mesmos endpoints"
(a frase literal do plano) valia para as quatro telas por igual só porque
valia para as outras três.

Lição: um plano de UI que descreve "a tela chama o endpoint X" é uma
afirmação sobre o código, não uma instrução que dispensa verificação — o
mesmo nível de ceticismo que já se aplica a specs de negócio vale para specs
de interface. Quando a verificação mostra que o endpoint não existe, a
resposta certa não é inventar um (a lógica de negócio de um endpoint de
convite — geração de token, hashing em repouso, trilha de auditoria,
revogação — pertence à sua própria PR, com sua própria revisão de segurança)
nem simplesmente pular a tela (o link ficaria quebrado e a lacuna, muda). A
resposta que preserva confiança é renderizar uma explicação honesta no lugar
exato onde a tela iria — nomeando o endpoint e o script que faltam pelos
nomes exatos que o plano previu — e registrar o achado no relatório da PR
como trabalho pendente para uma PR própria, nunca como algo silenciosamente
resolvido "de outro jeito".
