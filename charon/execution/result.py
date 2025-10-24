"""
Execution result classes for the Charon script execution engine.

These classes define the return types and status tracking for script execution.
"""

import time
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Any


class ExecutionStatus(Enum):
    """Script execution status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ExecutionResult:
    """Result of script execution"""
    status: ExecutionStatus
    start_time: float
    end_time: Optional[float] = None
    error_message: Optional[str] = None
    output: Optional[str] = None
    return_value: Any = None
    execution_mode: Optional[str] = None  # "main_thread" or "background"
    
    @property
    def execution_time(self) -> float:
        """Calculate execution time in seconds"""
        if self.end_time is None:
            return time.time() - self.start_time
        return self.end_time - self.start_time
    
    @property
    def success(self) -> bool:
        """True if execution completed successfully"""
        return self.status == ExecutionStatus.COMPLETED
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization"""
        return {
            "status": self.status.value,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "error_message": self.error_message,
            "output": self.output,
            "return_value": self.return_value,
            "execution_mode": self.execution_mode,
            "execution_time": self.execution_time,
            "success": self.success
        }