# TypeScript Audit Workflow

Activation: on-demand only. Do not run as part of routine PR review.
Trigger: human requests a TypeScript quality audit for a project.

## Prerequisites

- Project uses TypeScript (`.ts`/`.tsx` files present).
- `docs/software-overview.md` and `docs/limits.md` are ready.
- Human has explicitly requested this audit.

## Scope

Whole-codebase analysis. Not scoped to a diff or branch.
Report findings; do not apply fixes unless the human explicitly authorizes.

---

## Audit Checklist

### 1. Excessive `any` Usage

- Grep for `: any`, `as any`, `<any>`, `Promise<any>`, `Array<any>`.
- For each occurrence: file, line, context.
- Suggest: `unknown` + narrowing, union type, or a constrained generic.

### 2. Runtime Validation at Trust Boundaries

The most critical category. TypeScript types are compile-time only; they do not survive API calls, `JSON.parse`, environment variables, or form input.

- Find every location where external data is cast or annotated as a TypeScript type without a preceding runtime validation step.
- Common patterns to grep: `JSON.parse(`, `response.json()`, `process.env.`, `req.body`, `event.data`.
- For each: is there a Zod schema, io-ts codec, or manual shape check before the type is applied?
- Classify: unvalidated external data typed directly → BLOCKER candidate; missing validation on internal-only data → IMPROVEMENT.

### 3. `@ts-ignore` and `@ts-nocheck` Usage

- Grep for `@ts-ignore`, `@ts-nocheck`, `@ts-expect-error`.
- `@ts-expect-error` is acceptable when testing known type errors in test files; document it.
- `@ts-ignore` and `@ts-nocheck` suppress real problems — flag every usage.
- For each: file, line, what error was being suppressed, and suggested proper fix.

### 4. React Component Props Without Types

- Find components (function or class) that accept props without an explicit `interface` or `type`.
- List component name, file, and suggested interface shape.

### 5. `interface` vs `type` Consistency

- Identify whether the project mixes both without a stated convention.
- Recommend one pattern and list files that diverge.
- Guidance: prefer `interface` for object shapes that may be extended; prefer `type` for unions, intersections, aliases, and mapped types.

### 6. `enum` vs Union Literals

- Find all `enum` declarations.
- Classify each: does it need runtime iteration or reverse-lookup? If not, a union literal is lighter and tree-shakeable.
- Example improvement:
  ```typescript
  // before
  enum Status { Loading, Success, Error }

  // after
  type Status = "loading" | "success" | "error";
  ```
- Also flag `as const` + `typeof arr[number]` as an alternative for value arrays.

### 7. Discriminated Unions

- Find union types or state-like interfaces with multiple optional properties that represent mutually exclusive states.
- Suggest modeling with a literal `type` discriminant field:
  ```typescript
  // before
  interface Result { data?: User; error?: string; loading?: boolean }

  // after
  type Result =
    | { type: "loading" }
    | { type: "success"; data: User }
    | { type: "error"; error: string };
  ```
- Discriminated unions enable exhaustive narrowing and eliminate impossible state combinations.

### 8. Unsafe `as` Assertions

- Find `as SomeType` on paths that receive external/untrusted input (API responses, user input, `JSON.parse`).
- Classify: unsafe (BLOCKER candidate), internal-only (IMPROVEMENT), or justified (OK with comment).
- Flag `as unknown as T` double-casting — almost always a sign of a modelling error.

### 9. Functions Without Explicit Types

- Find exported functions with missing parameter types or inferred-`any` return types.
- Find callbacks passed to `Array.map`/`filter`/`reduce` with untyped parameters.
- Find uses of `Function` as a type — replace with explicit call signatures.
- Find `catch (e)` blocks where `e` is used as a typed value without narrowing (`e instanceof Error`).

### 10. Constrained Generics

- Find bare `<T>` generics with no constraint where the function clearly expects a shape.
- Suggest `<T extends { id: string }>` or equivalent to document contract and catch misuse at call site.
- Flag generic functions that internally access `.id`, `.length`, or other properties without constraining `T` to guarantee them.

### 11. `never` Exhaustive Checks

- Find `switch` statements and if-else chains over union types.
- Verify each has a default/else branch that assigns the discriminant to `never`:
  ```typescript
  function assertNever(x: never): never {
    throw new Error("Unhandled case: " + JSON.stringify(x));
  }
  ```
- Without this, adding a new union variant silently falls through at runtime.

### 12. `satisfies` and `as const` Opportunities

- **`satisfies` (TS 4.9+):** Find objects directly annotated with a type where literal types are lost.
  ```typescript
  // before — port widens to number
  const config: ServerConfig = { port: 3000 };

  // after — port stays 3000, shape still validated
  const config = { port: 3000 } satisfies ServerConfig;
  ```
  Useful for config objects, route maps, and feature flag definitions.

- **`as const`:** Find fixed arrays or objects used as lookup tables or option sets that are annotated loosely.
  ```typescript
  // before
  const ROLES = ["admin", "user", "guest"];     // string[]
  type Role = string;

  // after
  const ROLES = ["admin", "user", "guest"] as const;
  type Role = typeof ROLES[number];              // "admin" | "user" | "guest"
  ```

### 13. `readonly` and Immutability

- Find array parameters and state-like interfaces that mutate their inputs.
- Suggest `ReadonlyArray<T>` / `readonly T[]` for arrays that should not be mutated by the callee.
- Suggest `Readonly<T>` for config/settings interfaces.
- Find `.push()`, `.splice()`, direct index assignment on React state — flag as a correctness risk.

### 14. `Object.keys()` Without Narrowing

- `Object.keys(obj)` always returns `string[]`, not `(keyof typeof obj)[]`.
- Find usages where the result is used as a key to index the original object without a cast.
- Suggest a typed helper or explicit `keyof typeof obj` pattern.

### 15. Duplicated Types and Shared Extraction

- Identify identical or near-identical `interface`/`type` declarations across files.
- List types used in 3+ files that are not yet in a shared location.
- Suggest canonical location: `src/types/`, `src/shared/types.ts`, or co-located barrel file.
- Check whether built-in utility types (`Partial<T>`, `Required<T>`, `Omit<T,K>`, `Pick<T,K>`, `Record<K,V>`) could replace manual re-declarations.

### 16. `tsconfig.json` Evaluation

Recommended flags to verify or enable:

| Flag | Why |
|---|---|
| `"strict": true` | Master switch — enables all strict checks below |
| `"noImplicitAny": true` | Catches untyped parameters (included in `strict`) |
| `"strictNullChecks": true` | Prevents null/undefined runtime errors (included in `strict`) |
| `"useUnknownInCatchVariables": true` | `catch (e)` becomes `unknown`, not `any` (TS 4.4+) |
| `"noUncheckedIndexedAccess": true` | Array and record access returns `T \| undefined` |
| `"exactOptionalPropertyTypes": true` | `?` properties cannot be set to `undefined` explicitly |
| `"noPropertyAccessFromIndexSignature": true` | Forces bracket notation on index-signed types |
| `"noImplicitReturns": true` | All code paths must return a value |
| `"noFallthroughCasesInSwitch": true` | Prevents accidental `switch` fallthrough |
| `"forceConsistentCasingInFileNames": true` | Cross-platform import safety |

Report current state (enabled / disabled) for each flag and flag any that are disabled but would catch real issues in the current codebase.

### 17. Tooling Baseline

Verify these are present and enforced as pre-commit gates (not just CI):

| Tool | Purpose |
|---|---|
| `typescript-eslint` | TS-aware lint rules beyond compiler checks |
| `eslint-plugin-react` | React-specific type and hook rules |
| Prettier | Formatting — removes style noise from reviews |
| Zod / io-ts | Runtime validation at API and input boundaries |
| TypeDoc | Type-driven documentation generation |

If any are absent, classify as IMPROVEMENT with estimated setup effort.

### 18. Maintainability, Readability, and Type Safety Gains

- Estimate effort vs. benefit for each category above.
- Identify which findings, if fixed, would eliminate the most runtime risk.
- Identify which findings are blocking adoption of stricter `tsconfig` flags.

---

## Required Output Format

### Executive Summary

2–4 sentences: overall TypeScript maturity, top risk, and top quick win.

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

### TypeScript Maturity Score

Score: X / 10

| Dimension | Score |
|---|---|
| Strict config coverage | /2 |
| Explicit types and no `any` | /2 |
| No unsafe assertions or suppressions | /2 |
| Modern patterns (discriminated unions, `satisfies`, `as const`, `never`) | /2 |
| Runtime safety and tooling | /2 |

Scoring guide:
- 8–10: Production-ready, minimal runtime type risk
- 5–7: Functional but brittle; targeted improvements recommended
- 3–4: High implicit-`any` surface; type safety largely nominal
- 0–2: TypeScript used as a linter only; consider a structured strict migration plan

---

## What This Workflow Does NOT Do

- Does not apply fixes automatically.
- Does not create branches or PRs.
- Does not flag findings from unmodified legacy code as BLOCKERs — those are IMPROVEMENT.
- Does not replace per-PR TypeScript checks in `reviewer.md`.
