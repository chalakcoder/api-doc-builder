"""
JSON Schema specification parser.
"""
from typing import Dict, Any, List

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


class JSONSchemaParser(BaseParser):
    """Parser for JSON Schema specifications."""
    
    def get_supported_format(self) -> SpecFormat:
        """Return JSON Schema format."""
        return SpecFormat.JSON_SCHEMA
    
    def parse(self, spec_content: str | Dict[str, Any]) -> ParsedSpecification:
        """Parse JSON Schema specification."""
        try:
            spec_dict = self._parse_content(spec_content)
            
            # Extract basic info
            title = spec_dict.get("title", "JSON Schema")
            version = spec_dict.get("version", "1.0.0")
            description = spec_dict.get("description")
            
            # JSON Schema doesn't define endpoints, so we create a virtual one
            # representing the schema validation endpoint
            endpoints = self._create_validation_endpoints(spec_dict)
            
            # Parse the main schema and any definitions
            schemas = self._parse_schemas(spec_dict)
            
            return ParsedSpecification(
                format=SpecFormat.JSON_SCHEMA,
                title=title,
                version=version,
                description=description,
                endpoints=endpoints,
                schemas=schemas,
                raw_spec=spec_dict
            )
            
        except Exception as e:
            raise ParseError(f"Failed to parse JSON Schema: {e}")
    
    def _create_validation_endpoints(self, schema_dict: Dict[str, Any]) -> List[Endpoint]:
        """Create virtual endpoints for schema validation."""
        endpoints = []
        
        # Main validation endpoint
        main_endpoint = Endpoint(
            path="/validate",
            method=EndpointMethod.POST,
            summary="Validate data against schema",
            description="Validates input data against the JSON schema",
            operation_id="validate_data",
            tags=["Validation"],
            parameters=[
                Parameter(
                    name="data",
                    type="object",
                    description="Data to validate against the schema",
                    required=True,
                    location="body"
                )
            ],
            responses=[
                Response(
                    status_code="200",
                    description="Validation successful",
                    content_type="application/json",
                    schema={"type": "object", "properties": {"valid": {"type": "boolean"}}}
                ),
                Response(
                    status_code="400", 
                    description="Validation failed",
                    content_type="application/json",
                    schema={"type": "object", "properties": {"errors": {"type": "array"}}}
                )
            ]
        )
        endpoints.append(main_endpoint)
        
        # If there are definitions, create endpoints for each
        definitions = schema_dict.get("definitions", {})
        if not definitions:
            definitions = schema_dict.get("$defs", {})
        
        for def_name in definitions.keys():
            def_endpoint = Endpoint(
                path=f"/validate/{def_name.lower()}",
                method=EndpointMethod.POST,
                summary=f"Validate {def_name}",
                description=f"Validates input data against the {def_name} schema definition",
                operation_id=f"validate_{def_name.lower()}",
                tags=["Validation", def_name],
                parameters=[
                    Parameter(
                        name="data",
                        type="object", 
                        description=f"Data to validate against {def_name} schema",
                        required=True,
                        location="body"
                    )
                ],
                responses=[
                    Response(
                        status_code="200",
                        description="Validation successful",
                        content_type="application/json"
                    ),
                    Response(
                        status_code="400",
                        description="Validation failed", 
                        content_type="application/json"
                    )
                ]
            )
            endpoints.append(def_endpoint)
        
        return endpoints
    
    def _parse_schemas(self, spec_dict: Dict[str, Any]) -> List[Schema]:
        """Parse JSON Schema definitions."""
        schemas = []
        
        # Parse the root schema
        if spec_dict.get("type") or spec_dict.get("properties"):
            root_schema = self._parse_single_schema("RootSchema", spec_dict)
            schemas.append(root_schema)
        
        # Parse definitions
        definitions = spec_dict.get("definitions", {})
        if not definitions:
            definitions = spec_dict.get("$defs", {})
        
        for name, schema_data in definitions.items():
            schema = self._parse_single_schema(name, schema_data)
            schemas.append(schema)
        
        return schemas
    
    def _parse_single_schema(self, name: str, schema_data: Dict[str, Any]) -> Schema:
        """Parse a single JSON schema definition."""
        schema_type = schema_data.get("type", "object")
        
        # Handle array types
        if schema_type == "array":
            items = schema_data.get("items", {})
            if isinstance(items, dict):
                item_type = items.get("type", "object")
                schema_type = f"array<{item_type}>"
        
        # Extract properties
        properties = {}
        if "properties" in schema_data:
            for prop_name, prop_data in schema_data["properties"].items():
                properties[prop_name] = self._parse_property(prop_data)
        
        # Handle allOf, anyOf, oneOf
        if "allOf" in schema_data:
            properties.update(self._merge_schema_properties(schema_data["allOf"]))
        elif "anyOf" in schema_data:
            properties.update(self._merge_schema_properties(schema_data["anyOf"]))
        elif "oneOf" in schema_data:
            properties.update(self._merge_schema_properties(schema_data["oneOf"]))
        
        return Schema(
            name=name,
            type=schema_type,
            description=schema_data.get("description"),
            properties=properties,
            required_fields=schema_data.get("required", []),
            example=schema_data.get("examples", [None])[0] if schema_data.get("examples") else None
        )
    
    def _parse_property(self, prop_data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse a single property definition."""
        prop_type = prop_data.get("type", "string")
        
        # Handle array properties
        if prop_type == "array":
            items = prop_data.get("items", {})
            if isinstance(items, dict):
                item_type = items.get("type", "object")
                prop_type = f"array<{item_type}>"
        
        property_info = {
            "type": prop_type,
            "description": prop_data.get("description")
        }
        
        # Add constraints
        if "enum" in prop_data:
            property_info["enum"] = prop_data["enum"]
        if "format" in prop_data:
            property_info["format"] = prop_data["format"]
        if "minimum" in prop_data:
            property_info["minimum"] = prop_data["minimum"]
        if "maximum" in prop_data:
            property_info["maximum"] = prop_data["maximum"]
        if "minLength" in prop_data:
            property_info["minLength"] = prop_data["minLength"]
        if "maxLength" in prop_data:
            property_info["maxLength"] = prop_data["maxLength"]
        if "pattern" in prop_data:
            property_info["pattern"] = prop_data["pattern"]
        
        return property_info
    
    def _merge_schema_properties(self, schema_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Merge properties from multiple schemas (for allOf, anyOf, oneOf)."""
        merged_properties = {}
        
        for schema in schema_list:
            if "properties" in schema:
                for prop_name, prop_data in schema["properties"].items():
                    merged_properties[prop_name] = self._parse_property(prop_data)
        
        return merged_properties