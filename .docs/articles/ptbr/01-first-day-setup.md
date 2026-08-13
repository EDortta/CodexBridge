# 01 - Setup do Primeiro Dia

## História feliz: Lia começou certo
Lia é programadora júnior. Ela quer usar agentes sem perder controle do projeto. No primeiro dia, ela não começa codando. Primeiro, prepara o terreno: contexto, limites e regras. O agente passa a trabalhar a favor dela, não no escuro.

## O que é seu (programador)
- Escrever o contexto real em `docs/software-overview.md`.
- Definir limites reais em `docs/limits.md`.
- Decidir o que pode e o que não pode ser feito.
- Validar se os readiness flags viraram `yes`.

## O que é do agente
- Ler esses arquivos antes de planejar/editar.
- Respeitar limites e avisar quando houver conflito.
- Propor plano coerente com o contexto.

## Passo a passo

**1. Instale o policy pack com o GovernanceKit.**

```bash
pip install git+https://github.com/EDortta/AI-GovernanceKit.git
governancekit --root "$PWD" install-agents
```

Não copie o diretório do kit manualmente: o comando separa arquivos do kit e documentação do projeto.

**2. Configure esta máquina e este checkout.**

```bash
governancekit configure
```

Isso registra a identidade local da máquina separadamente dos valores do operador
usados pelos contratos instalados.

**3. Preencha `docs/software-overview.md`** com o propósito do produto, stack tecnológico e módulos principais.

**4. Preencha `docs/limits.md`** com o que os agentes podem e não podem fazer neste projeto.

**5. Preencha `docs/project-rules.md` e liste cada contrato obrigatório em `docs/required-reading.md`.**

**6. Marque os readiness flags.**

Abra os dois arquivos e defina:
```
project_context_ready: yes
limits_ready: yes
```

**7. Valide o setup.**

```bash
governancekit doctor
```

A maioria das verificações falha numa instalação nova — isso é esperado. Corrija
cada linha `[FAIL]` antes de continuar. Depois de completar contexto, limites e
regras, o doctor deve passar.

**8. Gere o mapa de código.**

```bash
governancekit map
```

Isso cria `docs/codemap.md` — um índice Markdown dos seus arquivos e símbolos. Faça commit. Os agentes leem isso no início da sessão em vez de escanear arquivo por arquivo.

**9. Só então peça implementação ao agente.**

## Prompt sugerido
"Rode `governancekit resume` primeiro, depois leia AGENTS.md, software-overview e limits. Confirme entendimento e proponha um plano curto antes de codar."

## Definição de pronto
- `governancekit doctor` passa em todas as verificações.
- `docs/codemap.md` existe e está commitado.
- O agente sabe o que fazer e o que evitar.
- Você consegue reiniciar qualquer sessão sem perder contexto.
