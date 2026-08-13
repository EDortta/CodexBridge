# Delphi Audit Workflow

Activation: on-demand only. Do not run as part of routine PR review.
Trigger: human requests a Delphi quality audit for a project.

## Prerequisites

- Project uses Delphi 11/12 (`.pas`/`.dpr`/`.dpk` files present).
- `docs/software-overview.md` and `docs/limits.md` are ready.
- Human has explicitly requested this audit.

## Scope

Whole-codebase analysis. Not scoped to a diff or branch.
Report findings; do not apply fixes unless the human explicitly authorizes.

---

## Audit Checklist

### 1. Tipos Primitivos vs Tipos Fortes (TypeDef)

- Find raw `Integer`, `String`, `Cardinal`, `Int64` used for domain identifiers, status codes, and enums.
- A domain ID typed as `Integer` is interchangeable with any other `Integer` — the compiler cannot prevent accidental mix-ups.
- For each: which domain concept is represented, is a `type TUserId = type Integer;` or similar strong typedef feasible?
- Classify: raw primitive used as a parameter that could be confused with another same-typed parameter in the same call → IMPROVEMENT; mixing two domain IDs in a single expression → BLOCKER candidate.

### 2. Interfaces — Uso Correto vs Herança Múltipla de Classes

- Find service, repository, and adapter classes declared without a corresponding interface (`IMyService`).
- Classes without interfaces cannot be substituted in tests without modifying callers.
- Find cases of deep class inheritance hierarchies (3+ levels) where interfaces and composition would simplify the design.
- Flag: concrete class used as type in `constructor` parameters instead of an interface → couples implementation to caller.
- Classify: services/repositories without interfaces in business-logic layer → IMPROVEMENT.

### 3. Gerenciamento de Memória — `Free` vs Reference Counting

- Find objects created with `TObject` descendants where `Free` is called but no `try..finally` wraps the `Create`→`Free` pair.
- Find `TInterfacedObject` descendants — these use reference counting; manual `Free` is incorrect and may double-free.
- Find `FreeAndNil` used on interface-typed variables — usually a sign of mixing ownership models.
- Classify: `TObject` created without `try..finally..Free` pattern → BLOCKER; interface variable manually freed → BLOCKER.

### 4. `try..finally` Ausente para Recursos

The most critical category for memory and handle safety.

- Find every `TObject.Create`, file handle (`TFileStream`, `TMemoryStream`, `AssignFile`), database connection, or lock acquisition without a `try..finally` block ensuring cleanup.
- Pattern to look for: `Obj := TFoo.Create;` followed by `Obj.Free` without an intervening `try..finally`.
- For each: what resource is at risk, what exception would leak it, suggested fix.
- Classify: any acquired resource without finally-guarded release → BLOCKER.

### 5. Generics — Restrições de Tipo (`T: IInterface`, `T: TMyBase`)

- Find generic class and method declarations with bare `<T>` and no type constraint.
- Without constraints, the compiler cannot verify that `T` supports the operations called on it — errors surface only at instantiation sites, not at the generic definition.
- For each: what properties/methods does the generic body access on `T`? What interface or base class should constrain it?
- Example:
  ```delphi
  // before — T unconstrained
  procedure Process<T>(Item: T);

  // after — T must implement IDisposable
  procedure Process<T: IDisposable>(Item: T);
  ```
- Classify: generic accessing member on `T` without a constraint guaranteeing that member → BLOCKER candidate.

### 6. RTTI — Uso Controlado

- Find `GetTypeInfo`, `TRttiContext`, `TRttiType`, `IsClass`, `ClassType`, and `TObject.ClassName` usage outside of serialization/persistence layers.
- RTTI bypasses compile-time type checking; excessive use in business logic is a design smell.
- Find `as` type-cast without a preceding `is` check or equivalent RTTI guard.
- Classify: bare `as` cast on a value received from external input or polymorphic container without guard → BLOCKER candidate.

### 7. Visibilidade de Métodos (published Desnecessário)

- Find `published` methods that are not bound to form designer events or RTTI-exposed properties.
- `published` widens visibility to RTTI reflection — unintended exposure of implementation details.
- Find `public` methods that are only called within the same unit — candidates for `private` or `protected`.
- Find `private` methods in a base class where `strict private` would prevent accidental access from descendant classes.

### 8. Dependências Circulares Entre Units

- Map `uses` clauses across units and identify cycles (`UnitA uses UnitB`, `UnitB uses UnitA`).
- Circular dependencies in the `interface` section cause compilation order problems and tightly couple unrelated modules.
- Flag cycles: distinguish `interface` section cycles (bad) from `implementation` section cycles (acceptable but worth noting).
- Suggest: extract a shared type unit (`Types.pas`, `Interfaces.pas`) to break cycles without changing logic.

### 9. Código Platform-Específico Sem `{$IFDEF}` Adequado

- Find Windows API calls (`WinAPI.Windows`, `ShellAPI`, registry, `HWND`) outside of `{$IFDEF MSWINDOWS}` blocks.
- Find FMX/VCL cross-platform code where platform-specific behavior is assumed but not guarded.
- Find hardcoded path separators (`\` vs `/`) and line endings without `PathDelim` / `sLineBreak` constants.
- Classify: Windows API called unconditionally in a cross-platform (`{$IFDEF IOS}` or `{$IFDEF ANDROID}`) codebase → BLOCKER.

### 10. Exception Handling — `EAbstractError`, Bare `except`

- Find bare `except` clauses with no exception type:
  ```delphi
  try
    DoSomething;
  except
    // swallowed
  end;
  ```
  These catch and discard every exception including `EOutOfMemory`, `EAccessViolation`, and `EAbstractError`.
- Find `except on E: Exception do` that log but do not re-raise in contexts where the caller expects propagation.
- Find `raise` without an exception object (bare re-raise outside of an `except` block is a compile error in some Delphi versions — flag as risk).
- Classify: bare `except` in production code → BLOCKER; swallowed exceptions without logging → BLOCKER.

### 11. Dados Externos Sem Validação

- Find REST API responses (`TRESTResponse`, `TJSONObject`, `TJSONValue`) accessed via field names without nil-checks or shape validation.
- Find database query results (`TDataSet`, `TFDQuery`) where `.FieldByName` is called without verifying the field exists.
- Find `StrToInt`, `StrToFloat`, `StrToDateTime` on user input without `TryStrToInt` / `TryStrToFloat` equivalents.
- Classify: external JSON/DB data accessed without validation before assignment to domain types → BLOCKER candidate.

### 12. Constants e Resourcestrings — Uso Correto

- Find string literals duplicated across multiple units that represent user-facing messages, error codes, or configuration keys.
- `resourcestring` enables localization at runtime; `const` does not — flag user-visible strings declared as `const`.
- Find magic numbers used in business logic without a named `const` declaration.
- Find `resourcestring` blocks in implementation units instead of a centralized strings unit — localization tooling typically expects a flat structure.

### 13. Propriedades — Getter/Setter Desnecessário

- Find properties with a getter/setter that only reads/writes the backing field with no logic:
  ```delphi
  property Name: string read FName write FName; // OK — no getter/setter needed
  property Name: string read GetName write SetName; // flag if GetName/SetName just access FName
  ```
- Trivial getters/setters add code noise without value; use direct field access syntax in the property declaration.
- Conversely, find public fields that should be properties (no encapsulation, cannot add validation later).

### 14. Event Handlers — Acoplamento Excessivo

- Find `TNotifyEvent` / custom event handlers that access form fields or global state directly instead of receiving data as parameters.
- Event handlers embedded in forms that contain business logic → violates separation of concerns.
- Find anonymous methods (`TProc`, `TFunc`) capturing `Self` or local variables across async operations — risk of use-after-free if the owner is destroyed before the callback fires.
- Classify: business logic inside form event handlers → IMPROVEMENT; captured `Self` in async callback without lifetime guard → BLOCKER candidate.

### 15. Thread Safety — `TMonitor`, `TCriticalSection`, `TInterlocked`

- Find shared mutable state (class fields, global variables) accessed from worker threads or `TThread` descendants without synchronization.
- Find `TThread.Synchronize` / `TThread.Queue` calls used to access UI from background threads — verify all UI access goes through these.
- Find `TCriticalSection` created but `Enter`/`Leave` not wrapped in `try..finally`.
- Find `TInterlocked.Increment`/`Decrement` opportunities where raw `Inc`/`Dec` on shared counters are used.
- Classify: shared mutable field accessed from multiple threads without lock → BLOCKER.

### 16. Naming Conventions (Pascal Case, Prefixo T/I/E)

- Verify Delphi naming conventions:
  - Types: `T` prefix (`TCustomer`, `TOrderList`)
  - Interfaces: `I` prefix (`IRepository`, `IService`)
  - Exception classes: `E` prefix (`EValidationError`, `EDatabaseTimeout`)
  - Constants: `c` or `k` prefix, or all-caps (project-dependent — flag inconsistency)
  - Private fields: `F` prefix (`FName`, `FCount`)
- Find deviations from the project's established convention.
- Flag: interface types without `I` prefix cause confusion with class types in polymorphic code.

### 17. Baseline de Ferramentas

Verify these are present and enforced:

| Tool | Purpose |
|---|---|
| FixInsight | Delphi-native static analysis and code inspection |
| Delphi Sonar plugin | SonarQube integration for Delphi metrics |
| TestInsight | Real-time unit test runner inside the IDE |
| DUnit / DUnitX | Test framework — DUnitX preferred for modern Delphi |
| Delphi Code Coverage | Coverage measurement for DUnit/DUnitX test runs |

If any are absent, classify as IMPROVEMENT with estimated setup effort.
Flag: no unit test framework present → BLOCKER for new feature work.

### 18. Manutenibilidade, Legibilidade e Segurança de Tipo

- Estimate effort vs. benefit for each category above.
- Identify which findings, if fixed, would eliminate the most runtime risk (memory leaks, access violations, silent data corruption).
- Identify which findings are blocking adoption of stricter compiler warnings (`{$WARN SYMBOL_DEPRECATED ON}`, hints as errors).

---

## Required Output Format

### Executive Summary

2–4 sentences: overall Delphi code safety maturity, top risk, and top quick win.

### Findings by Category

For each category (1–18):
- Category name
- Severity: High / Medium / Low
- Occurrences count
- Representative examples (file:line + snippet)
- Recommendation

### Before / After Examples

For each High finding, provide one concrete before/after code snippet.

### Prioritized Recommendations

| Priority | Finding | Effort | Impact |
|---|---|---|---|
| High | ... | ... | ... |
| Medium | ... | ... | ... |
| Low | ... | ... | ... |

### Quick Wins

List up to 5 changes achievable in under 30 minutes each with no functional risk.

### Delphi Maturity Score

Score: X / 10

| Dimension | Score |
|---|---|
| Memory and resource safety (`try..finally`) | /2 |
| Type safety (interfaces, strong typedefs, constrained generics) | /2 |
| No unvalidated external data | /2 |
| Modern patterns (readonly, generics, no bare except) | /2 |
| Tooling baseline (FixInsight, DUnitX, coverage) | /2 |

Scoring guide:
- 8–10: Production-ready, minimal memory/type risk
- 5–7: Functional but fragile; targeted improvements recommended
- 3–4: High resource-leak and silent-failure surface; structured remediation needed
- 0–2: Safety practices largely absent; prioritize try..finally and exception typing immediately

---

## What This Workflow Does NOT Do

- Does not apply fixes automatically.
- Does not create branches or PRs.
- Does not flag findings from unmodified legacy code as BLOCKERs — those are IMPROVEMENT.
- Does not replace per-PR Delphi checks in `reviewer.md`.
