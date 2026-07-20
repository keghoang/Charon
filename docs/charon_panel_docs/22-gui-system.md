# GUI System

## Goals

- predictable hierarchy as features are added
- consistent density, spacing, sizing, and interaction states
- palette-aware rendering in supported Nuke/Qt versions
- thin views with testable controllers and headless services
- no one-off style recipes inside feature methods

## Design Tokens

The canonical implementation lives in `charon/ui/foundation/tokens.py`.

### Spacing
Use the shared scale: 4, 8, 12, 16, and 24 pixels. Zero is valid for nested
layouts whose parent already provides spacing. Avoid unexplained intermediate
values.

### Control sizes
- compact control height: 24
- standard control height: 32
- compact icon size: 16
- standard icon size: 20
- minimum pointer target: 24

Fixed widths are reserved for icons or intentionally aligned table actions.
Text controls should use size hints plus minimum widths.

### Semantic colors
Use roles rather than feature-specific hex values:
- surface and raised surface
- primary and muted text
- border
- accent
- success, warning, and danger

Palette-derived values are preferred for host-integrated surfaces. Dark-theme
fallbacks exist for dialogs that must render before a host palette is stable.

## Reusable primitives

- `PanelHeader`: title, optional subtitle, and action region
- `SectionCard`: grouped content with standard padding and border
- `ActionButton`: primary, secondary, toolbar, or destructive role
- `StatusBadge`: neutral, active, success, warning, or error state
- `EmptyState`: title, explanation, and optional action
- `BusyState`: consistent progress and cancellation presentation

## Feature composition

```text
CharonWindow shell
    WorkflowsFeature
        FolderPanel
        WorkflowTable
        MetadataPanel
    CharonBoardFeature
    TinyModeFeature
    ConnectionStatusFeature
```

The shell owns navigation and presentation mode. Feature controllers own their
state and application commands. Widgets do not access sibling internals.

## Interaction states

Every asynchronous action uses:

```text
Idle -> Loading -> Success
               -> Error
               -> Cancelled
```

Buttons, labels, progress, and retry actions render from this state instead of
independent booleans and timers.

## Review checklist

- Uses shared spacing and control metrics.
- Uses a shared primitive before introducing custom QSS.
- Works at minimum window size and 150% display scaling.
- Handles long workflow/model paths without forcing window growth.
- Exposes keyboard focus, tooltip, disabled, busy, and error states.
- Performs no blocking I/O on the GUI thread.

