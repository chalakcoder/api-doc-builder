"""
Documentation generation prompt templates for GenAI.
Provides structured prompts for different documentation sections.
"""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum
import json


class DocumentationSection(str, Enum):
    """Documentation section types."""
    OVERVIEW = "overview"
    ENDPOINTS = "endpoints"
    SCHEMAS = "schemas"
    EXAMPLES = "examples"
    AUTHENTICATION = "authentication"
    ERROR_HANDLING = "error_handling"


class SpecificationType(str, Enum):
    """Supported specification types."""
    OPENAPI = "openapi"
    GRAPHQL = "graphql"
    JSON_SCHEMA = "json_schema"


@dataclass
class PromptContext:
    """Context data for prompt generation."""
    specification: Dict[str, Any]
    spec_type: SpecificationType
    service_name: str
    team_id: str
    section: DocumentationSection
    output_format: str = "markdown"
    additional_context: Optional[Dict[str, Any]] = None


class PromptTemplateEngine:
    """
    Engine for generating structured prompts for documentation generation.
    
    Creates context-aware prompts for different documentation sections
    based on specification type and content.
    """
    
    def __init__(self):
        """Initialize prompt template engine."""
        self._base_instructions = self._load_base_instructions()
        self._section_templates = self._load_section_templates()
        
    def _load_base_instructions(self) -> str:
        """Load base instructions for all prompts."""
        return """
You are a technical documentation expert specializing in API documentation generation.
Your task is to create comprehensive, clear, and accurate documentation from API specifications.

Guidelines:
- Write in clear, professional language suitable for developers
- Include practical examples and use cases
- Focus on accuracy and completeness
- Use proper formatting for the requested output format
- Highlight important information like required fields, authentication, and error conditions
- Provide code examples in multiple programming languages when appropriate
- Ensure all technical details are correct and up-to-date

Output Format: {output_format}
Service Name: {service_name}
Team: {team_id}
"""

    def _load_section_templates(self) -> Dict[DocumentationSection, str]:
        """Load templates for different documentation sections."""
        return {
            DocumentationSection.OVERVIEW: """
Generate a comprehensive API overview section that includes:

1. **Service Description**: Brief description of what this API does and its primary purpose
2. **Key Features**: Main capabilities and features provided by the API
3. **Base URL**: API base URL and versioning information
4. **Quick Start**: Simple getting started guide with basic usage example
5. **Architecture**: High-level architecture overview if applicable

Focus on giving developers a clear understanding of the API's purpose and capabilities.
Make it engaging and informative for both new and experienced developers.

Specification Type: {spec_type}
Specification Content: {specification}
""",

            DocumentationSection.ENDPOINTS: """
Generate detailed endpoint documentation that includes:

For each endpoint:
1. **HTTP Method and Path**: Clear method and URL path
2. **Description**: What the endpoint does and when to use it
3. **Parameters**: 
   - Path parameters with types and descriptions
   - Query parameters with types, required/optional status, and descriptions
   - Request body schema with examples
4. **Request Examples**: Show actual request examples with sample data
5. **Response Format**: Expected response structure and status codes
6. **Response Examples**: Show successful and error response examples
7. **Error Codes**: Possible error responses with explanations

Make sure to include realistic examples that developers can copy and use.
Group related endpoints logically and provide clear navigation.

Specification Type: {spec_type}
Specification Content: {specification}
""",

            DocumentationSection.SCHEMAS: """
Generate comprehensive data model documentation that includes:

For each schema/model:
1. **Model Name**: Clear, descriptive name
2. **Description**: Purpose and usage of the model
3. **Properties**: 
   - Field names with types
   - Required vs optional fields
   - Field descriptions and constraints
   - Default values where applicable
   - Validation rules (min/max length, patterns, etc.)
4. **Relationships**: How models relate to each other
5. **Examples**: Complete example objects with realistic data
6. **Usage Notes**: Important implementation details or gotchas

Present schemas in a logical order, with dependencies listed first.
Use clear formatting to distinguish between different data types.

Specification Type: {spec_type}
Specification Content: {specification}
""",

            DocumentationSection.EXAMPLES: """
Generate comprehensive code examples that include:

1. **Multi-Language Examples**: Provide code samples in these programming languages:
   - Python (using requests library)
   - JavaScript (using fetch API and async/await)
   - cURL commands (with proper formatting)
   - Java (using HttpClient)
   - C# (using HttpClient)
   - PHP (using cURL)
   - Ruby (using Net::HTTP)

2. **Complete Request Examples**: For each endpoint, show:
   - Full request setup including headers and authentication
   - Parameter handling (path, query, body parameters)
   - Request body formatting for POST/PUT operations
   - Proper error handling and response parsing

3. **Common Use Cases**: Real-world scenarios demonstrating:
   - Basic CRUD operations with realistic data
   - Authentication flows (API key, OAuth, JWT)
   - Error handling with retry logic
   - Pagination patterns (if applicable)
   - Filtering and searching operations (if applicable)
   - Batch operations (if supported)

4. **Response Handling**: Show how to:
   - Parse successful responses
   - Handle different HTTP status codes
   - Extract specific data from responses
   - Handle error responses gracefully

5. **Complete Workflows**: End-to-end examples showing:
   - Multi-step API interactions
   - Data transformation and validation
   - Integration with common frameworks
   - Best practices for production use

Format each example with:
- Clear section headers for each language
- Inline comments explaining important steps
- Realistic example data that makes sense for the API domain
- Proper code formatting and indentation
- Error handling patterns

Make all examples copy-pasteable and production-ready.

Specification Type: {spec_type}
Specification Content: {specification}
""",

            DocumentationSection.AUTHENTICATION: """
Generate authentication and authorization documentation that includes:

1. **Authentication Methods**: 
   - Supported authentication types (API keys, OAuth, JWT, etc.)
   - How to obtain credentials
   - Where to include authentication in requests

2. **Authorization Scopes**: 
   - Available permission levels
   - Scope requirements for different endpoints
   - How to request specific scopes

3. **Security Best Practices**:
   - Credential storage recommendations
   - Token refresh procedures
   - Rate limiting information

4. **Examples**:
   - Authentication request examples
   - Authenticated API call examples
   - Error handling for auth failures

5. **Troubleshooting**:
   - Common authentication errors
   - How to debug auth issues

Make security information clear and actionable for developers.

Specification Type: {spec_type}
Specification Content: {specification}
""",

            DocumentationSection.ERROR_HANDLING: """
Generate comprehensive error handling documentation that includes:

1. **Error Response Format**:
   - Standard error response structure
   - Error code meanings
   - Error message formats

2. **HTTP Status Codes**:
   - All possible status codes returned by the API
   - When each status code is used
   - How to handle each type of error

3. **Error Categories**:
   - Client errors (4xx) with resolution steps
   - Server errors (5xx) with retry guidance
   - Validation errors with field-specific details

4. **Error Examples**:
   - Sample error responses for common scenarios
   - How to parse and handle errors in code

5. **Retry Logic**:
   - Which errors are retryable
   - Recommended retry strategies
   - Exponential backoff guidelines

6. **Debugging Tips**:
   - How to troubleshoot common issues
   - Logging and monitoring recommendations

Focus on helping developers handle errors gracefully and debug issues effectively.

Specification Type: {spec_type}
Specification Content: {specification}
"""
        }
        
    def generate_prompt(self, context: PromptContext) -> str:
        """
        Generate a structured prompt for documentation generation.
        
        Args:
            context: Prompt context with specification and metadata
            
        Returns:
            Formatted prompt string for GenAI
        """
        # Get base instructions
        base_instructions = self._base_instructions.format(
            output_format=context.output_format,
            service_name=context.service_name,
            team_id=context.team_id
        )
        
        # Get section-specific template
        section_template = self._section_templates.get(context.section)
        if not section_template:
            raise ValueError(f"Unknown documentation section: {context.section}")
            
        # Format section template with context
        section_prompt = section_template.format(
            spec_type=context.spec_type.value,
            specification=self._format_specification(context.specification),
            service_name=context.service_name,
            team_id=context.team_id
        )
        
        # Combine base instructions with section-specific prompt
        full_prompt = f"{base_instructions}\n\n{section_prompt}"
        
        # Add additional context if provided
        if context.additional_context:
            additional_info = self._format_additional_context(context.additional_context)
            full_prompt += f"\n\nAdditional Context:\n{additional_info}"
            
        return full_prompt
        
    def _format_specification(self, specification: Dict[str, Any]) -> str:
        """
        Format specification for inclusion in prompt.
        
        Args:
            specification: Raw specification data
            
        Returns:
            Formatted specification string
        """
        # Convert to JSON with proper formatting
        return json.dumps(specification, indent=2, ensure_ascii=False)
        
    def _format_additional_context(self, context: Dict[str, Any]) -> str:
        """
        Format additional context for inclusion in prompt.
        
        Args:
            context: Additional context data
            
        Returns:
            Formatted context string
        """
        formatted_lines = []
        for key, value in context.items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value, indent=2)
            formatted_lines.append(f"- {key}: {value}")
            
        return "\n".join(formatted_lines)
        
    def generate_section_prompts(
        self,
        specification: Dict[str, Any],
        spec_type: SpecificationType,
        service_name: str,
        team_id: str,
        sections: List[DocumentationSection] = None,
        output_format: str = "markdown",
        additional_context: Optional[Dict[str, Any]] = None
    ) -> Dict[DocumentationSection, str]:
        """
        Generate prompts for multiple documentation sections.
        
        Args:
            specification: API specification data
            spec_type: Type of specification
            service_name: Name of the service
            team_id: Team identifier
            sections: List of sections to generate (default: all)
            output_format: Output format (markdown, html)
            additional_context: Additional context data
            
        Returns:
            Dictionary mapping sections to their prompts
        """
        if sections is None:
            sections = list(DocumentationSection)
            
        prompts = {}
        
        for section in sections:
            context = PromptContext(
                specification=specification,
                spec_type=spec_type,
                service_name=service_name,
                team_id=team_id,
                section=section,
                output_format=output_format,
                additional_context=additional_context
            )
            
            prompts[section] = self.generate_prompt(context)
            
        return prompts


class SpecificationAnalyzer:
    """
    Analyzer for determining which documentation sections are relevant
    for a given specification.
    """
    
    def analyze_specification(
        self,
        specification: Dict[str, Any],
        spec_type: SpecificationType
    ) -> List[DocumentationSection]:
        """
        Analyze specification to determine relevant documentation sections.
        
        Args:
            specification: API specification data
            spec_type: Type of specification
            
        Returns:
            List of relevant documentation sections
        """
        sections = [DocumentationSection.OVERVIEW]
        
        if spec_type == SpecificationType.OPENAPI:
            sections.extend(self._analyze_openapi(specification))
        elif spec_type == SpecificationType.GRAPHQL:
            sections.extend(self._analyze_graphql(specification))
        elif spec_type == SpecificationType.JSON_SCHEMA:
            sections.extend(self._analyze_json_schema(specification))
            
        return sections
        
    def _analyze_openapi(self, spec: Dict[str, Any]) -> List[DocumentationSection]:
        """Analyze OpenAPI specification for relevant sections."""
        sections = []
        
        # Check for endpoints
        if spec.get("paths"):
            sections.append(DocumentationSection.ENDPOINTS)
            sections.append(DocumentationSection.EXAMPLES)
            
        # Check for schemas
        if spec.get("components", {}).get("schemas") or spec.get("definitions"):
            sections.append(DocumentationSection.SCHEMAS)
            
        # Check for authentication
        if (spec.get("components", {}).get("securitySchemes") or 
            spec.get("securityDefinitions") or 
            spec.get("security")):
            sections.append(DocumentationSection.AUTHENTICATION)
            
        # Always include error handling for APIs with endpoints
        if DocumentationSection.ENDPOINTS in sections:
            sections.append(DocumentationSection.ERROR_HANDLING)
            
        return sections
        
    def _analyze_graphql(self, spec: Dict[str, Any]) -> List[DocumentationSection]:
        """Analyze GraphQL specification for relevant sections."""
        sections = []
        
        # GraphQL always has schemas
        sections.append(DocumentationSection.SCHEMAS)
        sections.append(DocumentationSection.EXAMPLES)
        
        # Check for queries/mutations (endpoints equivalent)
        if spec.get("data", {}).get("__schema", {}).get("queryType"):
            sections.append(DocumentationSection.ENDPOINTS)
            
        # GraphQL typically has authentication
        sections.append(DocumentationSection.AUTHENTICATION)
        sections.append(DocumentationSection.ERROR_HANDLING)
        
        return sections
        
    def _analyze_json_schema(self, spec: Dict[str, Any]) -> List[DocumentationSection]:
        """Analyze JSON Schema specification for relevant sections."""
        sections = []
        
        # JSON Schema is primarily about data models
        sections.append(DocumentationSection.SCHEMAS)
        sections.append(DocumentationSection.EXAMPLES)
        
        return sections


# Global instances
prompt_engine = PromptTemplateEngine()
spec_analyzer = SpecificationAnalyzer()


def get_prompt_engine() -> PromptTemplateEngine:
    """Get global prompt template engine instance."""
    return prompt_engine


def get_spec_analyzer() -> SpecificationAnalyzer:
    """Get global specification analyzer instance."""
    return spec_analyzer