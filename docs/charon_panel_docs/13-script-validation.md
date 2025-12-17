# Script Validation System

The Script Validation System provides centralized logic for determining whether scripts can be executed, how they should be displayed, and what visual properties they should have. This ensures consistent behavior across all UI components.

## Overview

The `ScriptValidator` class centralizes:
- Execution permission checks
- Entry file validation
- Host compatibility verification
- Visual property determination (colors, opacity, selectability)

## Core Components

### ScriptValidator Class

Located in `charon/script_validator.py`, this class provides static methods for all validation needs:

```python
class ScriptValidator:
    @staticmethod
    def can_execute(script_path: str, metadata: dict, host: str) -> Tuple[bool, str]
    
    @staticmethod
    def has_valid_entry(script_path: str, metadata: dict) -> Tuple[bool, str]
    
    @staticmethod
    def is_compatible(metadata: dict, host: str) -> bool
    
    @staticmethod
    def get_visual_properties(script_path: str, metadata: dict, host: str, is_bookmarked: bool) -> dict
```

## Validation Rules

### 1. Execution Validation (`can_execute`)

A script can be executed if ALL of the following are true:
- Script path exists
- Script has metadata (`.charon.json` file)
- Script is compatible with current host
- Script has a valid entry file

```python
can_run, reason = ScriptValidator.can_execute(script_path, metadata, host)
if not can_run:
    print(f"Cannot execute: {reason}")
```

### 2. Entry File Validation (`has_valid_entry`)

Entry file validation follows this hierarchy:
1. **Explicit entry**: Uses `entry` field from metadata
2. **Script type inference**: Based on `script_type` field
3. **Common patterns**: Searches for standard entry files

Valid entry file must:
- Exist in the script directory
- Be non-empty (size > 0 bytes)
- Match expected patterns for script type

Common entry patterns by script type:
- **Python**: `main.py`, `run.py`, `script.py`, `__main__.py`
- **MEL**: `main.mel`, `run.mel`, `script.mel`

### 3. Host Compatibility (`is_compatible`)

Compatibility is determined by:
- Script's `software` field in metadata
- Current host application
- Special handling for "none" software

Rules:
- Scripts with matching software are compatible
- Scripts with "none" software show in all hosts but are not executable
- Scripts without metadata are treated as "none" software

### 4. Visual Properties (`get_visual_properties`)

Returns a dictionary with:
```python
{
    "color": "#hexcolor",      # Color based on software
    "should_fade": bool,       # Whether to apply opacity
    "is_selectable": bool,     # Whether item can be selected
    "can_run": bool           # Whether script can execute
}
```

Visual rules:
- **Compatible + valid entry**: Full color, selectable, can run
- **Compatible + no entry**: Full color, selectable, cannot run
- **Incompatible**: Faded color, selectable, cannot run
- **"None" software**: Always faded, always selectable, never runs

## Integration with UI Components

### Script Panel (Normal Mode)
```python
# In ScriptTableModel
def can_run_script(self, script: ScriptItem) -> bool:
    can_run, _ = ScriptValidator.can_execute(
        script.path, 
        script.metadata, 
        self.host
    )
    return can_run
```

### Bookmarks Panel (Command Mode)
```python
# In BookmarksListModel
def get_visual_properties(self, script_item):
    return ScriptValidator.get_visual_properties(
        script_item.path,
        script_item.metadata,
        self.host,
        is_bookmarked=True
    )
```

### Execution Flow
```python
# In MainWindow.execute_script
def execute_script(self, script_path):
    metadata = get_charon_config(script_path)
    can_run, reason = ScriptValidator.can_execute(
        script_path, 
        metadata, 
        self.host
    )
    
    if not can_run:
        system_debug(f"Script cannot run: {reason}")
        return
    
    # Proceed with execution
    self.script_engine.execute_script(script_path)
```

## Color and Opacity System

### Software Colors
Defined in `config.py` using unified SOFTWARE configuration:
```python
# Colors are now part of the unified SOFTWARE dictionary
SOFTWARE = {
    "maya": {
        "color": "#3498db",  # Blue
        # ... other settings
    },
    "nuke": {
        "color": "#f1c40f",  # Yellow
        # ... other settings
    },
    "windows": {
        "color": "#27ae60",  # Green
        # ... other settings
    }
}

# Use get_software_color() utility function for consistency
from charon.utilities import get_software_color
color = get_software_color("Maya")  # Returns "#3498db"
```

### Opacity Application
```python
# For incompatible/non-runnable scripts
INCOMPATIBLE_OPACITY = 0.4  # 40% opacity

# Applied via utilities.apply_incompatible_opacity()
color.setAlpha(int(255 * INCOMPATIBLE_OPACITY))
```

## Error Messages

The validation system provides clear error messages:
- "Script path does not exist"
- "No metadata found"
- "Not compatible with [host]"
- "No valid entry file found"

## Workflow Validation (ComfyUI Integration)

Beyond script metadata checks, Charon performs pre-flight validation for ComfyUI workflows:

- **Entry Point**: `charon.comfy_validation.validate_comfy_environment()` inspects the configured Comfy install, embedded Python, required models, and custom nodes. Missing pieces are returned as `ValidationIssue` objects.
- **UI Integration**: The script browser triggers validation via the *Validate* column. States progress from *Validate* ? *Validatingâ€¦* ? *Resolve* ? *? Passed*. Results are cached per workflow hash so the UI can display status without re-hitting ComfyUI every time.
- **Per-User Cache**: Validation payloads persist under `%LOCALAPPDATA%\Charon\plugins\charon\Charon_repo_local\workflow\<workflow>\.charon_cache\validation\\validation_status.json`. This keeps personal model layouts and overrides local to each artist.
- **Execution Guard**: Grab/Execute remains disabled until a workflow reaches *? Passed*, preventing surprise failures when models or custom nodes are missing.

### Validation Result Dialog

Selecting *Resolve* opens a rich checklist (`ValidationResolveDialog`) that summarises every `ValidationIssue` returned by the validator:

- **Checklist Rows**: Each issue renders as a pass/fail row with a concise summary and the original detail text.
- **Formatted Details**: Missing assets call out the exact filename and the directories ComfyUI searched (for example, `Cannot find <b>FLUX1\flux1-fill-dev.safetensors</b> under <b>models/unet, models/diffusion_models</b>`).
- **Auto Resolve Buttons**: Supported issues expose an *Auto Resolve* button that delegates to the helpers in `charon.validation_resolver` (copying models, cloning custom nodes, etc.). Resolution only searches the directories Comfy reported for the missing asset (resolver.missing[].searched), preventing cross-folder fixes.
- **Advanced Mode Raw View**: When **Advanced User Mode** is enabled, the context menu on the *Validate* column adds *Show Raw Validation Payload*, opening the JSON payload for power users.
- **Activity Log**: Each auto-resolve attempt appends a note at the bottom of the dialog so artists can see what changed.

The validation dialog is intentionally read-only; actual fixes are deferred to the resolve helpers so they can be reused from scripting or future tooling.

- **Live Status**: As soon as the last missing model is resolved, the section header flips to the green **âœ“ Passed** state. The Action column grows to fit the â€œResolvedâ€ label and buttons disable once a row is fixed.

#### Validation Artifacts

Every validation run now writes per-user artifacts beside the validated workflow (stored under %LOCALAPPDATA%\Charon\plugins\charon\Charon_repo_local\workflow\<relative_path>\.charon_cache\validation\):

- validation_result_raw.json captures the first validation payload exactly as ComfyUI returned it. This file is never deleted automatically, giving artists a canonical snapshot.
- validation_resolve_log.json is an ordered list of resolution events (button clicks, auto-resolve copies, etc.) so support can review what changed post-validation.

Both files live inside the local mirror introduced during validation/override consolidation and survive workflow overrides or subsequent validation runs.

### Custom Node & Model Resolution

- **Dynamic Categories**: Model discovery asks the running ComfyUI instance (via `folder_paths`) to resolve each filename, so reorganized libraries (for example `models/unet`) are detected automatically.
- **Custom Node Script**: A helper spins up the embedded interpreter, loads ComfyUI, and reports any node classes that failed to register.
- **Resolve Helpers**: `charon.validation_resolver` contains the tooling used by the UI to attempt fixes; validation itself remains a read-only check.

## Best Practices

1. **Always validate before execution**: Use `can_execute()` before running scripts
2. **Use visual properties consistently**: Apply the same visual rules across all UI components
3. **Provide feedback**: Show validation errors to users
4. **Cache validation results**: For performance in large lists

## Example: Complete Validation Flow

```python
# Load script metadata
script_path = "/path/to/script"
metadata = get_charon_config(script_path)

# Check if executable
can_run, reason = ScriptValidator.can_execute(script_path, metadata, "Maya")

if can_run:
    # Execute script
    script_engine.execute_script(script_path)
else:
    # Show error to user
    show_error_dialog(f"Cannot run script: {reason}")

# Get visual properties for UI
props = ScriptValidator.get_visual_properties(
    script_path, 
    metadata, 
    "Maya", 
    is_bookmarked=False
)

# Apply to UI element
item.setForeground(QColor(props["color"]))
if props["should_fade"]:
    apply_opacity(item)
```

## Future Enhancements

- Performance validation (warn about slow scripts)
- Dependency checking (required modules/plugins)
- Version compatibility validation
- Script signing/security validation


