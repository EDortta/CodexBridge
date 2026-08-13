# 10 - Antipadrões e Recuperação

## História feliz: recuperando sem culpas
Lia herdou uma etapa bagunçada: sem `work_id`, sem handoff e sem evidência de testes. Em vez de desistir, ela aplicou um protocolo de recuperação.

## Antipadrões comuns
- começar sem contexto/limites prontos
- pedir mudança grande e vaga
- fechar sessão sem handoff
- lições genéricas sem ação

## Protocolo de recuperação
1. Reconstruir estado atual no `handoff.md`.
2. Definir/normalizar `work_id` e atualizar docs.
3. Revalidar limites e escopo.
4. Rodar checks mínimos e registrar.
5. Capturar lições napkin acionáveis.

## Resultado esperado
Sessão volta a ser controlável e o time retoma com segurança.
