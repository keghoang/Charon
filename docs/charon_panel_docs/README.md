# Charon Documentation

This folder mixes current workflow-era documentation with older deep dives from
the pre-consolidation "script manager" era.

## Start Here
If you need a refresher on the codebase as it exists today, read these first:

1. `../../PROJECT_SUMMARY.md`
2. `01-architecture.md`
3. `PROJECT_STRUCTURE.md`
4. `18-testing-guide.md`
5. `19-configuration-reference.md`
6. `20-architecture-boundaries.md`
7. `21-state-and-storage.md`
8. `22-gui-system.md`
9. `23-component-map.md`
10. `24-refactor-plan.md`

## What Is Current
- `01-architecture.md`
  Current runtime flow, module map, validation pipeline, and data surfaces.
- `18-testing-guide.md`
  Manual QA paths and the current smoke-test commands.
- `19-configuration-reference.md`
  Paths, preferences, output layout, and dependency/bootstrap settings.
- `PROJECT_STRUCTURE.md`
  Current repository layout and where the important modules live.
- `20-architecture-boundaries.md`
  Intended dependency direction and rules for new code.
- `21-state-and-storage.md`
  Sources of truth, cache projections, and invalidation events.
- `22-gui-system.md`
  Shared design tokens, primitives, layout rules, and interaction states.
- `23-component-map.md`
  Ownership and target boundaries for the major runtime and GUI components.
- `24-refactor-plan.md`
  Incremental implementation order and exit conditions.
- `25-verification.md`
  Automated baseline and required production smoke tests.

## What To Treat As Historical
Most of the numbered deep dives from `02-17` still contain useful UI and
implementation notes, but many were written before Charon became explicitly
workflow-centric. They should not be treated as the source of truth for:

- runtime architecture
- testing expectations
- configuration keys
- repository layout

When those files disagree with the code, prefer the code and the current docs
listed above.

## Naming Note
You will still see legacy names such as `script_panel`, `script_model`, and
`ExecutionHistoryPanel`. Those modules now support workflow browsing and
CharonOp orchestration, not a generic script launcher.
