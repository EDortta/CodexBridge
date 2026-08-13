# 06 - Work ID e Rastreabilidade de Commit

## História feliz: auditoria sem dor
Uma semana depois, Lia precisa explicar por que fez certa mudança. Com `work_id` em docs, handoff e commit, ela encontra tudo em minutos.

## O que é seu (programador)
- Criar `work_id` no formato `WK-YYYYMMDD-<slug>`.
- Reutilizar o mesmo id em toda a etapa.

## O que é do agente
- Lembrar você do `work_id` quando faltar.
- Sugerir mensagem de commit com prefixo correto.

## Onde usar
- docs de épico e tarefa
- `handoff.md`
- mensagem de commit

## Exemplo
- `work_id`: `WK-20260420-login-refresh`
- commit: `[WK-20260420-login-refresh] add refresh token validation`
