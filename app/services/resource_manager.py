"""
Resource management for file processing operations.
"""
import asyncio
import logging
import os
import time
import threading
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, field
from contextlib import asynccontextmanager
from pathlib import Path
import psutil
import weakref

logger = logging.getLogger(__name__)


@dataclass
class ResourceMetrics:
    """Resource usage metrics for file processing operations."""
    memory_usage_mb: float
    cpu_usage_percent: float
    temp_files_created: List[str] = field(default_factory=list)
    processing_time_ms: float = 0.0
    peak_memory_mb: float = 0.0
    start_time: float = field(default_factory=time.time)
    
    def update_peak_memory(self, current_memory_mb: float) -> None:
        """Update peak memory usage if current usage is higher."""
        if current_memory_mb > self.peak_memory_mb:
            self.peak_memory_mb = current_memory_mb
    
    def finalize(self) -> None:
        """Finalize metrics calculation."""
        self.processing_time_ms = (time.time() - self.start_time) * 1000


@dataclass
class ResourceLimits:
    """Resource limits for file processing operations."""
    max_memory_mb: float = 512.0  # 512MB max memory per operation
    max_processing_time_seconds: float = 300.0  # 5 minutes max processing time
    max_temp_files: int = 10  # Maximum temporary files per operation
    max_concurrent_operations: int = 5  # Maximum concurrent file processing operations


class ResourceTracker:
    """Tracks resource usage for individual file processing operations."""
    
    def __init__(self, operation_id: str, limits: ResourceLimits):
        self.operation_id = operation_id
        self.limits = limits
        self.metrics = ResourceMetrics()
        self.temp_files: Set[str] = set()
        self.start_time = time.time()
        self._monitoring = False
        self._monitor_task: Optional[asyncio.Task] = None
    
    async def start_monitoring(self) -> None:
        """Start resource monitoring for this operation."""
        if self._monitoring:
            return
        
        self._monitoring = True
        self._monitor_task = asyncio.create_task(self._monitor_resources())
        logger.debug(f"Started resource monitoring for operation {self.operation_id}")
    
    async def stop_monitoring(self) -> ResourceMetrics:
        """Stop resource monitoring and return final metrics."""
        self._monitoring = False
        
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        
        self.metrics.finalize()
        logger.debug(f"Stopped resource monitoring for operation {self.operation_id}")
        return self.metrics
    
    def add_temp_file(self, file_path: str) -> None:
        """Register a temporary file for cleanup."""
        self.temp_files.add(file_path)
        self.metrics.temp_files_created.append(file_path)
        
        if len(self.temp_files) > self.limits.max_temp_files:
            logger.warning(
                f"Operation {self.operation_id} exceeded temp file limit: "
                f"{len(self.temp_files)} > {self.limits.max_temp_files}"
            )
    
    def remove_temp_file(self, file_path: str) -> None:
        """Unregister a temporary file (when cleaned up)."""
        self.temp_files.discard(file_path)
    
    async def cleanup_temp_files(self) -> int:
        """Clean up all registered temporary files."""
        cleaned_count = 0
        
        for file_path in list(self.temp_files):
            try:
                if os.path.exists(file_path):
                    os.unlink(file_path)
                    cleaned_count += 1
                    logger.debug(f"Cleaned up temp file: {file_path}")
                self.remove_temp_file(file_path)
            except Exception as e:
                logger.error(f"Failed to clean up temp file {file_path}: {e}")
        
        return cleaned_count
    
    async def _monitor_resources(self) -> None:
        """Monitor resource usage periodically."""
        try:
            process = psutil.Process(os.getpid())
            
            while self._monitoring:
                try:
                    # Get current resource usage
                    memory_info = process.memory_info()
                    current_memory_mb = memory_info.rss / (1024 * 1024)
                    cpu_percent = process.cpu_percent()
                    
                    # Update metrics
                    self.metrics.memory_usage_mb = current_memory_mb
                    self.metrics.cpu_usage_percent = cpu_percent
                    self.metrics.update_peak_memory(current_memory_mb)
                    
                    # Check limits
                    await self._check_resource_limits(current_memory_mb)
                    
                    # Wait before next check
                    await asyncio.sleep(1.0)  # Check every second
                    
                except Exception as e:
                    logger.error(f"Error monitoring resources for {self.operation_id}: {e}")
                    await asyncio.sleep(5.0)  # Wait longer on error
                    
        except asyncio.CancelledError:
            logger.debug(f"Resource monitoring cancelled for {self.operation_id}")
        except Exception as e:
            logger.error(f"Resource monitoring failed for {self.operation_id}: {e}")
    
    async def _check_resource_limits(self, current_memory_mb: float) -> None:
        """Check if resource limits are exceeded."""
        # Check memory limit
        if current_memory_mb > self.limits.max_memory_mb:
            logger.warning(
                f"Operation {self.operation_id} exceeded memory limit: "
                f"{current_memory_mb:.1f}MB > {self.limits.max_memory_mb}MB"
            )
        
        # Check processing time limit
        elapsed_time = time.time() - self.start_time
        if elapsed_time > self.limits.max_processing_time_seconds:
            logger.warning(
                f"Operation {self.operation_id} exceeded time limit: "
                f"{elapsed_time:.1f}s > {self.limits.max_processing_time_seconds}s"
            )


class ResourceManager:
    """
    Manages resources for file processing operations.
    
    Features:
    - Automatic cleanup of temporary files after processing
    - Memory usage monitoring during file processing
    - Resource usage tracking for file upload operations
    - Concurrent operation limits
    """
    
    def __init__(self, limits: Optional[ResourceLimits] = None):
        self.limits = limits or ResourceLimits()
        self.active_operations: Dict[str, ResourceTracker] = {}
        self.operation_counter = 0
        self._lock = threading.Lock()
        
        # Weak reference cleanup for abandoned operations
        self._cleanup_refs: Set[weakref.ref] = set()
    
    @asynccontextmanager
    async def track_operation(self, operation_name: str = "file_processing"):
        """
        Context manager for tracking a file processing operation.
        
        Usage:
            async with resource_manager.track_operation("upload_processing") as tracker:
                # Process file
                tracker.add_temp_file("/tmp/somefile")
                # ... processing logic ...
                # Temp files are automatically cleaned up on exit
        """
        # Check concurrent operation limit
        if len(self.active_operations) >= self.limits.max_concurrent_operations:
            raise RuntimeError(
                f"Maximum concurrent operations limit reached: {self.limits.max_concurrent_operations}"
            )
        
        # Create operation tracker
        with self._lock:
            self.operation_counter += 1
            operation_id = f"{operation_name}_{self.operation_counter}_{int(time.time())}"
        
        tracker = ResourceTracker(operation_id, self.limits)
        self.active_operations[operation_id] = tracker
        
        try:
            # Start monitoring
            await tracker.start_monitoring()
            logger.info(f"Started tracking operation: {operation_id}")
            
            yield tracker
            
        except Exception as e:
            logger.error(f"Error in tracked operation {operation_id}: {e}")
            raise
        finally:
            # Stop monitoring and cleanup
            try:
                metrics = await tracker.stop_monitoring()
                cleaned_files = await tracker.cleanup_temp_files()
                
                logger.info(
                    f"Completed operation {operation_id}: "
                    f"processed in {metrics.processing_time_ms:.1f}ms, "
                    f"peak memory {metrics.peak_memory_mb:.1f}MB, "
                    f"cleaned {cleaned_files} temp files"
                )
                
            except Exception as e:
                logger.error(f"Error cleaning up operation {operation_id}: {e}")
            finally:
                # Remove from active operations
                self.active_operations.pop(operation_id, None)
    
    def get_active_operations(self) -> Dict[str, Dict[str, Any]]:
        """Get information about currently active operations."""
        operations = {}
        
        for op_id, tracker in self.active_operations.items():
            operations[op_id] = {
                "operation_id": op_id,
                "start_time": tracker.start_time,
                "elapsed_seconds": time.time() - tracker.start_time,
                "temp_files_count": len(tracker.temp_files),
                "current_memory_mb": tracker.metrics.memory_usage_mb,
                "peak_memory_mb": tracker.metrics.peak_memory_mb,
                "cpu_percent": tracker.metrics.cpu_usage_percent
            }
        
        return operations
    
    def get_system_resource_info(self) -> Dict[str, Any]:
        """Get current system resource information."""
        try:
            # System memory info
            memory = psutil.virtual_memory()
            
            # System CPU info
            cpu_percent = psutil.cpu_percent(interval=1)
            
            # Disk usage for temp directory
            temp_dir = Path.cwd() / "tmp"
            if temp_dir.exists():
                disk_usage = psutil.disk_usage(str(temp_dir))
            else:
                disk_usage = psutil.disk_usage("/tmp")
            
            return {
                "system_memory": {
                    "total_mb": memory.total / (1024 * 1024),
                    "available_mb": memory.available / (1024 * 1024),
                    "used_mb": memory.used / (1024 * 1024),
                    "percent": memory.percent
                },
                "system_cpu": {
                    "percent": cpu_percent,
                    "count": psutil.cpu_count()
                },
                "disk_usage": {
                    "total_gb": disk_usage.total / (1024 * 1024 * 1024),
                    "free_gb": disk_usage.free / (1024 * 1024 * 1024),
                    "used_gb": disk_usage.used / (1024 * 1024 * 1024),
                    "percent": (disk_usage.used / disk_usage.total) * 100
                },
                "active_operations": len(self.active_operations),
                "limits": {
                    "max_memory_mb": self.limits.max_memory_mb,
                    "max_processing_time_seconds": self.limits.max_processing_time_seconds,
                    "max_temp_files": self.limits.max_temp_files,
                    "max_concurrent_operations": self.limits.max_concurrent_operations
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to get system resource info: {e}")
            return {"error": str(e)}
    
    async def cleanup_abandoned_resources(self) -> int:
        """Clean up resources from abandoned operations."""
        cleaned_count = 0
        
        # Find operations that have been running too long
        current_time = time.time()
        abandoned_ops = []
        
        for op_id, tracker in self.active_operations.items():
            elapsed = current_time - tracker.start_time
            if elapsed > self.limits.max_processing_time_seconds * 2:  # 2x the limit
                abandoned_ops.append(op_id)
        
        # Clean up abandoned operations
        for op_id in abandoned_ops:
            try:
                tracker = self.active_operations.get(op_id)
                if tracker:
                    cleaned_files = await tracker.cleanup_temp_files()
                    cleaned_count += cleaned_files
                    await tracker.stop_monitoring()
                    self.active_operations.pop(op_id, None)
                    logger.warning(f"Cleaned up abandoned operation: {op_id}")
            except Exception as e:
                logger.error(f"Failed to clean up abandoned operation {op_id}: {e}")
        
        return cleaned_count
    
    def update_limits(self, new_limits: ResourceLimits) -> None:
        """Update resource limits."""
        self.limits = new_limits
        logger.info(f"Updated resource limits: {new_limits}")


# Global resource manager instance
_resource_manager: Optional[ResourceManager] = None


def get_resource_manager() -> ResourceManager:
    """Get or create global resource manager instance."""
    global _resource_manager
    if _resource_manager is None:
        _resource_manager = ResourceManager()
    return _resource_manager


async def cleanup_temp_files(file_paths: List[str]) -> int:
    """
    Convenience function to clean up temporary files.
    
    Args:
        file_paths: List of file paths to clean up
        
    Returns:
        Number of files successfully cleaned up
    """
    cleaned_count = 0
    
    for file_path in file_paths:
        try:
            if os.path.exists(file_path):
                os.unlink(file_path)
                cleaned_count += 1
                logger.debug(f"Cleaned up temp file: {file_path}")
        except Exception as e:
            logger.error(f"Failed to clean up temp file {file_path}: {e}")
    
    return cleaned_count