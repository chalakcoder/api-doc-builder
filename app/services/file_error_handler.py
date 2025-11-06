"""
Enhanced error handling for file upload and processing operations.
"""
import logging
import traceback
from typing import Dict, Any, List, Optional, Union
from enum import Enum
from dataclasses import dataclass
import json

from fastapi import HTTPException
from pydantic import BaseModel

from app.core.exceptions import ValidationError, SpecificationError

logger = logging.getLogger(__name__)


class FileErrorType(str, Enum):
    """Types of file processing errors."""
    VALIDATION_ERROR = "validation_error"
    FORMAT_ERROR = "format_error"
    SIZE_ERROR = "size_error"
    ENCODING_ERROR = "encoding_error"
    PARSING_ERROR = "parsing_error"
    SPECIFICATION_ERROR = "specification_error"
    RESOURCE_ERROR = "resource_error"
    SYSTEM_ERROR = "system_error"


class FileErrorSeverity(str, Enum):
    """Severity levels for file processing errors."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class FileErrorDetail:
    """Detailed information about a file processing error."""
    error_type: FileErrorType
    severity: FileErrorSeverity
    message: str
    field: Optional[str] = None
    line_number: Optional[int] = None
    column_number: Optional[int] = None
    context: Optional[Dict[str, Any]] = None
    suggestions: Optional[List[str]] = None


class FileErrorResponse(BaseModel):
    """Standardized error response for file processing errors."""
    error: str
    error_type: str
    severity: str
    message: str
    details: Dict[str, Any]
    field: Optional[str] = None
    retry_guidance: Optional[str] = None
    suggestions: Optional[List[str]] = None
    correlation_id: Optional[str] = None


class FileUploadErrorHandler:
    """
    Enhanced error handler for file upload and processing operations.
    
    Features:
    - Specific error messages for different file validation failures
    - Proper error handling for malformed file content
    - Detailed parsing error reporting for specification files
    - Error categorization and severity assessment
    """
    
    def __init__(self):
        self.error_patterns = self._initialize_error_patterns()
    
    def handle_file_validation_error(
        self, 
        error: Exception, 
        filename: Optional[str] = None,
        correlation_id: Optional[str] = None
    ) -> FileErrorResponse:
        """
        Handle file validation errors with specific error messages.
        
        Args:
            error: The exception that occurred
            filename: Name of the file being processed
            correlation_id: Request correlation ID for tracing
            
        Returns:
            Standardized error response
        """
        error_detail = self._analyze_error(error, filename)
        
        return FileErrorResponse(
            error="file_validation_failed",
            error_type=error_detail.error_type.value,
            severity=error_detail.severity.value,
            message=error_detail.message,
            details=self._build_error_details(error_detail, filename),
            field=error_detail.field,
            retry_guidance=self._get_retry_guidance(error_detail),
            suggestions=error_detail.suggestions,
            correlation_id=correlation_id
        )
    
    def handle_parsing_error(
        self, 
        error: Exception, 
        content: Optional[str] = None,
        filename: Optional[str] = None,
        correlation_id: Optional[str] = None
    ) -> FileErrorResponse:
        """
        Handle parsing errors with detailed error reporting.
        
        Args:
            error: The parsing exception
            content: File content that failed to parse
            filename: Name of the file being parsed
            correlation_id: Request correlation ID
            
        Returns:
            Detailed parsing error response
        """
        error_detail = self._analyze_parsing_error(error, content, filename)
        
        return FileErrorResponse(
            error="parsing_failed",
            error_type=error_detail.error_type.value,
            severity=error_detail.severity.value,
            message=error_detail.message,
            details=self._build_parsing_error_details(error_detail, content, filename),
            field=error_detail.field,
            retry_guidance=self._get_parsing_retry_guidance(error_detail),
            suggestions=error_detail.suggestions,
            correlation_id=correlation_id
        )
    
    def handle_specification_error(
        self, 
        error: SpecificationError,
        correlation_id: Optional[str] = None
    ) -> FileErrorResponse:
        """
        Handle specification validation errors with detailed feedback.
        
        Args:
            error: The specification error
            correlation_id: Request correlation ID
            
        Returns:
            Detailed specification error response
        """
        error_detail = self._analyze_specification_error(error)
        
        return FileErrorResponse(
            error="specification_validation_failed",
            error_type=error_detail.error_type.value,
            severity=error_detail.severity.value,
            message=error_detail.message,
            details=self._build_specification_error_details(error_detail, error),
            field=error_detail.field,
            retry_guidance=self._get_specification_retry_guidance(error_detail, error),
            suggestions=error_detail.suggestions,
            correlation_id=correlation_id
        )
    
    def handle_resource_error(
        self, 
        error: Exception,
        resource_info: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None
    ) -> FileErrorResponse:
        """
        Handle resource-related errors (memory, disk, etc.).
        
        Args:
            error: The resource error
            resource_info: Current resource usage information
            correlation_id: Request correlation ID
            
        Returns:
            Resource error response with guidance
        """
        error_detail = self._analyze_resource_error(error, resource_info)
        
        return FileErrorResponse(
            error="resource_error",
            error_type=error_detail.error_type.value,
            severity=error_detail.severity.value,
            message=error_detail.message,
            details=self._build_resource_error_details(error_detail, resource_info),
            retry_guidance=self._get_resource_retry_guidance(error_detail),
            suggestions=error_detail.suggestions,
            correlation_id=correlation_id
        )
    
    def _analyze_error(self, error: Exception, filename: Optional[str]) -> FileErrorDetail:
        """Analyze an error and categorize it."""
        error_str = str(error).lower()
        error_type = type(error).__name__
        
        # File size errors
        if "size" in error_str and ("exceed" in error_str or "limit" in error_str):
            return FileErrorDetail(
                error_type=FileErrorType.SIZE_ERROR,
                severity=FileErrorSeverity.MEDIUM,
                message=str(error),
                field="file_size",
                suggestions=[
                    "Reduce the file size by removing unnecessary content",
                    "Split large specifications into smaller modules",
                    "Compress the file if possible"
                ]
            )
        
        # Encoding errors
        if "encoding" in error_str or "utf-8" in error_str or "unicode" in error_str:
            return FileErrorDetail(
                error_type=FileErrorType.ENCODING_ERROR,
                severity=FileErrorSeverity.HIGH,
                message=str(error),
                field="file_content",
                suggestions=[
                    "Save the file with UTF-8 encoding",
                    "Remove or replace non-UTF-8 characters",
                    "Use a text editor that supports UTF-8"
                ]
            )
        
        # Format detection errors
        if "format" in error_str or "detect" in error_str:
            return FileErrorDetail(
                error_type=FileErrorType.FORMAT_ERROR,
                severity=FileErrorSeverity.HIGH,
                message=str(error),
                suggestions=[
                    "Ensure the file contains a valid OpenAPI, GraphQL, or JSON Schema specification",
                    "Check that the file extension matches the content format",
                    "Verify the specification follows the correct structure"
                ]
            )
        
        # Validation errors
        if isinstance(error, ValidationError) or "validation" in error_str:
            return FileErrorDetail(
                error_type=FileErrorType.VALIDATION_ERROR,
                severity=FileErrorSeverity.MEDIUM,
                message=str(error),
                field=getattr(error, 'field', None),
                suggestions=self._get_validation_suggestions(error_str)
            )
        
        # Default system error
        return FileErrorDetail(
            error_type=FileErrorType.SYSTEM_ERROR,
            severity=FileErrorSeverity.CRITICAL,
            message=f"An unexpected error occurred: {str(error)}",
            suggestions=[
                "Try uploading the file again",
                "Contact support if the problem persists"
            ]
        )
    
    def _analyze_parsing_error(
        self, 
        error: Exception, 
        content: Optional[str], 
        filename: Optional[str]
    ) -> FileErrorDetail:
        """Analyze parsing errors with content context."""
        error_str = str(error).lower()
        
        # JSON parsing errors
        if "json" in error_str:
            line_info = self._extract_line_info_from_json_error(str(error))
            return FileErrorDetail(
                error_type=FileErrorType.PARSING_ERROR,
                severity=FileErrorSeverity.HIGH,
                message=f"JSON parsing failed: {str(error)}",
                field="file_content",
                line_number=line_info.get("line"),
                column_number=line_info.get("column"),
                suggestions=[
                    "Check for missing commas, brackets, or quotes",
                    "Validate JSON syntax using a JSON validator",
                    "Ensure all strings are properly quoted"
                ]
            )
        
        # YAML parsing errors
        if "yaml" in error_str:
            line_info = self._extract_line_info_from_yaml_error(str(error))
            return FileErrorDetail(
                error_type=FileErrorType.PARSING_ERROR,
                severity=FileErrorSeverity.HIGH,
                message=f"YAML parsing failed: {str(error)}",
                field="file_content",
                line_number=line_info.get("line"),
                column_number=line_info.get("column"),
                suggestions=[
                    "Check YAML indentation (use spaces, not tabs)",
                    "Ensure proper YAML syntax",
                    "Validate YAML structure using a YAML validator"
                ]
            )
        
        # GraphQL parsing errors
        if "graphql" in error_str or "schema" in error_str:
            return FileErrorDetail(
                error_type=FileErrorType.PARSING_ERROR,
                severity=FileErrorSeverity.HIGH,
                message=f"GraphQL schema parsing failed: {str(error)}",
                field="file_content",
                suggestions=[
                    "Check GraphQL schema syntax",
                    "Ensure all types are properly defined",
                    "Validate schema using a GraphQL validator"
                ]
            )
        
        return FileErrorDetail(
            error_type=FileErrorType.PARSING_ERROR,
            severity=FileErrorSeverity.HIGH,
            message=f"Failed to parse file content: {str(error)}",
            field="file_content",
            suggestions=[
                "Check file format and syntax",
                "Ensure the file is not corrupted",
                "Try saving the file in a different format"
            ]
        )
    
    def _analyze_specification_error(self, error: SpecificationError) -> FileErrorDetail:
        """Analyze specification validation errors."""
        error_details = getattr(error, 'details', {})
        validation_errors = error_details.get('validation_errors', [])
        
        # Categorize based on validation errors
        if validation_errors:
            error_categories = self._categorize_validation_errors(validation_errors)
            primary_category = max(error_categories.items(), key=lambda x: x[1])[0]
            
            return FileErrorDetail(
                error_type=FileErrorType.SPECIFICATION_ERROR,
                severity=self._get_validation_severity(validation_errors),
                message=str(error),
                field="specification",
                context={"validation_errors": validation_errors},
                suggestions=self._get_specification_suggestions(primary_category, validation_errors)
            )
        
        return FileErrorDetail(
            error_type=FileErrorType.SPECIFICATION_ERROR,
            severity=FileErrorSeverity.HIGH,
            message=str(error),
            field="specification",
            suggestions=[
                "Review the specification format requirements",
                "Check for required fields and proper structure",
                "Validate against the specification schema"
            ]
        )
    
    def _analyze_resource_error(
        self, 
        error: Exception, 
        resource_info: Optional[Dict[str, Any]]
    ) -> FileErrorDetail:
        """Analyze resource-related errors."""
        error_str = str(error).lower()
        
        if "memory" in error_str:
            return FileErrorDetail(
                error_type=FileErrorType.RESOURCE_ERROR,
                severity=FileErrorSeverity.CRITICAL,
                message=f"Memory limit exceeded: {str(error)}",
                context=resource_info,
                suggestions=[
                    "Try uploading a smaller file",
                    "Split large specifications into smaller parts",
                    "Contact support for assistance with large files"
                ]
            )
        
        if "disk" in error_str or "space" in error_str:
            return FileErrorDetail(
                error_type=FileErrorType.RESOURCE_ERROR,
                severity=FileErrorSeverity.CRITICAL,
                message=f"Disk space error: {str(error)}",
                context=resource_info,
                suggestions=[
                    "Try again later when more disk space is available",
                    "Contact support if the problem persists"
                ]
            )
        
        return FileErrorDetail(
            error_type=FileErrorType.RESOURCE_ERROR,
            severity=FileErrorSeverity.HIGH,
            message=f"Resource error: {str(error)}",
            context=resource_info,
            suggestions=[
                "Try the operation again",
                "Contact support if the problem persists"
            ]
        )
    
    def _build_error_details(
        self, 
        error_detail: FileErrorDetail, 
        filename: Optional[str]
    ) -> Dict[str, Any]:
        """Build detailed error information."""
        details = {
            "error_type": error_detail.error_type.value,
            "severity": error_detail.severity.value,
            "timestamp": self._get_timestamp()
        }
        
        if filename:
            details["filename"] = filename
        
        if error_detail.line_number:
            details["line_number"] = error_detail.line_number
        
        if error_detail.column_number:
            details["column_number"] = error_detail.column_number
        
        if error_detail.context:
            details["context"] = error_detail.context
        
        return details
    
    def _build_parsing_error_details(
        self, 
        error_detail: FileErrorDetail, 
        content: Optional[str], 
        filename: Optional[str]
    ) -> Dict[str, Any]:
        """Build detailed parsing error information."""
        details = self._build_error_details(error_detail, filename)
        
        if content and error_detail.line_number:
            # Add context lines around the error
            lines = content.split('\n')
            if 0 <= error_detail.line_number - 1 < len(lines):
                start_line = max(0, error_detail.line_number - 3)
                end_line = min(len(lines), error_detail.line_number + 2)
                
                details["context_lines"] = {
                    "lines": lines[start_line:end_line],
                    "error_line_index": error_detail.line_number - start_line - 1,
                    "start_line_number": start_line + 1
                }
        
        return details
    
    def _build_specification_error_details(
        self, 
        error_detail: FileErrorDetail, 
        error: SpecificationError
    ) -> Dict[str, Any]:
        """Build detailed specification error information."""
        details = {
            "error_type": error_detail.error_type.value,
            "severity": error_detail.severity.value,
            "timestamp": self._get_timestamp()
        }
        
        if hasattr(error, 'spec_format'):
            details["specification_format"] = error.spec_format
        
        if hasattr(error, 'details') and error.details:
            details.update(error.details)
        
        return details
    
    def _build_resource_error_details(
        self, 
        error_detail: FileErrorDetail, 
        resource_info: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Build detailed resource error information."""
        details = {
            "error_type": error_detail.error_type.value,
            "severity": error_detail.severity.value,
            "timestamp": self._get_timestamp()
        }
        
        if resource_info:
            details["resource_usage"] = resource_info
        
        return details
    
    def _get_retry_guidance(self, error_detail: FileErrorDetail) -> str:
        """Get retry guidance based on error type."""
        guidance_map = {
            FileErrorType.SIZE_ERROR: "Reduce file size and try again",
            FileErrorType.ENCODING_ERROR: "Save file with UTF-8 encoding and retry",
            FileErrorType.FORMAT_ERROR: "Ensure file contains a valid specification format",
            FileErrorType.VALIDATION_ERROR: "Fix validation errors and retry",
            FileErrorType.PARSING_ERROR: "Fix syntax errors and retry",
            FileErrorType.SPECIFICATION_ERROR: "Fix specification errors and retry",
            FileErrorType.RESOURCE_ERROR: "Try again later or contact support",
            FileErrorType.SYSTEM_ERROR: "Try again or contact support if problem persists"
        }
        
        return guidance_map.get(error_detail.error_type, "Try again or contact support")
    
    def _get_parsing_retry_guidance(self, error_detail: FileErrorDetail) -> str:
        """Get specific retry guidance for parsing errors."""
        if error_detail.line_number:
            return f"Fix syntax error at line {error_detail.line_number} and retry"
        return "Fix syntax errors and retry"
    
    def _get_specification_retry_guidance(
        self, 
        error_detail: FileErrorDetail, 
        error: SpecificationError
    ) -> str:
        """Get specific retry guidance for specification errors."""
        if hasattr(error, 'details') and error.details.get('validation_errors'):
            error_count = len(error.details['validation_errors'])
            return f"Fix {error_count} validation error(s) and retry"
        return "Fix specification errors and retry"
    
    def _get_resource_retry_guidance(self, error_detail: FileErrorDetail) -> str:
        """Get specific retry guidance for resource errors."""
        if error_detail.error_type == FileErrorType.RESOURCE_ERROR:
            if "memory" in error_detail.message.lower():
                return "Try with a smaller file or contact support"
            elif "disk" in error_detail.message.lower():
                return "Try again later when more disk space is available"
        return "Try again later or contact support"
    
    def _initialize_error_patterns(self) -> Dict[str, Any]:
        """Initialize error pattern matching rules."""
        return {
            "json_errors": [
                "expecting property name",
                "expecting value",
                "invalid control character",
                "unterminated string"
            ],
            "yaml_errors": [
                "mapping values are not allowed",
                "could not find expected",
                "found undefined alias"
            ],
            "openapi_errors": [
                "missing required field",
                "invalid reference",
                "duplicate operationId"
            ]
        }
    
    def _extract_line_info_from_json_error(self, error_str: str) -> Dict[str, Optional[int]]:
        """Extract line and column information from JSON error messages."""
        import re
        
        # Try to extract line and column from error message
        line_match = re.search(r'line (\d+)', error_str)
        column_match = re.search(r'column (\d+)', error_str)
        
        return {
            "line": int(line_match.group(1)) if line_match else None,
            "column": int(column_match.group(1)) if column_match else None
        }
    
    def _extract_line_info_from_yaml_error(self, error_str: str) -> Dict[str, Optional[int]]:
        """Extract line information from YAML error messages."""
        import re
        
        # YAML errors often include line information
        line_match = re.search(r'line (\d+)', error_str)
        
        return {
            "line": int(line_match.group(1)) if line_match else None,
            "column": None
        }
    
    def _get_validation_suggestions(self, error_str: str) -> List[str]:
        """Get validation suggestions based on error message."""
        suggestions = []
        
        if "required" in error_str:
            suggestions.append("Add missing required fields")
        
        if "format" in error_str:
            suggestions.append("Check field format requirements")
        
        if "type" in error_str:
            suggestions.append("Ensure field values have correct data types")
        
        if not suggestions:
            suggestions.append("Review validation requirements and fix errors")
        
        return suggestions
    
    def _categorize_validation_errors(self, validation_errors: List[str]) -> Dict[str, int]:
        """Categorize validation errors by type."""
        categories = {
            "required_fields": 0,
            "format_errors": 0,
            "type_errors": 0,
            "reference_errors": 0,
            "other": 0
        }
        
        for error in validation_errors:
            error_lower = error.lower()
            
            if "required" in error_lower:
                categories["required_fields"] += 1
            elif "format" in error_lower:
                categories["format_errors"] += 1
            elif "type" in error_lower:
                categories["type_errors"] += 1
            elif "reference" in error_lower or "$ref" in error_lower:
                categories["reference_errors"] += 1
            else:
                categories["other"] += 1
        
        return categories
    
    def _get_validation_severity(self, validation_errors: List[str]) -> FileErrorSeverity:
        """Determine severity based on validation errors."""
        if len(validation_errors) > 10:
            return FileErrorSeverity.CRITICAL
        elif len(validation_errors) > 5:
            return FileErrorSeverity.HIGH
        else:
            return FileErrorSeverity.MEDIUM
    
    def _get_specification_suggestions(
        self, 
        primary_category: str, 
        validation_errors: List[str]
    ) -> List[str]:
        """Get suggestions based on specification error category."""
        suggestion_map = {
            "required_fields": [
                "Add missing required fields",
                "Check specification schema for required properties"
            ],
            "format_errors": [
                "Fix field format issues",
                "Ensure values match expected formats"
            ],
            "type_errors": [
                "Fix data type mismatches",
                "Ensure values have correct types"
            ],
            "reference_errors": [
                "Fix broken references",
                "Ensure all $ref values point to valid definitions"
            ],
            "other": [
                "Review specification requirements",
                "Check for syntax and structure errors"
            ]
        }
        
        return suggestion_map.get(primary_category, suggestion_map["other"])
    
    def _get_timestamp(self) -> str:
        """Get current timestamp for error details."""
        from datetime import datetime
        return datetime.utcnow().isoformat() + "Z"


# Global error handler instance
_error_handler: Optional[FileUploadErrorHandler] = None


def get_file_error_handler() -> FileUploadErrorHandler:
    """Get or create global file error handler instance."""
    global _error_handler
    if _error_handler is None:
        _error_handler = FileUploadErrorHandler()
    return _error_handler