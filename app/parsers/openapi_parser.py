"""
OpenAPI specification parser.
"""
from typing import Dict, Any, List, Optional

from .base import (
    BaseParser, 
    ParsedSpecification, 
    Endpoint, 
    Parameter, 
    Response, 
    Schema,
    EndpointMethod,
    ParseError
)
from app.validators.validators import SpecFormat


class OpenAPIParser(BaseParser):
    """Parser for OpenAPI specifications."""
    
    def get_supported_format(self) -> SpecFormat:
        """Return OpenAPI format."""
        return SpecFormat.OPENAPI
    
    def parse(self, spec_content: str | Dict[str, Any]) -> ParsedSpecification:
        """Parse OpenAPI specification."""
        try:
            spec_dict = self._parse_content(spec_content)
            
            # Extract basic info
            info = spec_dict.get("info", {})
            title = info.get("title", "Untitled API")
            version = info.get("version", "1.0.0")
            description = info.get("description")
            
            # Extract servers
            servers = self._parse_servers(spec_dict.get("servers", []))
            base_url = servers[0].get("url") if servers else None
            
            # Parse endpoints
            endpoints = self._parse_paths(spec_dict.get("paths", {}))
            
            # Parse schemas/components
            schemas = self._parse_schemas(spec_dict)
            
            # Parse tags
            tags = self._parse_tags(spec_dict.get("tags", []))
            
            return ParsedSpecification(
                format=SpecFormat.OPENAPI,
                title=title,
                version=version,
                description=description,
                base_url=base_url,
                endpoints=endpoints,
                schemas=schemas,
                tags=tags,
                servers=servers,
                raw_spec=spec_dict
            )
            
        except Exception as e:
            raise ParseError(f"Failed to parse OpenAPI specification: {e}")
    
    def _parse_servers(self, servers_data: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """Parse server information."""
        servers = []
        for server in servers_data:
            servers.append({
                "url": server.get("url", ""),
                "description": server.get("description", "")
            })
        return servers
    
    def _parse_paths(self, paths_data: Dict[str, Any]) -> List[Endpoint]:
        """Parse API paths into endpoints."""
        endpoints = []
        
        for path, path_item in paths_data.items():
            if not isinstance(path_item, dict):
                continue
                
            for method, operation in path_item.items():
                if method.upper() not in [m.value for m in EndpointMethod]:
                    continue
                
                if not isinstance(operation, dict):
                    continue
                
                endpoint = self._parse_operation(path, method.upper(), operation)
                endpoints.append(endpoint)
        
        return endpoints
    
    def _parse_operation(self, path: str, method: str, operation: Dict[str, Any]) -> Endpoint:
        """Parse a single operation into an Endpoint."""
        # Parse parameters
        parameters = []
        for param_data in operation.get("parameters", []):
            parameter = self._parse_parameter(param_data)
            parameters.append(parameter)
        
        # Parse request body parameters if present
        request_body = operation.get("requestBody")
        if request_body:
            body_params = self._parse_request_body(request_body)
            parameters.extend(body_params)
        
        # Parse responses
        responses = []
        for status_code, response_data in operation.get("responses", {}).items():
            response = self._parse_response(status_code, response_data)
            responses.append(response)
        
        return Endpoint(
            path=path,
            method=EndpointMethod(method),
            summary=operation.get("summary"),
            description=operation.get("description"),
            operation_id=operation.get("operationId"),
            tags=operation.get("tags", []),
            parameters=parameters,
            responses=responses
        )
    
    def _parse_parameter(self, param_data: Dict[str, Any]) -> Parameter:
        """Parse parameter data."""
        schema = param_data.get("schema", {})
        
        return Parameter(
            name=param_data.get("name", ""),
            type=schema.get("type", "string"),
            description=param_data.get("description"),
            required=param_data.get("required", False),
            location=param_data.get("in"),
            example=param_data.get("example") or schema.get("example"),
            enum_values=schema.get("enum")
        )
    
    def _parse_request_body(self, request_body: Dict[str, Any]) -> List[Parameter]:
        """Parse request body into parameters."""
        parameters = []
        content = request_body.get("content", {})
        
        for content_type, content_data in content.items():
            schema = content_data.get("schema", {})
            
            # For simple schemas, create a single body parameter
            if schema.get("type") in ["object", None]:
                parameter = Parameter(
                    name="body",
                    type="object",
                    description=request_body.get("description"),
                    required=request_body.get("required", False),
                    location="body"
                )
                parameters.append(parameter)
            else:
                # For primitive types
                parameter = Parameter(
                    name="body",
                    type=schema.get("type", "string"),
                    description=request_body.get("description"),
                    required=request_body.get("required", False),
                    location="body",
                    example=schema.get("example")
                )
                parameters.append(parameter)
        
        return parameters
    
    def _parse_response(self, status_code: str, response_data: Dict[str, Any]) -> Response:
        """Parse response data."""
        content = response_data.get("content", {})
        
        # Get the first content type and its schema
        content_type = None
        schema = None
        examples = None
        
        if content:
            content_type = list(content.keys())[0]
            content_info = content[content_type]
            schema = content_info.get("schema")
            examples = content_info.get("examples")
        
        return Response(
            status_code=status_code,
            description=response_data.get("description"),
            content_type=content_type,
            schema=schema,
            examples=examples
        )
    
    def _parse_schemas(self, spec_dict: Dict[str, Any]) -> List[Schema]:
        """Parse component schemas."""
        schemas = []
        
        # OpenAPI 3.x components
        components = spec_dict.get("components", {})
        schemas_data = components.get("schemas", {})
        
        # OpenAPI 2.x definitions
        if not schemas_data:
            schemas_data = spec_dict.get("definitions", {})
        
        for name, schema_data in schemas_data.items():
            schema = self._parse_schema(name, schema_data)
            schemas.append(schema)
        
        return schemas
    
    def _parse_schema(self, name: str, schema_data: Dict[str, Any]) -> Schema:
        """Parse a single schema definition."""
        return Schema(
            name=name,
            type=schema_data.get("type", "object"),
            description=schema_data.get("description"),
            properties=schema_data.get("properties", {}),
            required_fields=schema_data.get("required", []),
            example=schema_data.get("example")
        )
    
    def _parse_tags(self, tags_data: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """Parse tag information."""
        tags = []
        for tag in tags_data:
            tags.append({
                "name": tag.get("name", ""),
                "description": tag.get("description", "")
            })
        return tags