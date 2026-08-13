# 13 - Fluxo Offline de Issues (Modo Local)

## História feliz: sem internet, sem bloqueio
Lia ficou sem acesso externo. Mesmo assim, ela continuou avançando usando o fluxo local de issues com qualidade e rastreabilidade.

## O que é seu (programador)
- Organizar épicos/tarefas em `docs/issues/`.
- Atualizar status por renomeação e evidência.
- Preparar sincronização futura (quando voltar online).

## O que é do agente
- Estruturar e manter templates locais consistentes.
- Gerar handoff claro para retomada.
- Sugerir pacote de sincronização (o que subir depois).

## Passo a passo offline
1. Criar/atualizar issue local em `docs/issues/...`.
2. Preencher `work_id`, data e plano de testes.
3. Executar implementação por etapas curtas.
4. Rodar session-close (`handoff.md` + `napkin-lessons`).
5. Registrar itens pendentes de sincronização externa.

## Quando voltar online
- Criar issues Jira/GitHub a partir dos docs locais.
- Preservar o mesmo `work_id` para manter rastreio.
- Atualizar links finais nos docs e handoff.
