# PHP Audit Workflow

Activation: on-demand only. Do not run as part of routine PR review.
Trigger: human requests a PHP quality audit for a project.

## Prerequisites

- Project uses PHP 8.x (`.php` files present, `composer.json` optional but expected).
- `docs/software-overview.md` and `docs/limits.md` are ready.
- Human has explicitly requested this audit.

## Scope

Whole-codebase analysis. Not scoped to a diff or branch.
Report findings; do not apply fixes unless the human explicitly authorizes.

---

## Audit Checklist

### 1. `declare(strict_types=1)` Ausente

- Grep for PHP files missing `declare(strict_types=1)` as the first statement after `<?php`.
- Without it, PHP silently coerces types at function call boundaries — a typed `int` parameter accepts `"42"`.
- For each file: path, whether it declares strict types, and whether it's consumed by other modules.
- Classify: missing in any file that defines public methods/functions → BLOCKER candidate.

### 2. Typed Properties Sem Declaração de Tipo

- Find class properties declared without a type annotation (PHP 7.4+ supports them natively).
- Common pattern to grep: `public \$`, `protected \$`, `private \$` without a preceding type token.
- For each: class, property name, inferred type from DocBlock if present, suggested native type.
- Classify: public properties without types in domain/DTO classes → BLOCKER candidate.

### 3. Return Types Ausentes em Métodos Públicos

- Find `public function` declarations without an explicit return type.
- Includes `void`, `self`, `static`, `never` — absence means PHP accepts any return silently.
- For each: class, method, current DocBlock return if present, suggested native return type.
- Special attention to constructors (always `void`, already implicit — flag only if DocBlock contradicts it).

### 4. `mixed` e `object` Sem Justificativa

- Find `: mixed` and `: object` type hints.
- Both are escape hatches: `mixed` disables type checking entirely; `object` loses shape.
- For each: file, line, context, whether a narrower type (interface, union, named class) can replace it.
- Classify: `mixed` on any public API method → IMPROVEMENT; `mixed` on validated-input handling → BLOCKER candidate.

### 5. Union Types Mal Usados (PHP 8.0+)

- Find union types (`int|string`, `Foo|Bar|null`) and evaluate their intent.
- Flag: `null` in a union where nullsafe operator (`?->`) or `?Type` shorthand fits better.
- Flag: union with more than 3 members where a shared interface/abstract class would clarify contract.
- Flag: `string|int|float|bool|null` — almost always a sign that validation is being deferred rather than enforced at the boundary.

### 6. Nullsafe Operator vs Null-Check Manual

- Find `if ($x !== null) { $x->method(); }` chains where `$x?->method()` would be cleaner.
- Also find `isset($x) && $x->method()` patterns eligible for nullsafe.
- Flag the inverse: nullsafe used in a path where null is actually a bug (not an expected state) — should throw, not silently return null.

### 7. `match` vs `switch` — Exhaustiveness

- Find `switch` statements over enum-like values or typed discriminants.
- PHP 8.0+ `match` is strict (no type coercion), returns a value, and throws `UnhandledMatchError` on missing arms — safer than `switch`.
- For each `switch`: does it have a `default` arm? If not and the value is a typed discriminant, flag as BLOCKER candidate (silent fallthrough).
- Suggest `match` when: value is a string/int/enum without intentional fallthrough.

### 8. Named Arguments — Legibilidade vs Fragilidade

- Find calls with 4+ positional arguments (especially to built-in functions or constructors).
- Named arguments (PHP 8.0+) improve call-site clarity but couple callers to parameter names — flag renaming risk.
- Flag: named arguments used on `array_*` built-ins where parameter names have historically changed between PHP versions.

### 9. Readonly Properties (PHP 8.1+)

- Find value-object and DTO classes where properties are assigned only in `__construct` but are not declared `readonly`.
- `readonly` enforces immutability at the language level — no setter, no re-assignment after init.
- For each candidate: class name, property list, whether mutation outside `__construct` exists.
- Classify: domain entities / value objects without `readonly` where mutation is clearly unintended → IMPROVEMENT.

### 10. Enum Nativo vs Constantes de Classe (PHP 8.1+)

- Find classes used only for constant groups (`class Status { const ACTIVE = 'active'; ... }`).
- PHP 8.1 backed enums (`enum Status: string`) are type-safe, exhaustively checkable, and work as type hints.
- For each constant-group class: list constants, whether values are strings/ints (backed enum candidate) or unit-only (pure enum candidate).
- Also flag `define()` / `const` at global scope for domain values that belong in enums.

### 11. Dados Externos Sem Validação

The most critical category. PHP types are not enforced at runtime for data coming from outside the process.

- Find every location where external data is used without validation:
  - `$_POST`, `$_GET`, `$_REQUEST`, `$_FILES`, `$_COOKIE`, `$_SERVER`
  - `json_decode()` result used directly
  - PDO/MySQLi result rows accessed without shape validation
  - `file_get_contents()` / curl response cast to a typed object
- For each: is there a validation library (Respect\Validation, Symfony Validator, Laravel Validator, Nette Schema) or manual shape-check before the value is trusted?
- Classify: untrusted input reaching persistence, business logic, or rendering without validation → BLOCKER.

### 12. Exception Handling — Catch Genérico e Silenciamento

- Find `catch (\Exception $e)` and `catch (\Throwable $e)` blocks that:
  - Do nothing (empty body)
  - Log but swallow (no rethrow, no status propagation)
  - Re-throw as a less-specific type without adding context
- Find bare `catch` without any type (PHP 5 legacy pattern).
- For each: what exception type is actually expected? Can it be narrowed to a specific exception class?
- Classify: empty catch or catch-and-swallow in production code → BLOCKER.

### 13. DocBlocks Conflitando com Tipos Nativos

- Find `@param` and `@return` DocBlocks that contradict or duplicate native type declarations.
- PHP 8.x native types are authoritative; a conflicting DocBlock is misleading to IDEs and static analyzers.
- Common problem: `@return User|null` remaining after the signature was updated to `?User`, or vice versa.
- Flag: DocBlocks that add `mixed` or `array` generics not expressible natively (these may be intentional for PHPDoc tooling — note them as OK if consistent).

### 14. Visibilidade de Métodos e Propriedades Incompleta

- Find methods and properties without explicit visibility (`public`, `protected`, `private`).
- In PHP, bare `function` inside a class defaults to `public` — implicit visibility is a readability hazard.
- Find `public` methods that are only called internally — candidate for `protected` or `private`.
- Find properties that break encapsulation: `public` mutable properties on domain/service classes.

### 15. Interfaces vs Classes Abstratas — Uso Correto

- Find abstract classes used where an interface would suffice (no shared state or base implementation).
- Find classes implementing zero interfaces that are injected as dependencies — no contract enforced, hard to mock/test.
- Find interfaces with a single implementation where the abstraction adds no value yet.
- Flag: concrete class type hints in constructor parameters instead of interface type hints → reduces testability.

### 16. Injeção de Dependência vs `new` Interno

- Find `new ClassName()` calls inside methods (not constructors or factory methods).
- Each internal `new` couples the class to a concrete implementation, bypasses DI container, and makes testing harder.
- For each: is the instantiated class a value object (OK), a service/repository (flag), or a third-party (flag if not wrapped).
- Classify: `new` for services/repositories inside business-logic methods → IMPROVEMENT; `new` creating untestable external dependencies → BLOCKER candidate.

### 17. Baseline de Ferramentas

Verify these are present and enforced as pre-commit or CI gates:

| Tool | Purpose |
|---|---|
| PHPStan | Static analysis — minimum level 5 for meaningful safety |
| Psalm | Alternative/complementary static analysis |
| PHP-CS-Fixer / PHP_CodeSniffer | Formatting and style enforcement |
| Infection (mutation testing) | Validates test suite quality |
| Composer audit | Dependency vulnerability scanning |

If any are absent, classify as IMPROVEMENT with estimated setup effort.
Flag if PHPStan level is below 5 — levels 0–4 miss critical type errors.

### 18. Manutenibilidade, Legibilidade e Ganhos de Segurança de Tipo

- Estimate effort vs. benefit for each category above.
- Identify which findings, if fixed, would eliminate the most runtime risk.
- Identify which findings are blocking adoption of stricter PHPStan levels.

---

## Required Output Format

### Executive Summary

2–4 sentences: overall PHP type-safety maturity, top risk, and top quick win.

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

### PHP Maturity Score

Score: X / 10

| Dimension | Score |
|---|---|
| Strict types coverage | /2 |
| Explicit types (properties, params, returns) | /2 |
| No unvalidated external input | /2 |
| Modern patterns (readonly, enum, match, nullsafe) | /2 |
| Tooling baseline (PHPStan ≥ 5, CS-Fixer, audit) | /2 |

Scoring guide:
- 8–10: Production-ready, minimal runtime type risk
- 5–7: Functional but brittle; targeted improvements recommended
- 3–4: High implicit-type surface; type safety largely nominal
- 0–2: PHP used without type enforcement; consider a structured strict migration plan

---

## What This Workflow Does NOT Do

- Does not apply fixes automatically.
- Does not create branches or PRs.
- Does not flag findings from unmodified legacy code as BLOCKERs — those are IMPROVEMENT.
- Does not replace per-PR PHP checks in `reviewer.md`.
