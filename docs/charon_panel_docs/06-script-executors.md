# Script Executor Architecture

## Overview

The Script Executor architecture provides a clean, extensible way to execute different script types (Python, MEL, JavaScript, etc.) within Charon's execution framework. This architecture was introduced to solve the issue of MEL scripts being executed as Python scripts and to make it easy to add new script types in the future.

## Core Design Principles

1. **Separation of Concerns**: Script execution logic is separated from thread management
2. **Extensibility**: New script types can be added without modifying existing executors
3. **Registry Pattern**: Dynamic lookup of executors based on script type
4. **Host Validation**: Scripts are validated against host capabilities before execution

## Architecture Components

### 1. Abstract Base Class (ScriptExecutor)

Located in `/execution/script_executors/base.py`, this defines the interface all script executors must implement:

```python
class ScriptExecutor(ABC):
    @abstractmethod
    def can_execute(self, script_type: str) -> bool
    
    @abstractmethod  
    def execute(self, code: str, namespace: Dict[str, Any], host: str) -> Any
    
    @abstractmethod
    def get_file_extensions(self) -> List[str]
    
    def validate_for_host(self, host: str) -> Tuple[bool, str]
    
    def prepare_namespace(self, namespace: Dict[str, Any], host: str) -> Dict[str, Any]
```

### 2. Script Executor Registry

Located in `/execution/script_executors/registry.py`, this provides:
- Registration of script executors
- Dynamic lookup by script type
- Validation utilities
- File extension mapping

### 3. Built-in Executors

#### PythonExecutor
- Executes Python scripts using `exec()`
- Maintains backward compatibility with existing execution logic
- Supports all hosts that have Python

#### MELExecutor  
- Executes MEL scripts using `maya.mel.eval()`
- Only available when running in Maya
- **ALWAYS runs on main thread** (MEL is not thread-safe)
- Provides clear error messages when used outside Maya

## How It Works

1. **Script Type Detection**:
   - From metadata (`script_type` field in `.charon.json`)
   - From file extension (fallback)
   - Defaults to "python" if unknown

2. **Executor Selection**:
   - The registry looks up the appropriate executor
   - Validates the script can run on the current host
   - Returns clear error messages if validation fails

3. **Execution Flow**:
   ```
   ExecutionEngine → ThreadExecutor → ScriptExecutorRegistry → ScriptExecutor
   ```

## Adding New Script Types

To add a new script type (e.g., JavaScript):

1. **Create the Executor**:
   ```python
   # /execution/script_executors/javascript_executor.py
   from .base import ScriptExecutor
   
   class JavaScriptExecutor(ScriptExecutor):
       def can_execute(self, script_type: str) -> bool:
           return script_type.lower() == "javascript"
       
       def execute(self, code: str, namespace: Dict[str, Any], host: str) -> Any:
           # Implementation using Node.js or browser engine
           pass
       
       def get_file_extensions(self) -> List[str]:
           return [".js", ".mjs"]
   ```

2. **Register the Executor**:
   ```python
   # In __init__.py or startup code
   from .javascript_executor import JavaScriptExecutor
   ScriptExecutorRegistry.register("javascript", JavaScriptExecutor())
   ```

3. **Update Host Capabilities** (in `config.py`):
   ```python
   HOST_CAPABILITIES = {
       "windows": {
           "supports": ["python", "javascript"],
           ...
       }
   }
   ```

## Script Type Configuration

Scripts specify their type in `.charon.json`:

```json
{
    "software": ["Maya"],
    "entry": "setup.mel",
    "script_type": "mel",
    "run_on_main": true
}
```

If `script_type` is not specified, it's detected from the file extension.

## Thread Executor Integration

Both `MainThreadExecutor` and `BackgroundExecutor` use the same registry:

1. They receive the `script_type` parameter
2. Look up the executor from the registry
3. Validate against host capabilities
4. Execute using the appropriate executor

The threading logic remains unchanged - only the script execution method varies.

## Error Handling

The architecture provides clear error messages:

- Unknown script type → Lists available types
- Wrong host → Explains which hosts support the script type
- Missing dependencies → Guides user to required setup

## Benefits

1. **Clean Separation**: Thread management and script execution are independent
2. **Easy Extension**: Add new script types without touching existing code
3. **Type Safety**: Each executor handles its specific script type
4. **Better Error Messages**: Users get clear guidance on script compatibility
5. **Future-Proof**: Ready for JavaScript, VEX, MaxScript, etc.

## Testing

When testing script executors:

1. Test each executor in isolation
2. Test registry registration and lookup
3. Test host validation logic
4. Test with actual scripts in the target host application

## Future Considerations

- **Async Execution**: Some script types may benefit from async execution
- **Script Preprocessing**: Executors could transform scripts before execution
- **Output Handling**: Different script types may need different output capture methods
- **Debugging Support**: Script-specific debugging capabilities

## Related Documentation

- See `01-architecture.md` for overall system architecture
- See `04-host-integration.md` for host-specific details
- See `05-script-engine.md` for execution engine details