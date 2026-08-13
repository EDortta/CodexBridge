# Cómo Funcionan los Agentes de IA en el Chat de la IDE (Ejemplo con VSCodium)

Los agentes de IA en una IDE son asistentes que pueden leer archivos del proyecto, sugerir código, editar archivos, ejecutar comandos y explicar decisiones por chat.

En herramientas como VSCodium (con extensión de IA), el panel de chat es tu centro de control.
Tú describes el objetivo y el agente ejecuta pasos dentro del proyecto.

## 1. Qué Puede Hacer el Agente

Capacidades típicas:
- leer tu base de código y resumir la arquitectura
- proponer y aplicar cambios
- ejecutar tests y lint
- explicar errores y corregirlos
- crear documentación, plantillas y checklists

El agente funciona mejor cuando defines alcance y restricciones con claridad.

## 2. Cómo Hablar con el Agente (Principiante)

Usa esta estructura simple de prompt:
1. Objetivo: qué quieres construir/arreglar
2. Contexto: archivos/módulos involucrados
3. Restricciones: reglas, límites, estilo
4. Criterio de terminado: cómo validar éxito

Ejemplo:

```text
Objetivo: Agregar endpoint de reset de contraseña.
Contexto: módulo de autenticación backend y servicio de correo.
Restricciones: mantener compatibilidad de API, no cambiar esquema de BD.
Terminado: tests pasan y endpoint documentado.
```

## 3. Flujo Recomendado de Chat

Usa este ciclo corto:
1. Pide al agente inspeccionar y resumir primero.
2. Pide un plan por pasos.
3. Pide implementar un cambio acotado.
4. Pide ejecutar checks/tests.
5. Pide resumen final con archivos cambiados.

Así mantienes control y avanzas rápido.

## 4. Archivos que Debes Referenciar Siempre

En este kit, el programador debe alinearse con:
- `docs/software-overview.md`: qué es el software y por qué existe (archivo obligatorio que el programador debe editar en cada proyecto)
- `docs/limits.md`: límites estrictos (qué se puede/no se puede) (archivo obligatorio que el programador debe editar en cada proyecto)
- `AGENTS.md`: contrato de ejecución y expectativas de calidad/seguridad

Antes de implementar, pide confirmación de lectura de esos archivos.

Ejemplo:

```text
Antes de programar, lee AGENTS.md, docs/software-overview.md y docs/limits.md.
Confirma restricciones y propone un plan.
```

## 5. Cómo Evitar Errores Comunes

- No uses prompts amplios tipo "refactoriza todo".
- No omitas restricciones (seguridad, privacidad, alcance).
- No aceptes cambios sin evidencia de tests/checks.
- No aceptes supuestos ocultos; pide que se declaren.

## 6. Privacidad y Seguridad para Principiantes

Si la funcionalidad toca datos personales, pide explícitamente:
- impacto de privacidad (estilo GDPR/LGPD)
- comportamiento de retención/eliminación
- seguridad de logs (sin filtraciones sensibles)

Quién debe usar estos archivos:
- Programador: usarlos como checklist e incluir estos requisitos en el prompt del chat.
- Agente de IA: seguir estos archivos durante implementación y revisión.

Archivos de referencia:
- `.docs/agents/privacy-compliance.md`
- `.docs/agents/security.md`

## 7. Prompts Prácticos

- "Analiza este bug y muestra la causa raíz antes de editar código."
- "Propón 2 soluciones con trade-offs e implementa la más segura."
- "Aplica el fix mínimo y corre solo los tests impactados."
- "Lista archivos cambiados y por qué cada uno fue necesario."
- "Si la solicitud supera docs/limits.md, detente y pide aprobación."

## 8. Regla Final

Piensa en el chat de IA como pair programming:
- tú defines intención y límites
- el agente ejecuta con velocidad
- tú apruebas dirección y calidad

Mejores prompts producen mejor código.
