# 12 - Flujo Online de Issues (Jira + GitHub)

## Historia feliz: trazabilidad completa
Cuando se requiere trazabilidad corporativa, Lia usa Jira + GitHub conectados. Cada tarea queda trazable desde la planificación hasta el commit.

## Qué es tuyo (programador)
- Confirmar proyecto Jira y repositorio GitHub destino.
- Confirmar modo online/público.
- Revisar y aprobar contenido antes de crear.

## Qué es del agente
- Construir body completo (sin campos vacíos).
- Crear y vincular issues Jira/GitHub cuando se solicite.
- Respetar reglas de contenido de `AGENTS.md`.

## Paso a paso
1. Confirmar destino.
2. Generar docs locales en `docs/issues/`.
3. Crear issue en Jira.
4. Crear issue en GitHub.
5. Vincular Jira ↔ GitHub.
6. Propagar `work_id` a docs, handoff y commits.

## Tip operativo
Si el repo destino tiene `jkctl.py`, priorízalo para operaciones de issue/PR.
