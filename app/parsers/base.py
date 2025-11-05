"""
Base parser interface and common data structures.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from enum import Enum

from app.validators.validators import SpecFormat


class EndpointMethod(str, Enum):
    """HTTP methods for API endpoints."""
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"


@dataclass
class Parameter:
    """Represents a parameter in an API specification."""
    name: str
    type: str
    description: Optional[str] = None
    required: bool = False
    location: Optional[str] = None  # query, path, header, body
    example: Optional[Any] = None
    enum_values: Optional[List[str]] = None


@dataclass
class Response:
    """Represents a response in an API specification."""
    status_code: str
    description: Optional[str] = None
    content_type: Optional[str] = None
    schema: Optional[Dict[str, Any]] = None
    examples: Optional[Dict[str, Any]] = None


@dataclass
class Endpoint:
    """Represents an API endpoint."""
    path: str
    method: EndpointMethod
    summary: Optional[str] = None
    description: Optional[str] = None
    parameters: List[Parameter] = field(default_factory=list)
    responses: List[Response] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    operation_id: Optional[str] = None


@dataclass
class Schema:
    """Represents a data schema/model."""
    name: str
    type: str
    description: Optional[str] = None
    properties: Dict[str, Any] = field(default_factory=dict)
    required_fields: List[str] = field(default_factory=list)
    example: Optional[Dict[str, Any]] = None


@dataclass
class ParsedSpecification:
    """
    Normalized representation of a parsed specification.
    This is the common internal format that all parsers produce.
    """
    format: SpecFormat
    title: str
    version: str
    description: Optional[str] = None
    base_url: Optional[str] = None
    
    # API structure
    endpoints: List[Endpoint] = field(default_factory=list)
    schemas: List[Schema] = field(default_factory=list)
    
    # Metadata
    tags: List[Dict[str, str]] = field(default_factory=list)
    servers: List[Dict[str, str]] = field(default_factory=list)
    
    # Raw specification for reference
    raw_spec: Optional[Dict[str, Any]] = None


class BaseParser(ABC):
    """Abstract base class for specification parsers."""
    
    @abstractmethod
    def parse(self, spec_content: str | Dict[str, Any]) -> ParsedSpecification:
        """
        Parse specification content into normalized format.
        
        Args:
            spec_content: Raw specification content
            
        Returns:
            ParsedSpecification: Normalized specification data
            
        Raises:
            ParseError: If parsing fails
        """
        pass
    
    @abstractmethod
    def get_supported_format(self) -> SpecFormat:
        """Return the specification format this parser supports."""
        pass
    
    def _parse_content(self, content: str | Dict[str, Any]) -> Dict[str, Any]:
        """Parse string content to dictionary if needed."""
        if isinstance(content, dict):
            return content
        
        import json
        import yaml
        
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            try:
                return yaml.safe_load(content)
            except yaml.YAMLError as e:
                raise ParseError(f"Failed to parse content: {e}")


class ParseError(Exception):
    """Exception raised when parsing fails."""
    pass