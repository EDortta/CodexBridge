# Como Agentes de IA Funcionam no Chat da IDE (Exemplo com VSCodium)

Agentes de IA em uma IDE são assistentes que conseguem ler arquivos do projeto, sugerir código, editar arquivos, executar comandos e explicar decisões pelo chat.

Em ferramentas como VSCodium (com extensão de IA), o painel de chat é o centro de controle.
Você descreve o objetivo, e o agente executa passos dentro do projeto.

## 1. O Que o Agente Consegue Fazer

Capacidades típicas:
- ler sua base de código e resumir arquitetura
- propor e aplicar mudanças
- executar testes e lint
- explicar erros e corrigi-los
- criar docs, templates e checklists

O agente funciona melhor quando você define escopo e restrições com clareza.

## 2. Como Falar com o Agente (Iniciante)

Use esta estrutura simples de prompt:
1. Objetivo: o que você quer construir/corrigir
2. Contexto: arquivos/módulos envolvidos
3. Restrições: regras, limites, estilo
4. Critério de pronto: como validar sucesso

Exemplo:

```text
Objetivo: Adicionar endpoint de reset de senha.
Contexto: módulo de autenticação backend e serviço de e-mail.
Restrições: manter compatibilidade da API, sem alterar schema de banco.
Pronto: testes passam e endpoint documentado.
```

## 3. Fluxo Bom de Conversa

Use este ciclo curto:
1. Peça para o agente inspecionar e resumir antes.
2. Peça um plano em etapas.
3. Peça implementação de uma mudança por vez.
4. Peça execução de checks/testes.
5. Peça resumo final com arquivos alterados.

Isso mantém você no controle e acelera execução.

## 4. Arquivos que Você Deve Referenciar Sempre

Neste kit, o programador deve sempre alinhar com:
- `docs/software-overview.md`: o que o software é e por que existe (arquivo obrigatório que o programador deve editar em cada projeto)
- `docs/limits.md`: limites rígidos (o que pode/não pode) (arquivo obrigatório que o programador deve editar em cada projeto)
- `AGENTS.md`: contrato de execução e qualidade/segurança

Antes de implementar, peça confirmação de leitura desses arquivos.

Exemplo:

```text
Antes de codar, leia AGENTS.md, docs/software-overview.md e docs/limits.md.
Confirme as restrições e proponha um plano.
```

## 5. Como Evitar Erros Comuns

- Não use prompt amplo tipo "refatore tudo".
- Não omita restrições (segurança, privacidade, escopo).
- Não aceite mudanças sem evidência de testes/checks.
- Não aceite suposições ocultas; peça para explicitar.

## 6. Privacidade e Segurança para Iniciantes

Se a feature mexe com dados pessoais, peça explicitamente:
- impacto de privacidade (estilo GDPR/LGPD)
- comportamento de retenção/remoção
- segurança de logs (sem vazamento sensível)

Quem deve usar esses arquivos:
- Programador: usar como checklist e incluir essas exigências no prompt do chat.
- Agente de IA: seguir esses arquivos durante implementação e revisão.

Arquivos de referência:
- `.docs/agents/privacy-compliance.md`
- `.docs/agents/security.md`

## 7. Prompts Práticos

- "Analise este bug e mostre a causa raiz antes de editar código."
- "Proponha 2 soluções com trade-offs e implemente a mais segura."
- "Aplique a menor correção possível e rode só os testes impactados."
- "Liste os arquivos alterados e por que cada um foi necessário."
- "Se o pedido ultrapassar docs/limits.md, pare e peça aprovação."

## 8. Regra Final

Pense no chat de IA como pair programming:
- você define intenção e limites
- o agente executa com velocidade
- você aprova direção e qualidade

Prompts melhores geram código melhor.
