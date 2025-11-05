"""
GraphQL specification parser.
"""
from typing import Dict, Any, List

from graphql import build_schema, GraphQLSchema
from graphql.type import (
    GraphQLObjectType, 
    GraphQLField,
    GraphQLArgument,
    GraphQLInputObjectType,
    GraphQLEnumType,
    GraphQLScalarType,
    GraphQLList,
    GraphQLNonNull
)

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


class GraphQLParser(BaseParser):
    """Parser for GraphQL schemas."""
    
    def get_supported_format(self) -> SpecFormat:
        """Return GraphQL format."""
        return SpecFormat.GRAPHQL
    
    def parse(self, spec_content: str | Dict[str, Any]) -> ParsedSpecification:
        """Parse GraphQL schema."""
        try:
            # Extract schema string from content
            schema_string = self._extract_schema_string(spec_content)
            
            # Build GraphQL schema
            schema = build_schema(schema_string)
            
            # Extract basic info (GraphQL doesn't have built-in metadata)
            title = "GraphQL API"
            version = "1.0.0"
            description = "GraphQL API Schema"
            
            # Parse queries and mutations as endpoints
            endpoints = self._parse_operations(schema)
            
            # Parse types as schemas
            schemas = self._parse_types(schema)
            
            return ParsedSpecification(
                format=SpecFormat.GRAPHQL,
                title=title,
                version=version,
                description=description,
                endpoints=endpoints,
                schemas=schemas,
                raw_spec={"schema": schema_string}
            )
            
        except Exception as e:
            raise ParseError(f"Failed to parse GraphQL schema: {e}")
    
    def _extract_schema_string(self, content: str | Dict[str, Any]) -> str:
        """Extract GraphQL schema string from various input formats."""
        if isinstance(content, str):
            return content
        
        if isinstance(content, dict):
            # Look for schema in common locations
            if "schema" in content:
                return content["schema"]
            elif "data" in content:
                return content["data"]
            elif "query" in content:
                # Might be an introspection result
                raise ParseError("Introspection result parsing not yet supported")
            else:
                raise ParseError("GraphQL schema not found in provided structure")
        
        raise ParseError("Invalid GraphQL content format")
    
    def _parse_operations(self, schema: GraphQLSchema) -> List[Endpoint]:
        """Parse GraphQL operations (queries, mutations) as endpoints."""
        endpoints = []
        
        # Parse Query type
        if schema.query_type:
            query_endpoints = self._parse_object_type_fields(
                schema.query_type, 
                EndpointMethod.GET,
                "query"
            )
            endpoints.extend(query_endpoints)
        
        # Parse Mutation type
        if schema.mutation_type:
            mutation_endpoints = self._parse_object_type_fields(
                schema.mutation_type,
                EndpointMethod.POST, 
                "mutation"
            )
            endpoints.extend(mutation_endpoints)
        
        # Parse Subscription type
        if schema.subscription_type:
            subscription_endpoints = self._parse_object_type_fields(
                schema.subscription_type,
                EndpointMethod.GET,
                "subscription"
            )
            endpoints.extend(subscription_endpoints)
        
        return endpoints
    
    def _parse_object_type_fields(self, obj_type: GraphQLObjectType, 
                                 method: EndpointMethod, 
                                 operation_type: str) -> List[Endpoint]:
        """Parse fields of an object type as endpoints."""
        endpoints = []
        
        for field_name, field in obj_type.fields.items():
            endpoint = self._parse_field_as_endpoint(
                field_name, 
                field, 
                method, 
                operation_type
            )
            endpoints.append(endpoint)
        
        return endpoints
    
    def _parse_field_as_endpoint(self, field_name: str, 
                               field: GraphQLField,
                               method: EndpointMethod,
                               operation_type: str) -> Endpoint:
        """Parse a GraphQL field as an API endpoint."""
        # Parse arguments as parameters
        parameters = []
        for arg_name, arg in field.args.items():
            parameter = self._parse_argument_as_parameter(arg_name, arg)
            parameters.append(parameter)
        
        # Create response based on return type
        response = Response(
            status_code="200",
            description=f"Successful {operation_type}",
            content_type="application/json",
            schema={"type": self._get_type_name(field.type)}
        )
        
        return Endpoint(
            path=f"/{operation_type}/{field_name}",
            method=method,
            summary=field_name,
            description=field.description,
            operation_id=f"{operation_type}_{field_name}",
            tags=[operation_type.capitalize()],
            parameters=parameters,
            responses=[response]
        )
    
    def _parse_argument_as_parameter(self, arg_name: str, 
                                   arg: GraphQLArgument) -> Parameter:
        """Parse GraphQL argument as parameter."""
        arg_type = self._get_type_name(arg.type)
        required = isinstance(arg.type, GraphQLNonNull)
        
        return Parameter(
            name=arg_name,
            type=arg_type,
            description=arg.description,
            required=required,
            location="query" if arg_type in ["String", "Int", "Float", "Boolean"] else "body"
        )
    
    def _parse_types(self, schema: GraphQLSchema) -> List[Schema]:
        """Parse GraphQL types as schemas."""
        schemas = []
        
        for type_name, type_def in schema.type_map.items():
            # Skip built-in types
            if type_name.startswith("__"):
                continue
            
            if isinstance(type_def, GraphQLObjectType):
                schema_obj = self._parse_object_type_as_schema(type_name, type_def)
                schemas.append(schema_obj)
            elif isinstance(type_def, GraphQLInputObjectType):
                schema_obj = self._parse_input_type_as_schema(type_name, type_def)
                schemas.append(schema_obj)
            elif isinstance(type_def, GraphQLEnumType):
                schema_obj = self._parse_enum_type_as_schema(type_name, type_def)
                schemas.append(schema_obj)
        
        return schemas
    
    def _parse_object_type_as_schema(self, type_name: str, 
                                   obj_type: GraphQLObjectType) -> Schema:
        """Parse GraphQL object type as schema."""
        properties = {}
        required_fields = []
        
        for field_name, field in obj_type.fields.items():
            properties[field_name] = {
                "type": self._get_type_name(field.type),
                "description": field.description
            }
            
            if isinstance(field.type, GraphQLNonNull):
                required_fields.append(field_name)
        
        return Schema(
            name=type_name,
            type="object",
            description=obj_type.description,
            properties=properties,
            required_fields=required_fields
        )
    
    def _parse_input_type_as_schema(self, type_name: str,
                                  input_type: GraphQLInputObjectType) -> Schema:
        """Parse GraphQL input type as schema."""
        properties = {}
        required_fields = []
        
        for field_name, field in input_type.fields.items():
            properties[field_name] = {
                "type": self._get_type_name(field.type),
                "description": field.description
            }
            
            if isinstance(field.type, GraphQLNonNull):
                required_fields.append(field_name)
        
        return Schema(
            name=type_name,
            type="object",
            description=input_type.description,
            properties=properties,
            required_fields=required_fields
        )
    
    def _parse_enum_type_as_schema(self, type_name: str,
                                 enum_type: GraphQLEnumType) -> Schema:
        """Parse GraphQL enum type as schema."""
        enum_values = list(enum_type.values.keys())
        
        return Schema(
            name=type_name,
            type="string",
            description=enum_type.description,
            properties={"enum": enum_values}
        )
    
    def _get_type_name(self, graphql_type) -> str:
        """Get string representation of GraphQL type."""
        if isinstance(graphql_type, GraphQLNonNull):
            return self._get_type_name(graphql_type.of_type)
        elif isinstance(graphql_type, GraphQLList):
            return f"array<{self._get_type_name(graphql_type.of_type)}>"
        elif isinstance(graphql_type, (GraphQLObjectType, GraphQLInputObjectType, GraphQLEnumType)):
            return graphql_type.name
        elif isinstance(graphql_type, GraphQLScalarType):
            # Map GraphQL scalars to common types
            scalar_map = {
                "String": "string",
                "Int": "integer", 
                "Float": "number",
                "Boolean": "boolean",
                "ID": "string"
            }
            return scalar_map.get(graphql_type.name, graphql_type.name)
        else:
            return str(graphql_type)