# 09 - Flujo Senior y Automatización

## Historia feliz: escala sin caos
Lia estandarizó el kit en varios repositorios y creó una rutina de CLI que cualquier agente o programador sigue sin necesidad de pensar.

## Enfoque senior
- Estándares de gobernanza entre repositorios
- Gates de calidad automatizados con GovernanceKit CLI
- Cultura de handoff que sobrevive a reinicios de contexto

## El loop diario con CLI

Tres comandos cubren todo el ciclo de sesión:

**`governancekit resume`** — ejecuta al inicio de cada sesión. Imprime el work_id activo, branch, estado y el próximo paso exacto del RESUME.md. Tanto agentes como programadores lo ejecutan antes de tocar el código.

**`governancekit doctor`** — ejecuta antes de programar. Valida el scaffold: archivos requeridos, readiness flags, issue activa, próximo paso del resume y rutas de archivos secretos rastreados. Corrige cada `[FAIL]` antes de empezar. Las líneas `[HINT]` (como mapa de código desactualizado) son avisos — atiéndelas cuando sea conveniente.

**`governancekit map`** — ejecuta tras cambios significativos y haz commit del resultado. Regenera `docs/codemap.md`, el índice de código persistente que los agentes leen al inicio de la sesión en lugar de escanear archivos.

```bash
# Inicio de sesión
governancekit resume

# Antes de tocar el código
governancekit doctor

# Después de un lote de cambios
governancekit map
git add docs/codemap.md
git commit -m "refresh codemap"
```

## Integración con CI

Agrega `doctor` al pipeline para validación legible por máquina:

```bash
governancekit doctor --json | jq '.ok'
```

El exit code es 1 si alguna verificación no-advisory falla — úsalo como gate de merge.

## Escalar a un equipo

- Exige que `governancekit doctor` pase en CI antes de cualquier merge.
- Commitea `docs/codemap.md` junto con el código — trátalo como artefacto de primera clase, no como archivo generado a ignorar.
- Usa `resume` en el prompt de arranque: *"Ejecuta `governancekit resume` y usa la salida para orientarte antes de planificar."*
- Revisa `docs/napkin-lessons.md` en las retrospectivas del equipo — captura decisiones no evidentes.
- Un `docs/limits.md` por repositorio, revisado trimestralmente por el tech lead.

## Prompt sugerido para sesiones senior
"Ejecuta `governancekit resume`. Luego lee AGENTS.md, software-overview.md y limits.md. Reporta lo que encuentres y propón un plan enfocado antes de escribir cualquier código."

## Resultado
Los agentes llegan con contexto. Los programadores no pierden tiempo re-explicando el proyecto. El scaffold impone disciplina sin esfuerzo adicional de nadie.
