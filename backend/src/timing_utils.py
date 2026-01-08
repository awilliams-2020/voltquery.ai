"""
Timing utilities for tracking workflow performance and identifying bottlenecks.

Provides a context manager and decorator for timing operations throughout the workflow.
"""

import time
import functools
import asyncio
from typing import Dict, List, Optional, Any
from contextlib import contextmanager
from collections import defaultdict


class TimingContext:
    """Context manager for timing operations with hierarchical tracking."""
    
    def __init__(self, name: str, parent: Optional['TimingContext'] = None):
        self.name = name
        self.parent = parent
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.children: List['TimingContext'] = []
        self.metadata: Dict[str, Any] = {}
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.time()
        if self.parent:
            self.parent.children.append(self)
        return False
    
    @property
    def duration(self) -> float:
        """Get duration in seconds."""
        if self.start_time is None:
            return 0.0
        end = self.end_time if self.end_time is not None else time.time()
        return end - self.start_time
    
    def add_metadata(self, key: str, value: Any):
        """Add metadata to this timing context."""
        self.metadata[key] = value


class WorkflowTimer:
    """Main timer for tracking workflow performance."""
    
    def __init__(self, workflow_name: str = "query"):
        self.workflow_name = workflow_name
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.timings: List[TimingContext] = []
        self.current_context: Optional[TimingContext] = None
        self._stack: List[TimingContext] = []
    
    def start(self):
        """Start the workflow timer."""
        self.start_time = time.time()
    
    def stop(self):
        """Stop the workflow timer."""
        self.end_time = time.time()
    
    @contextmanager
    def time(self, name: str, **metadata):
        """
        Context manager for timing a section of the workflow.
        
        Args:
            name: Name of the timing section
            **metadata: Additional metadata to attach to this timing
        """
        context = TimingContext(name, parent=self.current_context)
        if self.current_context is None:
            self.timings.append(context)
        
        # Push onto stack
        previous = self.current_context
        self.current_context = context
        self._stack.append(context)
        
        try:
            with context:
                for key, value in metadata.items():
                    context.add_metadata(key, value)
                yield context
        finally:
            # Pop from stack
            self._stack.pop()
            self.current_context = previous
    
    def get_summary(self) -> Dict[str, Any]:
        """
        Get a summary of all timings.
        
        Returns:
            Dictionary with timing summary including total time, breakdown, and bottlenecks
        """
        total_time = (self.end_time - self.start_time) if self.end_time and self.start_time else 0.0
        
        def flatten_timings(contexts: List[TimingContext], level: int = 0) -> List[Dict[str, Any]]:
            """Flatten hierarchical timings into a list."""
            result = []
            for ctx in contexts:
                result.append({
                    "name": ctx.name,
                    "duration": ctx.duration,
                    "level": level,
                    "metadata": ctx.metadata,
                    "percentage": (ctx.duration / total_time * 100) if total_time > 0 else 0.0
                })
                if ctx.children:
                    result.extend(flatten_timings(ctx.children, level + 1))
            return result
        
        flat_timings = flatten_timings(self.timings)
        
        # Sort by duration descending
        flat_timings.sort(key=lambda x: x["duration"], reverse=True)
        
        # Find bottlenecks (top 5 longest operations)
        bottlenecks = [
            {
                "name": t["name"],
                "duration": t["duration"],
                "percentage": t["percentage"],
                "metadata": t["metadata"]
            }
            for t in flat_timings[:5]
        ]
        
        # Group by operation type
        by_type = defaultdict(list)
        for t in flat_timings:
            # Extract base name (before any colons or special chars)
            base_name = t["name"].split(":")[0].split("(")[0].strip()
            by_type[base_name].append(t["duration"])
        
        type_summary = {
            name: {
                "count": len(durations),
                "total": sum(durations),
                "average": sum(durations) / len(durations) if durations else 0.0,
                "max": max(durations) if durations else 0.0
            }
            for name, durations in by_type.items()
        }
        
        return {
            "workflow": self.workflow_name,
            "total_time": total_time,
            "timings": flat_timings,
            "bottlenecks": bottlenecks,
            "by_type": type_summary
        }
    
    def print_summary(self):
        """Print a formatted summary of timings."""
        summary = self.get_summary()
        
        print("\n" + "=" * 80)
        print(f"WORKFLOW TIMING SUMMARY: {summary['workflow']}")
        print("=" * 80)
        print(f"Total Time: {summary['total_time']:.3f}s")
        print("\nTop Bottlenecks:")
        for i, bottleneck in enumerate(summary['bottlenecks'], 1):
            indent = "  " * bottleneck.get("level", 0)
            print(f"{i}. {indent}{bottleneck['name']}: {bottleneck['duration']:.3f}s ({bottleneck['percentage']:.1f}%)")
            if bottleneck.get("metadata"):
                for key, value in bottleneck["metadata"].items():
                    print(f"   {indent}  {key}: {value}")
        
        print("\nBreakdown by Operation Type:")
        for op_type, stats in sorted(summary['by_type'].items(), key=lambda x: x[1]['total'], reverse=True):
            print(f"  {op_type}:")
            print(f"    Count: {stats['count']}")
            print(f"    Total: {stats['total']:.3f}s")
            print(f"    Average: {stats['average']:.3f}s")
            print(f"    Max: {stats['max']:.3f}s")
        
        print("\nDetailed Timings:")
        for timing in summary['timings']:
            indent = "  " * timing['level']
            print(f"{indent}{timing['name']}: {timing['duration']:.3f}s ({timing['percentage']:.1f}%)")
            if timing.get("metadata"):
                for key, value in timing["metadata"].items():
                    print(f"{indent}  {key}: {value}")
        
        print("=" * 80 + "\n")


# Global timer instance (can be accessed from anywhere)
_global_timer: Optional[WorkflowTimer] = None


def get_timer() -> Optional[WorkflowTimer]:
    """Get the global timer instance."""
    return _global_timer


def set_timer(timer: WorkflowTimer):
    """Set the global timer instance."""
    global _global_timer
    _global_timer = timer


def time_function(name: Optional[str] = None):
    """
    Decorator for timing function execution.
    
    Usage:
        @time_function("my_function")
        def my_function():
            ...
    """
    def decorator(func):
        func_name = name or func.__name__
        
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            timer = get_timer()
            if timer:
                with timer.time(func_name):
                    return await func(*args, **kwargs)
            else:
                return await func(*args, **kwargs)
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            timer = get_timer()
            if timer:
                with timer.time(func_name):
                    return func(*args, **kwargs)
            else:
                return func(*args, **kwargs)
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator

