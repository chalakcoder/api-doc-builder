"""
Parser factory for creating appropriate parsers based on specification format.
"""
from typing import Dict, Optional

from .base import BaseParser, ParseError
from .openapi_parser import OpenAPIParser
from .graphql_parser import GraphQLParser
from .json_schema_parser import JSONSchemaParser
from app.validators.validators import SpecFormat


class ParserFactory:
    """Factory for creating specification parsers."""
    
    def __init__(self):
        self._parsers: Dict[SpecFormat, BaseParser] = {
            SpecFormat.OPENAPI: OpenAPIParser(),
            SpecFormat.GRAPHQL: GraphQLParser(),
            SpecFormat.JSON_SCHEMA: JSONSchemaParser(),
        }
    
    def get_parser(self, format_type: SpecFormat) -> BaseParser:
        """
        Get parser for the specified format.
        
        Args:
            format_type: The specification format
            
        Returns:
            BaseParser: Parser instance for the format
            
        Raises:
            ParseError: If format is not supported
        """
        parser = self._parsers.get(format_type)
        if not parser:
            raise ParseError(f"No parser available for format: {format_type}")
        
        return parser
    
    def get_supported_formats(self) -> list[SpecFormat]:
        """Get list of supported specification formats."""
        return list(self._parsers.keys())
    
    def register_parser(self, format_type: SpecFormat, parser: BaseParser) -> None:
        """
        Register a custom parser for a format.
        
        Args:
            format_type: The specification format
            parser: Parser instance
        """
        self._parsers[format_type] = parser


# Global parser factory instance
parser_factory: Optional[ParserFactory] = None


def get_parser_factory() -> ParserFactory:
    """
    Get global parser factory instance.
    
    Returns:
        Parser factory instance
        
    Raises:
        RuntimeError: If factory is not initialized
    """
    if parser_factory is None:
        raise RuntimeError("Parser factory not initialized")
    return parser_factory


def initialize_parser_factory() -> None:
    """
    Initialize parser factory for application startup.
    
    This function is called during application startup to ensure
    the parser factory is properly configured and ready for use.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info("Initializing parser factory...")
    
    try:
        global parser_factory
        parser_factory = ParserFactory()
        
        # Validate that all parsers are available
        supported_formats = parser_factory.get_supported_formats()
        logger.info(f"Parser factory initialized with support for: {[f.value for f in supported_formats]}")
        
    except Exception as e:
        logger.error(f"Failed to initialize parser factory: {e}")
        raise