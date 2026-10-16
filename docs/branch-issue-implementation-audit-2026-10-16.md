# Branches `feature/gh-*`: vínculo com issues e grau de implementação

- **Data:** 2026-10-16
- **Work ID:** `WK-20261016-gh-issue-implementation-audit`
- **Base inspecionada:** `development` em `44d5f34` (`origin/development`)
- **Escopo:** branches `feature/gh-5`, `gh-6`, `gh-7`, `gh-8` e `gh-73`; código, documentação e testes existentes. Nenhum teste foi executado.

## Conclusão executiva

Sim. O número no nome das branches corresponde à issue GitHub: `gh-5` a #5, `gh-6` a #6, `gh-7` a #7, `gh-8` a #8 e `gh-73` ao épico #73. As quatro APIs de #5–#8 já estão integradas em `development`; as branches locais correspondentes não são necessárias para trazer essas implementações. Seus tips de #5–#8 terminam em commits `wip(...): parked, failed`; o tip de #73 é patch-equivalente a um commit de `development` (`git cherry -v`).

As issues #5–#8 continuam **abertas** no GitHub apesar dos commits de implementação e de integração registrados na atividade. A seção “Development” das páginas também diz “No branches or pull requests”. Portanto o estado GitHub está desatualizado em relação ao código; não significa que as APIs estejam ausentes. Não alterei issues nem branches remotas.

## Comparação por issue

| Branch / issue | Estado em `development` | O que está implementado | Lacunas relevantes frente ao escopo original |
|---|---|---|---|
| `feature/gh-5/...` / [#5](https://github.com/EDortta/CodexBridge/issues/5) | **Parcial, funcional no núcleo.** `projects.py` expõe listagem, detalhe e summary; implementação inicial em `e3d7d5c`, evolução posterior em `816a660`. | Paginação, filtros, atenção, health baseado em heartbeat recente, timestamps, contagens de decisões pendentes/missões ativas/sessões e autorização por projeto. O path do servidor não é exposto. `tests/integration/test_projects.py` contém 29 testes. | A issue pede contagens/sumários de issues e artifacts; os modelos ainda não existem e esses campos são omitidos. Branch local também guarda commits prévios explicitamente estacionados/falhos. |
| `feature/gh-6/...` / [#6](https://github.com/EDortta/CodexBridge/issues/6) | **Essencialmente completo no escopo descrito**, pela inspeção estática; não validado por execução nesta sessão. `decisions.py` foi integrado em `8113ec2` e recebeu mudanças subsequentes. | GET lista/detalhe e POST approve/reject/request-revision; filtros, escopo/autorização, `If-Match`/ETag, idempotência, justificativa de rejeição, `confirm: true` para aprovar decisão crítica, conflito para estado resolvido/obsoleto e auditoria do ator. `tests/integration/test_decisions.py` contém 47 testes. | Não identifiquei lacuna material nos critérios de aceite originais. O issue permanece aberto no GitHub, então a conclusão de fechamento/aceite ainda precisa ser registrada por quem mantém o backlog. |
| `feature/gh-7/...` / [#7](https://github.com/EDortta/CodexBridge/issues/7) | **Parcial, bastante implementado.** API original integrada em `37f23ba`; o domínio recebeu evolução posterior, incluindo `#43`, `#68` e `#69`. | Listagem, detalhe, timeline, cancelamento, explain; missão durável com tentativas e eventos, bloqueio/razões, validação de estado, autenticação e trilha de auditoria. Há também criação e delivery por incrementos posteriores. `tests/integration/test_missions.py` contém 72 testes. | `dependencies` e `relatedEntities` não estão implementados. Não há controles Mission-level `pause`/`resume`; o README documenta essa decisão e distingue comandos de sessão. A issue lista pause/resume nos endpoints propostos, embora seus critérios de aceite enfatizem transições válidas sem exigir esses dois comandos nominalmente. |
| `feature/gh-8/...` / [#8](https://github.com/EDortta/CodexBridge/issues/8) | **Parcial, API central implementada.** Integrada em `0660b17`, com evolução posterior para atualizar épicos/issues e mover issue entre épicos (`983adfa`). | DTOs provider-neutral, listagem/detalhe/criação/atualização, paginação/filtros, relação epic–issue, autorização e histórico do ator. Os dados são locais; há uma fronteira para provider, mas não sincronização GitHub. `tests/integration/test_epics_issues.py` contém 43 testes. | “Planning-review metadata and related missions, conversations and decisions” está explicitamente ausente no README da API. Não existe sincronização de tracker; o provider atual é `local`. |

Os números de testes acima contam funções `test_*` encontradas nos arquivos; **não são resultados de execução**.

## Épico #73 — `feature/gh-73/control-plane-domain`

A branch tip `13583f8` está patch-equivalente a `development`, segundo `git cherry -v`; não há um delta exclusivo a integrar. O épico [#73](https://github.com/EDortta/CodexBridge/issues/73) permanece aberto e seu Definition of Done é mais amplo que o domínio de dados.

O código/documentação mostram progresso substancial em domínio/contratos, visibilidade de nós, descoberta/adoção e autorização (Stages 1–4). Há um primeiro corte de Control UI (Stage 5), mas o código contém três rotas de página (`/control`, `/control/nodes/{node_id}` e `/control/invite`); ainda não entrega a experiência completa de Projects nem a convergência de Missions, Decisions e Audit descrita para Stage 6. Stage 7, distribuição e endurecimento, também não está demonstrada como concluída. O épico não está completo.

Correção de documentação: o `RESUME.md` de 2026-09-02 dizia que `/control/invite` não funcionava. O código atual em `gateway/app/api/routes/control_ui.py` renderiza um formulário e chama `POST /api/v1/nodes/invite`; portanto aquela advertência ficou obsoleta. Isto confirma a existência do fluxo no código, não valida uma inscrição real de node ou a implantação na borda.

## Evidências locais principais

- `docs/api/README.md` §§ Projects, Decisions, Missions e Epics and Issues documentam capacidades e lacunas.
- Rotas: `gateway/app/api/routes/projects.py`, `decisions.py`, `missions.py`, `epics.py`, `issues.py` e `control_ui.py`.
- Cobertura existente: `tests/integration/test_projects.py`, `test_decisions.py`, `test_missions.py`, `test_epics_issues.py` e `test_control_ui.py`.
- Verificação Git: tips das branches #5–#8 e `git cherry -v development feature/gh-73/control-plane-domain`.
- Estado GitHub consultado em 2026-10-16 nos links de cada linha acima; as quatro issues-filhas estão abertas e o épico #73 também.

## Recomendação de saneamento do backlog

1. Confirmar aceitação e fechar #6; pelo escopo registrado, é a candidata mais forte a conclusão.
2. Decidir se as lacunas de #5, #7 e #8 são necessárias agora ou devem virar follow-up explícito. Se a intenção original continuar valendo integralmente, não fechar essas issues ainda.
3. Atualizar estado/relacionamentos no GitHub para refletir o código já integrado e remover referências de branch obsoletas quando o mantenedor revisar.
4. Tratar #73 como épico ativo; escolher e especificar o próximo recorte (Projects/Stage 5 ou convergência operacional/Stage 6) após decidir a sequência.

Nenhum teste, merge, alteração no GitHub, deploy ou limpeza de branch foi feito nesta auditoria.
