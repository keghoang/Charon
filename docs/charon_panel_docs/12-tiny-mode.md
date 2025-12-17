# Tiny Mode

Tiny Mode now mirrors CharonBoard in a compact floating surface. Artists can leave it open while they work to keep an eye on the most relevant CharonOp without committing screen space to the full panel.

## Overview
- Tracks the active or most recently updated CharonOp (prefers errors, then processing nodes).
- Shows each CharonOp name with a compact progress indicator and status text.
- Runs as a lightweight floating window that updates every two seconds.
- All actions live in the right-click context menu; the surface itself stays clutter-free.
- Shares the main panel's ComfyUI footer so connection status and launch controls remain handy.
- Progress bars are sized with the final layout before first paint to prevent the width snap on entry, and cards use rounded corners for clearer separation.

## Activation
### Global Hotkey
- Default toggle: `F3` (configurable in Settings -> Charon Keybinds).
- Works both inside and outside the main Charon window.
- Tapping `F3` swaps between the full panel and Tiny Mode, keeping focus on entry.

### Window Behaviour
- Width/height defaults come from `config.TINY_MODE_*` constants.
- Geometry is stored separately from the full panel so regular resizing does not affect Tiny Mode.
- Host-specific window flags (always-on-top, tool window, etc.) still apply based on settings.
- The stacked widget switches to Tiny Mode after the window is resized/centered, keeping the progress bars stable on first render.

## UI Elements
1. **CharonOp List** - each entry shows the node name (prefix stripped) with an inline progress bar and status text.
2. **Empty State** - a lightweight message appears when no CharonOps are detected.
3. **ComfyUI Footer** - the same launch/settings widget from the full panel, reparented into Tiny Mode while it is active.

Right click anywhere inside the window to access actions. Double-clicking a node focuses it; double-clicking empty space still opens the full CharonBoard tab.

## Node Selection
- Nodes are automatically ordered by urgency: errors first, then processing nodes, followed by in-progress and recently completed items.
- Double-click a node name to center the corresponding CharonOp in the host node graph and highlight it inside CharonBoard.

## Context Menu Actions
- **Open Output Folder** - opens the resolved results directory when available.
- **Reveal Workflow File** - opens Explorer with the current workflow selected.
- **Copy Node Summary** - places a text summary (status, workflow, output paths) on the clipboard.
- **Focus in Node Graph** - explicitly recenters the selected node without double-clicking.
- **Open Full CharonBoard** - leaves Tiny Mode and focuses the CharonBoard tab in the main window.
- **Exit Tiny Mode** - returns to the full panel (same result as pressing `F3`).
- **Settings...** - opens the settings dialog to adjust keybinds and preferences.

## Integration Notes
- `TinyModeWidget` lives alongside the main window and pulls snapshots through `scene_nodes_runtime.list_scene_nodes`.
- Updates continue while the widget is shown or hidden; entering Tiny Mode simply swaps the stacked widget.
- The context actions reuse the same filesystem hints as the full CharonBoard (temp results, workflow paths, etc.).
- The ComfyUI footer widget migrates between the normal panel and Tiny Mode, so there is only one connection watcher and launch control instance.
- The row widget caches its chunk color to avoid redundant stylesheet resets; progress bars default to "Ready" text and rounded caps so they do not flash empty on first render.

## Best Practices
- Keep Tiny Mode on a secondary monitor for at-a-glance feedback during long conversions.
- Double-click nodes while troubleshooting to jump between CharonOps without leaving the mini view.
- Use the context menu to exit Tiny Mode instead of hunting for buttons--the surface deliberately stays free of chrome.

## Future Ideas
- Surface additional metadata (elapsed time, assignee) as optional metadata chips.
- Subscribe directly to CharonBoard refresh events to avoid duplicate polling when both views are open.
- Offer quick actions (retry, open logs) once processor error handling is unified across the UI.
