# Charon Workflow Panel
Charon helps you discover studio-ready workflows, drop them into Nuke, and drive ComfyUI renders without leaving the panel. The tool is built and maintained by **Kien**.

## What You Can Do
- Browse the curated workflow library with metadata, tags, and previews.
- Inspect parameters, dependencies, and prompt text before committing.
- Spawn CharonOps in your script with a single click.
- Submit jobs to ComfyUI and watch status roll from `Ready -> Processing -> Completed`.

## Fast Workflow Run
1. **Browse**: Locate a workflow from the left folder tree or use Quick Search (`Ctrl+F`).
2. **Review**: Check the metadata panel for descriptions, dependencies, and notes.
3. **Grab**: Click **Grab Workflow** (or double-click the entry) to create a CharonOp in the current script.
4. **Process**: On the CharonOp, press **Execute** to convert, submit, and monitor results.
5. **Inspect**: Open the Execution History tab to review logs, outputs, and retry if needed.

## Essential Controls
- `Ctrl+R` Refresh repository index and metadata cache.
- `Ctrl+Enter` Process the selected workflow immediately.
- `F4` Toggle Quick Search anywhere in the panel.
- `Space` Open the workflow readme for notes and troubleshooting.

## Helpful Tips
- Use the Tag Bar to filter down to lighting, look-dev, or utility workflows.
- Preferences live under **Settings -> Workflows**; keep the ComfyUI path pointed at the portable bundle.
- Debug artifacts land in `D:\Nuke\charon\debug`; include them when reporting issues.
