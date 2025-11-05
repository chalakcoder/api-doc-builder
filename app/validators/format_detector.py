"""
Specification format detection utilities.
"""
import json
import yaml
from typing import Dict, Any, Optional, Tuple
from pathlib import Path

from .validators import (
    SpecFormat,
    OpenAPIValidator,
    GraphQLValidator, 
    JSONSchemaValidator,
    ValidationResult,
    ValidationError,
)


class SpecificationFormatDetector:
    """Detects and validates specification formats."""
    
    def __init__(self):
        self.validators = {
            SpecFormat.OPENAPI: OpenAPIValidator(),
            SpecFormat.GRAPHQL: GraphQLValidator(),
            SpecFormat.JSON_SCHEMA: JSONSchemaValidator(),
        }
    
    def detect_format_from_filename(self, filename: str) -> Optional[SpecFormat]:
        """Detect format from file extension and name patterns."""
        path = Path(filename.lower())
        
        # Check file extensions
        if path.suffix in ['.yaml', '.yml']:
            # Common OpenAPI file patterns
            if any(pattern in path.name for pattern in ['openapi', 'swagger', 'api']):
                return SpecFormat.OPENAPI
        elif path.suffix == '.json':
            # Could be OpenAPI or JSON Schema
            if any(pattern in path.name for pattern in ['openapi', 'swagger', 'api']):
                return SpecFormat.OPENAPI
            elif any(pattern in path.name for pattern in ['schema', 'json-schema']):
                return SpecFormat.JSON_SCHEMA
        elif path.suffix in ['.graphql', '.gql']:
            return SpecFormat.GRAPHQL
        
        return None
    
    def detect_format_from_content(self, content: str | Dict[str, Any]) -> Tuple[Optional[SpecFormat], ValidationResult]:
        """
        Detect format by analyzing content structure and attempting validation.
        Returns the detected format and validation result for that format.
        """
        # Parse content if it's a string
        try:
            if isinstance(content, str):
                parsed_content = self._parse_content(content)
            else:
                parsed_content = content
        except Exception:
            # If parsing fails, try GraphQL (which expects string content)
            if isinstance(content, str):
                result = self.validators[SpecFormat.GRAPHQL].validate(content)
                if result.is_valid:
                    return SpecFormat.GRAPHQL, result
            
            return None, ValidationResult(
                is_valid=False,
                errors=["Unable to parse content as JSON, YAML, or GraphQL"]
            )
        
        # Try to detect format based on content structure
        detection_order = self._get_detection_order(parsed_content)
        
        for format_type in detection_order:
            validator = self.validators[format_type]
            result = validator.validate(content)
            
            if result.is_valid:
                return format_type, result
        
        # If no format validates successfully, return the most likely format's errors
        primary_format = detection_order[0] if detection_order else SpecFormat.OPENAPI
        primary_result = self.validators[primary_format].validate(content)
        
        return None, primary_result
    
    def validate_specification(self, content: str | Dict[str, Any], 
                             expected_format: Optional[SpecFormat] = None,
                             filename: Optional[str] = None) -> ValidationResult:
        """
        Validate specification with optional format hint.
        
        Args:
            content: Specification content
            expected_format: Expected format (if known)
            filename: Original filename for format detection hints
            
        Returns:
            ValidationResult with format detection and validation details
        """
        detected_format = None
        
        # Try filename-based detection first if provided
        if filename and not expected_format:
            detected_format = self.detect_format_from_filename(filename)
        
        # Use expected format if provided
        if expected_format:
            detected_format = expected_format
        
        # If we have a suspected format, validate against it first
        if detected_format:
            validator = self.validators[detected_format]
            result = validator.validate(content)
            
            if result.is_valid:
                result.format = detected_format
                return result
            else:
                # If expected format fails, try content-based detection
                if expected_format:
                    # Return the validation errors for the expected format
                    result.format = expected_format
                    return result
        
        # Fall back to content-based detection
        detected_format, result = self.detect_format_from_content(content)
        
        if detected_format:
            result.format = detected_format
        
        return result
    
    def _parse_content(self, content: str) -> Dict[str, Any]:
        """Parse string content to dictionary."""
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            try:
                return yaml.safe_load(content)
            except yaml.YAMLError as e:
                raise ValidationError(f"Failed to parse content: {e}")
    
    def _get_detection_order(self, parsed_content: Dict[str, Any]) -> list[SpecFormat]:
        """
        Determine the order to try format validation based on content hints.
        """
        detection_order = []
        
        # Check for OpenAPI indicators
        if any(key in parsed_content for key in ['openapi', 'swagger', 'info', 'paths']):
            detection_order.append(SpecFormat.OPENAPI)
        
        # Check for JSON Schema indicators  
        if any(key in parsed_content for key in ['$schema', 'definitions', 'properties']) and 'paths' not in parsed_content:
            detection_order.append(SpecFormat.JSON_SCHEMA)
        
        # Add remaining formats
        for format_type in SpecFormat:
            if format_type not in detection_order:
                detection_order.append(format_type)
        
        return detection_order


class FormatDetector:
    """
    Simplified format detector interface for backward compatibility.
    
    This class provides a simpler interface that matches the existing usage
    in the API endpoints.
    """
    
    def __init__(self):
        self.detector = SpecificationFormatDetector()
    
    def detect_format(self, content: str, filename: Optional[str] = None, url: Optional[str] = None) -> Optional[SpecFormat]:
        """
        Detect specification format from content.
        
        Args:
            content: Specification content as string
            filename: Optional filename for format hints
            url: Optional URL for format hints
            
        Returns:
            Detected SpecFormat or None if detection fails
        """
        # Try filename-based detection first
        if filename:
            detected = self.detector.detect_format_from_filename(filename)
            if detected:
                return detected
        
        # Try URL-based detection
        if url:
            detected = self.detector.detect_format_from_filename(url)
            if detected:
                return detected
        
        # Fall back to content-based detection
        detected_format, validation_result = self.detector.detect_format_from_content(content)
        return detected_format


# Global format detector instance
format_detector: Optional[FormatDetector] = None


def get_format_detector() -> FormatDetector:
    """
    Get global format detector instance.
    
    Returns:
        Format detector instance
        
    Raises:
        RuntimeError: If detector is not initialized
    """
    if format_detector is None:
        raise RuntimeError("Format detector not initialized")
    return format_detector


def initialize_format_detector() -> None:
    """
    Initialize format detector for application startup.
    
    This function is called during application startup to ensure
    the format detector is properly configured and ready for use.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info("Initializing format detector...")
    
    try:
        global format_detector
        format_detector = FormatDetector()
        
        logger.info("Format detector initialized successfully")
        
    except Exception as e:
        logger.error(f"Failed to initialize format detector: {e}")
        raise