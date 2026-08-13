# 12 - Fluxo Online de Issues (Jira + GitHub)

## História feliz: rastreabilidade completa
Quando o projeto exige rastreio corporativo, Lia usa Jira + GitHub conectados. Cada tarefa fica auditável do planejamento ao commit.

## O que é seu (programador)
- Confirmar repositório/projeto de destino.
- Definir modo de trabalho (público online).
- Revisar e aprovar o conteúdo antes de criar issue.

## O que é do agente
- Montar body completo da issue (sem campos vazios).
- Criar e linkar Jira + GitHub quando solicitado.
- Respeitar regras de conteúdo mínimo do `AGENTS.md`.

## Passo a passo
1. Confirmar alvo (Jira project + GitHub repo).
2. Gerar docs locais da issue em `docs/issues/`.
3. Criar issue no Jira.
4. Criar issue no GitHub.
5. Cruzar links Jira ↔ GitHub.
6. Propagar `work_id` para docs, handoff e commits.

## Dica operacional
Se existir `jkctl.py` no repositório alvo, prefira ele para fluxo de issue/PR.
