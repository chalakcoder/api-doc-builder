"""
Robust file upload handler with streaming processing and comprehensive validation.
"""
import asyncio
import tempfile
import os
import hashlib
import time
from typing import Optional, Dict, Any, List, AsyncGenerator, Tuple
from pathlib import Path
from dataclasses import dataclass
from enum import Enum
import aiofiles

from fastapi import UploadFile
from pydantic import BaseModel

from app.validators.format_detector import FormatDetector
from app.validators.validators import SpecificationValidator, ValidationResult
from app.core.exceptions import ValidationError, SpecificationError
from app.core.logging import get_logger, EnhancedLoggerMixin, get_correlation_id
from app.services.error_pattern_tracker import track_error_pattern

logger = get_logger(__name__)


class FileValidationError(Exception):
    """Exception raised for file validation errors."""
    
    def __init__(self, message: str, field: str = "file", details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.field = field
        self.details = details or {}


@dataclass
class FileInfo:
    """Information about an uploaded file."""
    filename: str
    size: int
    content_type: str
    checksum: str
    temp_path: Optional[str] = None


@dataclass
class ProcessedFile:
    """Result of file processing."""
    file_info: FileInfo
    content: str
    detected_format: str
    validation_result: ValidationResult
    temp_files: List[str]


class FileUploadConfig:
    """Configuration for file upload processing."""
    
    # File size limits (in bytes)
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
    CHUNK_SIZE = 8192  # 8KB chunks for streaming
    
    # Supported file extensions
    SUPPORTED_EXTENSIONS = {'.json', '.yaml', '.yml', '.graphql', '.gql', '.txt'}
    
    # Content type validation
    ALLOWED_CONTENT_TYPES = {
        'application/json',
        'application/x-yaml',
        'text/yaml',
        'text/plain',
        'application/octet-stream',  # For files without specific MIME type
        'text/x-yaml'
    }


class RobustFileHandler(EnhancedLoggerMixin):
    """
    Robust file upload handler with streaming processing and comprehensive validation.
    
    Features:
    - Streaming file processing to prevent memory issues
    - Comprehensive file format validation
    - File size and content validation with specific error messages
    - Automatic temporary file cleanup
    - Memory usage monitoring
    - Enhanced logging and error pattern tracking
    """
    
    def __init__(self, config: Optional[FileUploadConfig] = None):
        """Initialize the file handler with configuration."""
        self.config = config or FileUploadConfig()
        self.format_detector = FormatDetector()
        self.validator = SpecificationValidator()
        self.temp_files: List[str] = []
    
    async def process_upload_stream(self, file: UploadFile) -> ProcessedFile:
        """
        Process uploaded file with streaming to handle large files efficiently.
        
        Args:
            file: FastAPI UploadFile object
            
        Returns:
            ProcessedFile with validation results and file info
            
        Raises:
            FileValidationError: If file validation fails
            SpecificationError: If specification validation fails
        """
        start_time = time.time()
        correlation_id = get_correlation_id()
        
        self.log_operation_start(
            "file_upload_processing",
            filename=file.filename,
            content_type=file.content_type,
            correlation_id=correlation_id
        )
        
        try:
            # Validate file metadata first
            await self._validate_file_metadata(file)
            
            # Create temporary file for streaming
            temp_file_path = await self._create_temp_file()
            self.temp_files.append(temp_file_path)
            
            # Stream file content to temporary file with validation
            file_info = await self._stream_file_content(file, temp_file_path)
            
            # Read and validate file content
            content = await self._read_file_content(temp_file_path)
            
            # Detect format and validate specification
            detected_format = self._detect_file_format(content, file_info.filename)
            validation_result = self._validate_specification_content(content, detected_format)
            
            # Log successful processing
            duration_ms = (time.time() - start_time) * 1000
            self.log_operation_success(
                "file_upload_processing",
                duration_ms=duration_ms,
                file_size_bytes=file_info.size,
                detected_format=detected_format.value if detected_format else "unknown",
                validation_passed=validation_result.is_valid if validation_result else False
            )
            
            return ProcessedFile(
                file_info=file_info,
                content=content,
                detected_format=detected_format.value if detected_format else "unknown",
                validation_result=validation_result,
                temp_files=self.temp_files.copy()
            )
            
        except Exception as e:
            # Log error and track pattern
            duration_ms = (time.time() - start_time) * 1000
            self.log_operation_error(
                "file_upload_processing",
                e,
                duration_ms=duration_ms,
                filename=file.filename,
                content_type=file.content_type
            )
            
            # Track error pattern
            error_code = "FILE_PROCESSING_ERROR"
            if isinstance(e, FileValidationError):
                error_code = "FILE_VALIDATION_ERROR"
            elif isinstance(e, SpecificationError):
                error_code = "SPECIFICATION_ERROR"
            
            track_error_pattern(
                error_type=type(e).__name__,
                endpoint="/generate-docs/file",  # Assuming this is the main endpoint
                error_code=error_code,
                correlation_id=correlation_id,
                additional_context={
                    "filename": file.filename,
                    "content_type": file.content_type,
                    "file_size": getattr(file, 'size', 0),
                    "processing_duration_ms": duration_ms
                }
            )
            
            # Clean up temp files on error
            await self.cleanup_temp_resources(self.temp_files)
            raise
    
    async def _validate_file_metadata(self, file: UploadFile) -> None:
        """Validate file metadata before processing."""
        # Check filename
        if not file.filename:
            raise FileValidationError(
                message="Filename is required",
                field="filename",
                details={"retry_guidance": "Ensure the uploaded file has a valid filename"}
            )
        
        # Check file extension
        file_path = Path(file.filename.lower())
        if file_path.suffix not in self.config.SUPPORTED_EXTENSIONS:
            raise FileValidationError(
                message=f"Unsupported file extension: {file_path.suffix}",
                field="filename",
                details={
                    "provided_extension": file_path.suffix,
                    "supported_extensions": list(self.config.SUPPORTED_EXTENSIONS),
                    "retry_guidance": "Upload a file with a supported extension"
                }
            )
        
        # Check content type if available
        if file.content_type and file.content_type not in self.config.ALLOWED_CONTENT_TYPES:
            logger.warning(f"Unexpected content type: {file.content_type} for file {file.filename}")
            # Don't fail on content type mismatch, just log warning
        
        # Check file size if available
        if hasattr(file, 'size') and file.size is not None:
            if file.size > self.config.MAX_FILE_SIZE:
                raise FileValidationError(
                    message=f"File size exceeds maximum limit of {self.config.MAX_FILE_SIZE // (1024*1024)}MB",
                    field="file_size",
                    details={
                        "file_size": file.size,
                        "max_size": self.config.MAX_FILE_SIZE,
                        "retry_guidance": f"Upload a file smaller than {self.config.MAX_FILE_SIZE // (1024*1024)}MB"
                    }
                )
    
    async def _create_temp_file(self) -> str:
        """Create a temporary file for streaming."""
        temp_fd, temp_path = tempfile.mkstemp(suffix='.tmp', prefix='upload_')
        os.close(temp_fd)  # Close the file descriptor, we'll use aiofiles
        return temp_path
    
    async def _stream_file_content(self, file: UploadFile, temp_path: str) -> FileInfo:
        """Stream file content to temporary file with size validation."""
        total_size = 0
        hasher = hashlib.sha256()
        
        try:
            async with aiofiles.open(temp_path, 'wb') as temp_file:
                while True:
                    chunk = await file.read(self.config.CHUNK_SIZE)
                    if not chunk:
                        break
                    
                    # Check size limit during streaming
                    total_size += len(chunk)
                    if total_size > self.config.MAX_FILE_SIZE:
                        raise FileValidationError(
                            message=f"File size exceeds maximum limit of {self.config.MAX_FILE_SIZE // (1024*1024)}MB",
                            field="file_size",
                            details={
                                "file_size": total_size,
                                "max_size": self.config.MAX_FILE_SIZE,
                                "retry_guidance": f"Upload a file smaller than {self.config.MAX_FILE_SIZE // (1024*1024)}MB"
                            }
                        )
                    
                    # Write chunk and update hash
                    await temp_file.write(chunk)
                    hasher.update(chunk)
            
            # Validate minimum file size
            if total_size == 0:
                raise FileValidationError(
                    message="File is empty",
                    field="file_size",
                    details={"retry_guidance": "Upload a file with content"}
                )
            
            return FileInfo(
                filename=file.filename,
                size=total_size,
                content_type=file.content_type or "application/octet-stream",
                checksum=hasher.hexdigest(),
                temp_path=temp_path
            )
            
        except Exception as e:
            # Clean up temp file on error
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise
    
    async def _read_file_content(self, temp_path: str) -> str:
        """Read file content from temporary file."""
        try:
            async with aiofiles.open(temp_path, 'r', encoding='utf-8') as f:
                return await f.read()
        except UnicodeDecodeError as e:
            raise FileValidationError(
                message="File contains invalid UTF-8 characters",
                field="file_content",
                details={
                    "encoding_error": str(e),
                    "retry_guidance": "Ensure the file is saved with UTF-8 encoding"
                }
            )
        except Exception as e:
            raise FileValidationError(
                message=f"Failed to read file content: {str(e)}",
                field="file_content",
                details={"retry_guidance": "Ensure the file is not corrupted"}
            )
    
    def _detect_file_format(self, content: str, filename: str) -> Optional[Any]:
        """Detect file format using format detector."""
        try:
            detected_format = self.format_detector.detect_format(
                content=content,
                filename=filename
            )
            
            if not detected_format:
                raise SpecificationError(
                    message="Unable to detect specification format",
                    details={
                        "filename": filename,
                        "supported_formats": ["OpenAPI", "GraphQL", "JSON Schema"],
                        "retry_guidance": "Ensure the file contains a valid specification in a supported format"
                    }
                )
            
            return detected_format
            
        except Exception as e:
            logger.error(f"Format detection failed for {filename}: {e}")
            raise SpecificationError(
                message=f"Format detection failed: {str(e)}",
                details={
                    "filename": filename,
                    "retry_guidance": "Verify the file contains a valid specification"
                }
            )
    
    def _validate_specification_content(self, content: str, detected_format: Any) -> ValidationResult:
        """Validate specification content using the appropriate validator."""
        try:
            validation_result = self.validator.validate_specification(
                content=content,
                spec_format=detected_format
            )
            
            if not validation_result.is_valid:
                raise SpecificationError(
                    message=f"Specification validation failed: {'; '.join(validation_result.errors)}",
                    spec_format=detected_format.value,
                    details={
                        "validation_errors": validation_result.errors,
                        "warnings": validation_result.warnings,
                        "retry_guidance": "Fix the specification errors and try again"
                    }
                )
            
            return validation_result
            
        except SpecificationError:
            raise
        except Exception as e:
            logger.error(f"Specification validation failed: {e}")
            raise SpecificationError(
                message=f"Specification validation failed: {str(e)}",
                spec_format=detected_format.value if detected_format else "unknown",
                details={"retry_guidance": "Verify the specification syntax is correct"}
            )
    
    async def cleanup_temp_resources(self, file_paths: List[str]) -> None:
        """Clean up temporary files."""
        for file_path in file_paths:
            try:
                if os.path.exists(file_path):
                    os.unlink(file_path)
                    logger.debug(f"Cleaned up temporary file: {file_path}")
            except Exception as e:
                logger.error(f"Failed to clean up temporary file {file_path}: {e}")
        
        # Clear the temp files list
        self.temp_files.clear()
    
    def get_memory_usage_info(self) -> Dict[str, Any]:
        """Get current memory usage information for monitoring."""
        import psutil
        import os
        
        try:
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()
            
            return {
                "rss_mb": memory_info.rss / (1024 * 1024),  # Resident Set Size
                "vms_mb": memory_info.vms / (1024 * 1024),  # Virtual Memory Size
                "percent": process.memory_percent(),
                "temp_files_count": len(self.temp_files),
                "temp_files_paths": self.temp_files.copy()
            }
        except Exception as e:
            logger.warning(f"Failed to get memory usage info: {e}")
            return {
                "error": str(e),
                "temp_files_count": len(self.temp_files)
            }


# Global file handler instance
_file_handler: Optional[RobustFileHandler] = None


def get_file_handler() -> RobustFileHandler:
    """Get or create global file handler instance."""
    global _file_handler
    if _file_handler is None:
        _file_handler = RobustFileHandler()
    return _file_handler


async def process_uploaded_file(file: UploadFile) -> ProcessedFile:
    """
    Convenience function to process an uploaded file.
    
    Args:
        file: FastAPI UploadFile object
        
    Returns:
        ProcessedFile with validation results
    """
    handler = get_file_handler()
    return await handler.process_upload_stream(file)