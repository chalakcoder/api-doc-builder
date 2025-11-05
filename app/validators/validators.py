"""
Specification validators for different formats.
"""
import json
import yaml
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum

import jsonschema
from openapi_spec_validator import validate_spec
from openapi_spec_validator.exceptions import OpenAPISpecValidatorError
from graphql import build_schema, GraphQLError


class SpecFormat(str, Enum):
    """Supported specification formats."""
    OPENAPI = "openapi"
    GRAPHQL = "graphql"
    JSON_SCHEMA = "json_schema"


@dataclass
class ValidationResult:
    """Result of specification validation."""
    is_valid: bool
    format: Optional[SpecFormat] = None
    errors: List[str] = None
    warnings: List[str] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.warnings is None:
            self.warnings = []


class ValidationError(Exception):
    """Custom validation error."""
    
    def __init__(self, message: str, errors: List[str] = None):
        super().__init__(message)
        self.errors = errors or []


class BaseValidator:
    """Base class for specification validators."""
    
    def validate(self, spec_content: str | Dict[str, Any]) -> ValidationResult:
        """Validate specification content."""
        raise NotImplementedError
    
    def _parse_content(self, content: str | Dict[str, Any]) -> Dict[str, Any]:
        """Parse string content to dictionary."""
        if isinstance(content, dict):
            return content
        
        try:
            # Try JSON first
            return json.loads(content)
        except json.JSONDecodeError:
            try:
                # Try YAML
                return yaml.safe_load(content)
            except yaml.YAMLError as e:
                raise ValidationError(f"Failed to parse content as JSON or YAML: {e}")


class OpenAPIValidator(BaseValidator):
    """Validator for OpenAPI specifications."""
    
    def validate(self, spec_content: str | Dict[str, Any]) -> ValidationResult:
        """Validate OpenAPI specification."""
        try:
            spec_dict = self._parse_content(spec_content)
            
            # Check for OpenAPI version field
            if "openapi" not in spec_dict and "swagger" not in spec_dict:
                return ValidationResult(
                    is_valid=False,
                    errors=["Missing 'openapi' or 'swagger' version field"]
                )
            
            # Validate using openapi-spec-validator
            validate_spec(spec_dict)
            
            return ValidationResult(
                is_valid=True,
                format=SpecFormat.OPENAPI
            )
            
        except OpenAPISpecValidatorError as e:
            return ValidationResult(
                is_valid=False,
                errors=[str(e)]
            )
        except ValidationError:
            raise
        except Exception as e:
            return ValidationResult(
                is_valid=False,
                errors=[f"OpenAPI validation failed: {e}"]
            )


class GraphQLValidator(BaseValidator):
    """Validator for GraphQL schemas."""
    
    def validate(self, spec_content: str | Dict[str, Any]) -> ValidationResult:
        """Validate GraphQL schema."""
        try:
            # GraphQL schemas are typically strings, not JSON/YAML
            if isinstance(spec_content, dict):
                # If it's a dict, look for common GraphQL schema fields
                if "schema" in spec_content:
                    schema_content = spec_content["schema"]
                elif "data" in spec_content:
                    schema_content = spec_content["data"]
                else:
                    return ValidationResult(
                        is_valid=False,
                        errors=["GraphQL schema not found in provided structure"]
                    )
            else:
                schema_content = spec_content
            
            # Validate by building the schema
            build_schema(schema_content)
            
            return ValidationResult(
                is_valid=True,
                format=SpecFormat.GRAPHQL
            )
            
        except GraphQLError as e:
            return ValidationResult(
                is_valid=False,
                errors=[f"GraphQL validation error: {e}"]
            )
        except Exception as e:
            return ValidationResult(
                is_valid=False,
                errors=[f"GraphQL validation failed: {e}"]
            )


class JSONSchemaValidator(BaseValidator):
    """Validator for JSON Schema specifications."""
    
    def validate(self, spec_content: str | Dict[str, Any]) -> ValidationResult:
        """Validate JSON Schema."""
        try:
            spec_dict = self._parse_content(spec_content)
            
            # Check for JSON Schema indicators
            schema_indicators = ["$schema", "type", "properties", "definitions"]
            if not any(indicator in spec_dict for indicator in schema_indicators):
                return ValidationResult(
                    is_valid=False,
                    errors=["No JSON Schema indicators found (missing $schema, type, properties, or definitions)"]
                )
            
            # Validate the schema itself
            jsonschema.validators.validator_for(spec_dict).check_schema(spec_dict)
            
            return ValidationResult(
                is_valid=True,
                format=SpecFormat.JSON_SCHEMA
            )
            
        except jsonschema.SchemaError as e:
            return ValidationResult(
                is_valid=False,
                errors=[f"JSON Schema validation error: {e}"]
            )
        except ValidationError:
            raise
        except Exception as e:
            return ValidationResult(
                is_valid=False,
                errors=[f"JSON Schema validation failed: {e}"]
            )


class SpecificationValidator:
    """
    Main validator that combines all format-specific validators.
    
    This class provides a unified interface for validating specifications
    of different formats (OpenAPI, GraphQL, JSON Schema).
    """
    
    def __init__(self):
        """Initialize with all available validators."""
        self.validators = {
            SpecFormat.OPENAPI: OpenAPIValidator(),
            SpecFormat.GRAPHQL: GraphQLValidator(),
            SpecFormat.JSON_SCHEMA: JSONSchemaValidator(),
        }
    
    def validate_specification(
        self, 
        content: str | Dict[str, Any], 
        spec_format: SpecFormat
    ) -> ValidationResult:
        """
        Validate specification content using the appropriate validator.
        
        Args:
            content: Specification content (string or dict)
            spec_format: Expected format of the specification
            
        Returns:
            ValidationResult with validation status and details
            
        Raises:
            ValidationError: If the format is not supported
        """
        if spec_format not in self.validators:
            raise ValidationError(f"Unsupported specification format: {spec_format}")
        
        validator = self.validators[spec_format]
        result = validator.validate(content)
        
        # Ensure the format is set in the result
        if result.is_valid and result.format is None:
            result.format = spec_format
            
        return result
    
    def auto_validate(self, content: str | Dict[str, Any]) -> ValidationResult:
        """
        Automatically detect format and validate specification.
        
        Args:
            content: Specification content
            
        Returns:
            ValidationResult with detected format and validation status
        """
        # Try each validator and return the first successful one
        for spec_format, validator in self.validators.items():
            try:
                result = validator.validate(content)
                if result.is_valid:
                    result.format = spec_format
                    return result
            except Exception:
                # Continue to next validator if this one fails
                continue
        
        # If no validator succeeded, return a failure result
        return ValidationResult(
            is_valid=False,
            errors=["Unable to validate as any supported format (OpenAPI, GraphQL, JSON Schema)"]
        )
    
    def get_supported_formats(self) -> List[SpecFormat]:
        """Get list of supported specification formats."""
        return list(self.validators.keys())