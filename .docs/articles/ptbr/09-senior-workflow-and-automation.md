# 09 - Fluxo Sênior e Automação

## História feliz: escala sem caos
Lia virou referência no time. Ela padronizou o kit em vários repositórios e criou uma rotina de CLI que qualquer agente ou programador segue sem precisar pensar.

## O que muda no nível sênior
- Padronização de governança entre repositórios
- Gates de qualidade automatizados com GovernanceKit CLI
- Cultura de handoff que sobrevive a reinícios de contexto

## O loop diário com CLI

Três comandos cobrem todo o ciclo de sessão:

**`governancekit resume`** — rode no início de cada sessão. Imprime o work_id ativo, branch, status e o próximo passo exato do RESUME.md. Tanto agentes quanto programadores rodam isso antes de tocar no código.

**`governancekit doctor`** — rode antes de codar. Valida o scaffold: arquivos obrigatórios, readiness flags, issue ativa, próximo passo do resume e caminhos de arquivos secretos rastreados. Corrija cada `[FAIL]` antes de começar. Linhas `[HINT]` (como mapa de código desatualizado) são avisos — trate quando conveniente.

**`governancekit map`** — rode após mudanças significativas e faça commit do resultado. Regera `docs/codemap.md`, o índice de código persistente que os agentes leem no início da sessão em vez de escanear arquivos.

```bash
# Início da sessão
governancekit resume

# Antes de tocar no código
governancekit doctor

# Depois de um lote de mudanças
governancekit map
git add docs/codemap.md
git commit -m "refresh codemap"
```

## Integração com CI

Adicione `doctor` ao pipeline para validação legível por máquina:

```bash
governancekit doctor --json | jq '.ok'
```

O exit code é 1 se qualquer verificação não-advisory falhar — use como gate de merge.

## Escalando para um time

- Exija que `governancekit doctor` passe no CI antes de qualquer merge.
- Commite `docs/codemap.md` junto com o código — trate como artefato de primeira classe, não como arquivo gerado para ignorar.
- Use `resume` no prompt de partida: *"Rode `governancekit resume` e use a saída para se orientar antes de planejar."*
- Revise `docs/napkin-lessons.md` em retrospectivas de time — captura decisões não-óbvias.
- Um `docs/limits.md` por repositório, revisado trimestralmente pelo tech lead.

## Prompt sugerido para sessões sênior
"Rode `governancekit resume`. Depois leia AGENTS.md, software-overview.md e limits.md. Reporte o que encontrar e proponha um plano focado antes de escrever qualquer código."

## Resultado
Agentes chegam com contexto. Programadores não perdem tempo re-explicando o projeto. O scaffold impõe disciplina sem esforço extra de ninguém.
