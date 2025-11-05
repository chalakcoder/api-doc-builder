"""
Documentation generator service that orchestrates GenAI-based documentation creation.
Combines specification parsing, prompt generation, and GenAI client calls.
"""
import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from app.services.genai_client import GenAIClient, GenAIRequest, GenAIResponse, get_genai_client
from app.services.prompt_templates import (
    PromptTemplateEngine, 
    SpecificationAnalyzer,
    DocumentationSection,
    SpecificationType,
    PromptContext,
    get_prompt_engine,
    get_spec_analyzer
)
from app.parsers.base import ParsedSpecification, Endpoint, Parameter, EndpointMethod

logger = logging.getLogger(__name__)


class OutputFormat(str, Enum):
    """Supported output formats for documentation."""
    MARKDOWN = "markdown"
    HTML = "html"


@dataclass
class DocumentationRequest:
    """Request for documentation generation."""
    specification: Dict[str, Any]
    spec_type: SpecificationType
    service_name: str
    team_id: str
    output_formats: List[OutputFormat]
    sections: Optional[List[DocumentationSection]] = None
    additional_context: Optional[Dict[str, Any]] = None


@dataclass
class GeneratedDocumentationSection:
    """Generated documentation section."""
    section_type: DocumentationSection
    content: str
    tokens_used: int
    generation_metadata: Optional[Dict[str, Any]] = None


@dataclass
class DocumentationResult:
    """Complete documentation generation result."""
    request: DocumentationRequest
    sections: List[GeneratedDocumentationSection]
    total_tokens_used: int
    generation_time_seconds: float
    formatted_outputs: Dict[OutputFormat, str]
    metadata: Optional[Dict[str, Any]] = None


class DocumentationGenerator:
    """
    Main documentation generator that orchestrates the entire process.
    
    Handles specification analysis, prompt generation, GenAI calls,
    and output formatting.
    """
    
    def __init__(
        self,
        genai_client: Optional[GenAIClient] = None,
        prompt_engine: Optional[PromptTemplateEngine] = None,
        spec_analyzer: Optional[SpecificationAnalyzer] = None,
        code_example_generator: Optional['CodeExampleGenerator'] = None
    ):
        """
        Initialize documentation generator.
        
        Args:
            genai_client: GenAI client instance
            prompt_engine: Prompt template engine
            spec_analyzer: Specification analyzer
            code_example_generator: Code example generator
        """
        self.genai_client = genai_client or get_genai_client()
        self.prompt_engine = prompt_engine or get_prompt_engine()
        self.spec_analyzer = spec_analyzer or get_spec_analyzer()
        self.code_example_generator = code_example_generator or CodeExampleGenerator()
        
    async def generate_documentation(
        self,
        request: DocumentationRequest
    ) -> DocumentationResult:
        """
        Generate complete documentation from specification.
        
        Args:
            request: Documentation generation request
            
        Returns:
            Complete documentation result with all sections and formats
            
        Raises:
            ValueError: If request is invalid
            GenAIError: If GenAI generation fails
        """
        import time
        start_time = time.time()
        
        logger.info(
            f"Starting documentation generation",
            extra={
                "service_name": request.service_name,
                "team_id": request.team_id,
                "spec_type": request.spec_type.value,
                "output_formats": [f.value for f in request.output_formats]
            }
        )
        
        try:
            # Determine sections to generate
            sections_to_generate = self._determine_sections(request)
            
            # Generate content for each section
            generated_sections = await self._generate_sections(
                request, sections_to_generate
            )
            
            # Enhance sections with programmatic code examples if needed
            generated_sections = self._enhance_sections_with_code_examples(
                generated_sections, request
            )
            
            # Format outputs in requested formats
            formatted_outputs = self._format_outputs(
                generated_sections, request.output_formats
            )
            
            # Calculate total tokens and time
            total_tokens = sum(section.tokens_used for section in generated_sections)
            generation_time = time.time() - start_time
            
            result = DocumentationResult(
                request=request,
                sections=generated_sections,
                total_tokens_used=total_tokens,
                generation_time_seconds=generation_time,
                formatted_outputs=formatted_outputs,
                metadata={
                    "sections_generated": len(generated_sections),
                    "avg_tokens_per_section": total_tokens / len(generated_sections) if generated_sections else 0
                }
            )
            
            logger.info(
                f"Documentation generation completed",
                extra={
                    "service_name": request.service_name,
                    "sections_generated": len(generated_sections),
                    "total_tokens": total_tokens,
                    "generation_time": generation_time
                }
            )
            
            return result
            
        except Exception as e:
            logger.error(
                f"Documentation generation failed: {str(e)}",
                extra={
                    "service_name": request.service_name,
                    "team_id": request.team_id,
                    "error_type": type(e).__name__
                }
            )
            raise
            
    def _determine_sections(
        self, 
        request: DocumentationRequest
    ) -> List[DocumentationSection]:
        """
        Determine which sections to generate based on specification analysis.
        
        Args:
            request: Documentation generation request
            
        Returns:
            List of sections to generate
        """
        if request.sections:
            return request.sections
            
        # Analyze specification to determine relevant sections
        analyzed_sections = self.spec_analyzer.analyze_specification(
            request.specification, request.spec_type
        )
        
        logger.info(
            f"Analyzed specification sections",
            extra={
                "service_name": request.service_name,
                "sections": [s.value for s in analyzed_sections]
            }
        )
        
        return analyzed_sections
        
    async def _generate_sections(
        self,
        request: DocumentationRequest,
        sections: List[DocumentationSection]
    ) -> List[GeneratedDocumentationSection]:
        """
        Generate content for all specified sections.
        
        Args:
            request: Documentation generation request
            sections: Sections to generate
            
        Returns:
            List of generated documentation sections
        """
        # Generate prompts for all sections
        section_prompts = {}
        for section in sections:
            context = PromptContext(
                specification=request.specification,
                spec_type=request.spec_type,
                service_name=request.service_name,
                team_id=request.team_id,
                section=section,
                output_format="markdown",  # Always generate in markdown first
                additional_context=request.additional_context
            )
            section_prompts[section] = self.prompt_engine.generate_prompt(context)
            
        # Create GenAI requests
        genai_requests = [
            GenAIRequest(
                prompt=prompt,
                max_tokens=3000,  # Larger token limit for documentation
                temperature=0.2,  # Lower temperature for more consistent output
                context={
                    "section": section.value,
                    "service_name": request.service_name,
                    "spec_type": request.spec_type.value
                }
            )
            for section, prompt in section_prompts.items()
        ]
        
        # Generate content using batch processing
        logger.info(
            f"Generating content for {len(genai_requests)} sections",
            extra={"service_name": request.service_name}
        )
        
        genai_responses = await self.genai_client.generate_batch(
            genai_requests, max_concurrent=3
        )
        
        # Combine sections with responses
        generated_sections = []
        for section, response in zip(sections, genai_responses):
            doc_section = GeneratedDocumentationSection(
                section_type=section,
                content=response.content,
                tokens_used=response.tokens_used,
                generation_metadata={
                    "model": response.model,
                    "request_id": response.request_id,
                    "response_metadata": response.metadata
                }
            )
            generated_sections.append(doc_section)
            
        return generated_sections
        
    def _format_outputs(
        self,
        sections: List[GeneratedDocumentationSection],
        output_formats: List[OutputFormat]
    ) -> Dict[OutputFormat, str]:
        """
        Format generated sections into requested output formats.
        
        Args:
            sections: Generated documentation sections
            output_formats: Requested output formats
            
        Returns:
            Dictionary mapping formats to formatted content
        """
        formatted_outputs = {}
        
        for output_format in output_formats:
            if output_format == OutputFormat.MARKDOWN:
                formatted_outputs[output_format] = self._format_markdown(sections)
            elif output_format == OutputFormat.HTML:
                formatted_outputs[output_format] = self._format_html(sections)
                
        return formatted_outputs
        
    def _format_markdown(self, sections: List[GeneratedDocumentationSection]) -> str:
        """
        Format sections as Markdown document.
        
        Args:
            sections: Generated documentation sections
            
        Returns:
            Complete Markdown document
        """
        markdown_parts = []
        
        # Add document header with metadata
        markdown_parts.append("# API Documentation\n")
        markdown_parts.append("*Generated automatically from API specification*\n")
        
        # Add table of contents
        markdown_parts.append("## Table of Contents\n")
        for section in sections:
            section_title = self._format_section_title(section.section_type)
            anchor = section.section_type.value.replace("_", "-")
            markdown_parts.append(f"- [{section_title}](#{anchor})")
        markdown_parts.append("\n")
        
        # Add each section with proper formatting
        for section in sections:
            section_title = self._format_section_title(section.section_type)
            anchor = section.section_type.value.replace("_", "-")
            
            markdown_parts.append(f"## {section_title} {{#{anchor}}}\n")
            
            # Clean and format section content
            formatted_content = self._clean_section_content(section.content)
            
            # Add code examples if this is the examples section
            if section.section_type == DocumentationSection.EXAMPLES:
                formatted_content = self._enhance_examples_section(formatted_content)
            
            markdown_parts.append(formatted_content)
            markdown_parts.append("\n---\n")
            
        # Add generation metadata footer
        markdown_parts.append(self._generate_footer())
            
        return "\n".join(markdown_parts)
        
    def _format_html(self, sections: List[GeneratedDocumentationSection]) -> str:
        """
        Format sections as HTML document.
        
        Args:
            sections: Generated documentation sections
            
        Returns:
            Complete HTML document
        """
        try:
            import markdown
        except ImportError:
            # Fallback to basic HTML formatting if markdown is not available
            return self._format_html_basic(sections)
        
        # Convert markdown to HTML
        markdown_content = self._format_markdown(sections)
        
        # Use markdown library to convert to HTML with extensions
        html_content = markdown.markdown(
            markdown_content,
            extensions=[
                'toc', 
                'codehilite', 
                'fenced_code', 
                'tables',
                'attr_list',
                'def_list'
            ],
            extension_configs={
                'codehilite': {
                    'css_class': 'highlight',
                    'use_pygments': True
                },
                'toc': {
                    'permalink': True
                }
            }
        )
        
        # Wrap in complete HTML document with enhanced styling
        html_document = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>API Documentation</title>
    <style>
        {self._get_html_styles()}
    </style>
</head>
<body>
    <div class="container">
        {html_content}
    </div>
    <script>
        {self._get_html_scripts()}
    </script>
</body>
</html>"""
        
        return html_document.strip()
        
    def _format_html_basic(self, sections: List[GeneratedDocumentationSection]) -> str:
        """
        Basic HTML formatting without markdown dependency.
        
        Args:
            sections: Generated documentation sections
            
        Returns:
            Basic HTML document
        """
        html_parts = []
        
        # Add document header
        html_parts.append('<h1>API Documentation</h1>')
        html_parts.append('<p><em>Generated automatically from API specification</em></p>')
        
        # Add table of contents
        html_parts.append('<h2>Table of Contents</h2>')
        html_parts.append('<ul>')
        for section in sections:
            section_title = self._format_section_title(section.section_type)
            anchor = section.section_type.value.replace("_", "-")
            html_parts.append(f'<li><a href="#{anchor}">{section_title}</a></li>')
        html_parts.append('</ul>')
        
        # Add each section
        for section in sections:
            section_title = self._format_section_title(section.section_type)
            anchor = section.section_type.value.replace("_", "-")
            
            html_parts.append(f'<h2 id="{anchor}">{section_title}</h2>')
            
            # Basic content formatting (escape HTML and preserve line breaks)
            import html
            escaped_content = html.escape(section.content)
            formatted_content = escaped_content.replace('\n', '<br>')
            html_parts.append(f'<div class="section-content">{formatted_content}</div>')
            html_parts.append('<hr>')
        
        # Add footer
        html_parts.append(self._generate_footer().replace('\n', '<br>'))
        
        # Wrap in complete HTML document
        html_document = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>API Documentation</title>
    <style>
        {self._get_html_styles()}
    </style>
</head>
<body>
    <div class="container">
        {''.join(html_parts)}
    </div>
</body>
</html>"""
        
        return html_document.strip()


# Global instance
documentation_generator: Optional[DocumentationGenerator] = None


def get_documentation_generator() -> DocumentationGenerator:
    """
    Get global documentation generator instance.
    
    Returns:
        Documentation generator instance
        
    Raises:
        RuntimeError: If generator is not initialized
    """
    if documentation_generator is None:
        raise RuntimeError("Documentation generator not initialized")
    return documentation_generator


    def _format_section_title(self, section_type: DocumentationSection) -> str:
        """
        Format section type as human-readable title.
        
        Args:
            section_type: Documentation section type
            
        Returns:
            Formatted title string
        """
        title_map = {
            DocumentationSection.OVERVIEW: "Overview",
            DocumentationSection.ENDPOINTS: "API Endpoints", 
            DocumentationSection.SCHEMAS: "Data Models",
            DocumentationSection.EXAMPLES: "Code Examples",
            DocumentationSection.AUTHENTICATION: "Authentication",
            DocumentationSection.ERROR_HANDLING: "Error Handling"
        }
        
        return title_map.get(section_type, section_type.value.replace("_", " ").title())
        
    def _clean_section_content(self, content: str) -> str:
        """
        Clean and format section content for better presentation.
        
        Args:
            content: Raw section content
            
        Returns:
            Cleaned and formatted content
        """
        # Remove excessive whitespace
        lines = content.split('\n')
        cleaned_lines = []
        
        for line in lines:
            # Remove trailing whitespace
            cleaned_line = line.rstrip()
            cleaned_lines.append(cleaned_line)
        
        # Remove excessive empty lines (more than 2 consecutive)
        final_lines = []
        empty_count = 0
        
        for line in cleaned_lines:
            if line.strip() == "":
                empty_count += 1
                if empty_count <= 2:
                    final_lines.append(line)
            else:
                empty_count = 0
                final_lines.append(line)
        
        return '\n'.join(final_lines).strip()
        
    def _generate_footer(self) -> str:
        """
        Generate documentation footer with metadata.
        
        Returns:
            Footer content
        """
        from datetime import datetime
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
        
        return f"""
---

*This documentation was automatically generated on {timestamp}*

*For questions or issues with this documentation, please contact the API team.*
"""
        
    def _get_html_styles(self) -> str:
        """
        Get CSS styles for HTML documentation.
        
        Returns:
            CSS styles string
        """
        return """
        :root {
            --primary-color: #2c3e50;
            --secondary-color: #3498db;
            --accent-color: #e74c3c;
            --background-color: #ffffff;
            --text-color: #333333;
            --border-color: #ecf0f1;
            --code-background: #f8f9fa;
            --success-color: #27ae60;
            --warning-color: #f39c12;
        }
        
        * {
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            margin: 0;
            padding: 0;
            color: var(--text-color);
            background-color: var(--background-color);
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        
        h1, h2, h3, h4, h5, h6 {
            color: var(--primary-color);
            margin-top: 2rem;
            margin-bottom: 1rem;
            font-weight: 600;
        }
        
        h1 {
            border-bottom: 3px solid var(--secondary-color);
            padding-bottom: 0.5rem;
            font-size: 2.5rem;
        }
        
        h2 {
            border-bottom: 2px solid var(--border-color);
            padding-bottom: 0.5rem;
            font-size: 2rem;
        }
        
        h3 {
            font-size: 1.5rem;
            color: var(--secondary-color);
        }
        
        p {
            margin-bottom: 1rem;
        }
        
        code {
            background-color: var(--code-background);
            padding: 0.2rem 0.4rem;
            border-radius: 3px;
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
            font-size: 0.9em;
            border: 1px solid var(--border-color);
        }
        
        pre {
            background-color: var(--code-background);
            padding: 1rem;
            border-radius: 5px;
            overflow-x: auto;
            border-left: 4px solid var(--secondary-color);
            margin: 1rem 0;
        }
        
        pre code {
            background: none;
            padding: 0;
            border: none;
            font-size: 0.9rem;
        }
        
        table {
            border-collapse: collapse;
            width: 100%;
            margin: 1.5rem 0;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        
        th, td {
            border: 1px solid var(--border-color);
            padding: 0.75rem;
            text-align: left;
        }
        
        th {
            background-color: var(--code-background);
            font-weight: 600;
            color: var(--primary-color);
        }
        
        tr:nth-child(even) {
            background-color: #fafafa;
        }
        
        tr:hover {
            background-color: #f0f8ff;
        }
        
        ul, ol {
            margin-bottom: 1rem;
            padding-left: 2rem;
        }
        
        li {
            margin-bottom: 0.5rem;
        }
        
        a {
            color: var(--secondary-color);
            text-decoration: none;
        }
        
        a:hover {
            text-decoration: underline;
        }
        
        blockquote {
            border-left: 4px solid var(--secondary-color);
            margin: 1rem 0;
            padding: 0.5rem 1rem;
            background-color: #f8f9fa;
            font-style: italic;
        }
        
        hr {
            border: none;
            border-top: 2px solid var(--border-color);
            margin: 2rem 0;
        }
        
        .section-content {
            margin-bottom: 2rem;
        }
        
        .highlight {
            background-color: var(--code-background);
            border-radius: 5px;
            padding: 1rem;
            overflow-x: auto;
        }
        
        .toc {
            background-color: var(--code-background);
            padding: 1.5rem;
            border-radius: 5px;
            margin: 1.5rem 0;
            border: 1px solid var(--border-color);
        }
        
        .toc ul {
            margin: 0;
            padding-left: 1.5rem;
        }
        
        .method-get { color: var(--success-color); }
        .method-post { color: var(--secondary-color); }
        .method-put { color: var(--warning-color); }
        .method-delete { color: var(--accent-color); }
        
        @media (max-width: 768px) {
            .container {
                padding: 10px;
            }
            
            h1 {
                font-size: 2rem;
            }
            
            h2 {
                font-size: 1.5rem;
            }
            
            table {
                font-size: 0.9rem;
            }
            
            th, td {
                padding: 0.5rem;
            }
        }
        """
        
    def _get_html_scripts(self) -> str:
        """
        Get JavaScript for HTML documentation interactivity.
        
        Returns:
            JavaScript code string
        """
        return """
        // Add smooth scrolling for anchor links
        document.querySelectorAll('a[href^="#"]').forEach(anchor => {
            anchor.addEventListener('click', function (e) {
                e.preventDefault();
                const target = document.querySelector(this.getAttribute('href'));
                if (target) {
                    target.scrollIntoView({
                        behavior: 'smooth',
                        block: 'start'
                    });
                }
            });
        });
        
        // Add copy buttons to code blocks
        document.querySelectorAll('pre code').forEach((block) => {
            const button = document.createElement('button');
            button.innerText = 'Copy';
            button.style.cssText = `
                position: absolute;
                top: 5px;
                right: 5px;
                padding: 5px 10px;
                background: #007bff;
                color: white;
                border: none;
                border-radius: 3px;
                cursor: pointer;
                font-size: 12px;
            `;
            
            const pre = block.parentElement;
            pre.style.position = 'relative';
            pre.appendChild(button);
            
            button.addEventListener('click', () => {
                navigator.clipboard.writeText(block.textContent).then(() => {
                    button.innerText = 'Copied!';
                    setTimeout(() => {
                        button.innerText = 'Copy';
                    }, 2000);
                });
            });
        });
        
        // Add table of contents highlighting
        const observer = new IntersectionObserver((entries) => {
            entries.forEach((entry) => {
                const id = entry.target.getAttribute('id');
                const tocLink = document.querySelector(`a[href="#${id}"]`);
                if (tocLink) {
                    if (entry.isIntersecting) {
                        tocLink.style.fontWeight = 'bold';
                        tocLink.style.color = '#007bff';
                    } else {
                        tocLink.style.fontWeight = 'normal';
                        tocLink.style.color = '#3498db';
                    }
                }
            });
        });
        
        document.querySelectorAll('h2[id]').forEach((heading) => {
            observer.observe(heading);
        });
        """
        
    def _enhance_examples_section(self, content: str) -> str:
        """
        Enhance examples section with additional code examples.
        
        Args:
            content: Original examples content
            
        Returns:
            Enhanced content with additional examples
        """
        # Add programmatically generated code examples
        enhanced_content = content
        
        # Add a section for programmatically generated examples
        enhanced_content += "\n\n## Additional Code Examples\n\n"
        enhanced_content += "*The following examples are programmatically generated to supplement the AI-generated examples above.*\n\n"
        
        # Note: In a real implementation, we would need access to the parsed specification
        # to generate specific examples. For now, we add a placeholder.
        enhanced_content += "### Example API Calls\n\n"
        enhanced_content += "```python\n"
        enhanced_content += "# Example Python code would be generated here based on the API specification\n"
        enhanced_content += "import requests\n\n"
        enhanced_content += "response = requests.get('https://api.example.com/endpoint')\n"
        enhanced_content += "print(response.json())\n"
        enhanced_content += "```\n\n"
        
        return enhanced_content
        
    def generate_code_examples_for_specification(
        self,
        parsed_spec: ParsedSpecification,
        base_url: str = None
    ) -> str:
        """
        Generate code examples for all endpoints in a specification.
        
        Args:
            parsed_spec: Parsed API specification
            base_url: Base URL for the API
            
        Returns:
            Formatted markdown with code examples
        """
        if not base_url:
            base_url = parsed_spec.base_url or "https://api.example.com"
            
        examples_content = []
        examples_content.append("# Code Examples\n")
        examples_content.append("This section provides code examples for all API endpoints.\n")
        
        # Group endpoints by tags or method
        endpoints_by_tag = {}
        for endpoint in parsed_spec.endpoints:
            tag = endpoint.tags[0] if endpoint.tags else "General"
            if tag not in endpoints_by_tag:
                endpoints_by_tag[tag] = []
            endpoints_by_tag[tag].append(endpoint)
            
        # Generate examples for each group
        for tag, endpoints in endpoints_by_tag.items():
            examples_content.append(f"\n## {tag}\n")
            
            for endpoint in endpoints:
                examples_content.append(f"\n### {endpoint.method.value} {endpoint.path}\n")
                
                if endpoint.summary:
                    examples_content.append(f"{endpoint.summary}\n")
                    
                # Generate examples for multiple languages
                code_examples = self.code_example_generator.generate_examples_for_endpoint(
                    endpoint, base_url
                )
                
                for language, example_code in code_examples.items():
                    examples_content.append(f"\n#### {language.title()}\n")
                    examples_content.append(f"```{language}\n{example_code}\n```\n")
                    
        return "\n".join(examples_content)
        
    def _enhance_sections_with_code_examples(
        self,
        sections: List[GeneratedDocumentationSection],
        request: DocumentationRequest
    ) -> List[GeneratedDocumentationSection]:
        """
        Enhance documentation sections with programmatic code examples.
        
        Args:
            sections: Generated documentation sections
            request: Original documentation request
            
        Returns:
            Enhanced sections with additional code examples
        """
        enhanced_sections = []
        
        for section in sections:
            enhanced_section = section
            
            # Enhance examples section with programmatic code examples
            if section.section_type == DocumentationSection.EXAMPLES:
                try:
                    # Try to parse the specification to generate specific examples
                    from app.parsers.parser_factory import ParserFactory
                    from app.validators.validators import SpecFormat
                    
                    # Map SpecificationType to SpecFormat
                    format_mapping = {
                        SpecificationType.OPENAPI: SpecFormat.OPENAPI,
                        SpecificationType.GRAPHQL: SpecFormat.GRAPHQL,
                        SpecificationType.JSON_SCHEMA: SpecFormat.JSON_SCHEMA
                    }
                    
                    spec_format = format_mapping.get(request.spec_type)
                    if spec_format:
                        factory = ParserFactory()
                        parser = factory.get_parser(spec_format)
                        parsed_spec = parser.parse(request.specification)
                        
                        # Generate programmatic code examples
                        code_examples = self.generate_code_examples_for_specification(parsed_spec)
                        
                        # Append to existing content
                        enhanced_content = section.content + "\n\n" + code_examples
                        
                        enhanced_section = GeneratedDocumentationSection(
                            section_type=section.section_type,
                            content=enhanced_content,
                            tokens_used=section.tokens_used,
                            generation_metadata=section.generation_metadata
                        )
                        
                except Exception as e:
                    logger.warning(
                        f"Failed to generate programmatic code examples: {str(e)}",
                        extra={"service_name": request.service_name}
                    )
                    # Fall back to basic enhancement
                    enhanced_content = self._enhance_examples_section(section.content)
                    enhanced_section = GeneratedDocumentationSection(
                        section_type=section.section_type,
                        content=enhanced_content,
                        tokens_used=section.tokens_used,
                        generation_metadata=section.generation_metadata
                    )
                    
            enhanced_sections.append(enhanced_section)
            
        return enhanced_sections


class CodeExampleGenerator:
    """
    Generator for programming language examples for API endpoints.
    
    Supports multiple languages including Python, JavaScript, curl, etc.
    """
    
    def __init__(self):
        """Initialize code example generator."""
        self.supported_languages = [
            "python",
            "javascript", 
            "curl",
            "java",
            "csharp",
            "php",
            "ruby"
        ]
        
    def generate_examples_for_endpoint(
        self,
        endpoint: Endpoint,
        base_url: str = "https://api.example.com",
        languages: List[str] = None
    ) -> Dict[str, str]:
        """
        Generate code examples for a specific endpoint.
        
        Args:
            endpoint: API endpoint to generate examples for
            base_url: Base URL for the API
            languages: List of languages to generate (default: all supported)
            
        Returns:
            Dictionary mapping language names to code examples
        """
        if languages is None:
            languages = self.supported_languages
            
        examples = {}
        
        for language in languages:
            if language in self.supported_languages:
                example = self._generate_language_example(endpoint, base_url, language)
                if example:
                    examples[language] = example
                    
        return examples
        
    def _generate_language_example(
        self,
        endpoint: Endpoint,
        base_url: str,
        language: str
    ) -> str:
        """
        Generate code example for specific language.
        
        Args:
            endpoint: API endpoint
            base_url: Base URL for the API
            language: Programming language
            
        Returns:
            Code example string
        """
        if language == "python":
            return self._generate_python_example(endpoint, base_url)
        elif language == "javascript":
            return self._generate_javascript_example(endpoint, base_url)
        elif language == "curl":
            return self._generate_curl_example(endpoint, base_url)
        elif language == "java":
            return self._generate_java_example(endpoint, base_url)
        elif language == "csharp":
            return self._generate_csharp_example(endpoint, base_url)
        elif language == "php":
            return self._generate_php_example(endpoint, base_url)
        elif language == "ruby":
            return self._generate_ruby_example(endpoint, base_url)
        else:
            return ""
            
    def _generate_python_example(self, endpoint: Endpoint, base_url: str) -> str:
        """Generate Python example using requests library."""
        url = f"{base_url.rstrip('/')}{endpoint.path}"
        method = endpoint.method.value.lower()
        
        # Extract parameters
        query_params = [p for p in endpoint.parameters if p.location == "query"]
        path_params = [p for p in endpoint.parameters if p.location == "path"]
        body_params = [p for p in endpoint.parameters if p.location == "body"]
        
        lines = [
            "import requests",
            "import json",
            "",
            "# API endpoint"
        ]
        
        # Handle path parameters
        if path_params:
            lines.append("# Replace path parameters with actual values")
            for param in path_params:
                example_value = self._get_example_value(param)
                url = url.replace(f"{{{param.name}}}", f"{example_value}")
                
        lines.append(f'url = "{url}"')
        lines.append("")
        
        # Handle headers
        lines.append("headers = {")
        lines.append('    "Content-Type": "application/json",')
        lines.append('    "Authorization": "Bearer YOUR_API_KEY"')
        lines.append("}")
        lines.append("")
        
        # Handle query parameters
        if query_params:
            lines.append("params = {")
            for param in query_params:
                example_value = self._get_example_value(param)
                lines.append(f'    "{param.name}": {example_value},')
            lines.append("}")
            lines.append("")
            
        # Handle request body
        if body_params and method in ["post", "put", "patch"]:
            lines.append("data = {")
            for param in body_params:
                example_value = self._get_example_value(param)
                lines.append(f'    "{param.name}": {example_value},')
            lines.append("}")
            lines.append("")
            
        # Make the request
        request_args = ["url", "headers=headers"]
        if query_params:
            request_args.append("params=params")
        if body_params and method in ["post", "put", "patch"]:
            request_args.append("json=data")
            
        lines.append(f"response = requests.{method}({', '.join(request_args)})")
        lines.append("")
        lines.append("if response.status_code == 200:")
        lines.append("    result = response.json()")
        lines.append("    print(json.dumps(result, indent=2))")
        lines.append("else:")
        lines.append("    print(f'Error: {response.status_code} - {response.text}')")
        
        return "\n".join(lines)
        
    def _generate_javascript_example(self, endpoint: Endpoint, base_url: str) -> str:
        """Generate JavaScript example using fetch API."""
        url = f"{base_url.rstrip('/')}{endpoint.path}"
        method = endpoint.method.value.upper()
        
        # Extract parameters
        query_params = [p for p in endpoint.parameters if p.location == "query"]
        path_params = [p for p in endpoint.parameters if p.location == "path"]
        body_params = [p for p in endpoint.parameters if p.location == "body"]
        
        lines = [
            "// API endpoint"
        ]
        
        # Handle path parameters
        if path_params:
            lines.append("// Replace path parameters with actual values")
            for param in path_params:
                example_value = self._get_example_value(param, quote_strings=False)
                url = url.replace(f"{{{param.name}}}", f"{example_value}")
                
        # Handle query parameters
        if query_params:
            lines.append("const params = new URLSearchParams({")
            for param in query_params:
                example_value = self._get_example_value(param)
                lines.append(f'  {param.name}: {example_value},')
            lines.append("});")
            url_with_params = f"{url}?${{params}}"
            lines.append(f'const url = `{url_with_params}`;')
        else:
            lines.append(f'const url = "{url}";')
            
        lines.append("")
        
        # Build fetch options
        lines.append("const options = {")
        lines.append(f'  method: "{method}",')
        lines.append("  headers: {")
        lines.append('    "Content-Type": "application/json",')
        lines.append('    "Authorization": "Bearer YOUR_API_KEY"')
        lines.append("  }")
        
        # Handle request body
        if body_params and method in ["POST", "PUT", "PATCH"]:
            lines.append(",")
            lines.append("  body: JSON.stringify({")
            for param in body_params:
                example_value = self._get_example_value(param)
                lines.append(f'    {param.name}: {example_value},')
            lines.append("  })")
            
        lines.append("};")
        lines.append("")
        
        # Make the request
        lines.extend([
            "fetch(url, options)",
            "  .then(response => {",
            "    if (!response.ok) {",
            "      throw new Error(`HTTP error! status: ${response.status}`);",
            "    }",
            "    return response.json();",
            "  })",
            "  .then(data => {",
            "    console.log('Success:', data);",
            "  })",
            "  .catch(error => {",
            "    console.error('Error:', error);",
            "  });"
        ])
        
        return "\n".join(lines)
        
    def _generate_curl_example(self, endpoint: Endpoint, base_url: str) -> str:
        """Generate curl command example."""
        url = f"{base_url.rstrip('/')}{endpoint.path}"
        method = endpoint.method.value.upper()
        
        # Extract parameters
        query_params = [p for p in endpoint.parameters if p.location == "query"]
        path_params = [p for p in endpoint.parameters if p.location == "path"]
        body_params = [p for p in endpoint.parameters if p.location == "body"]
        
        # Handle path parameters
        if path_params:
            for param in path_params:
                example_value = self._get_example_value(param, quote_strings=False)
                url = url.replace(f"{{{param.name}}}", str(example_value))
                
        # Handle query parameters
        if query_params:
            query_parts = []
            for param in query_params:
                example_value = self._get_example_value(param, quote_strings=False)
                query_parts.append(f"{param.name}={example_value}")
            url += "?" + "&".join(query_parts)
            
        lines = [f'curl -X {method} "{url}" \\']
        lines.append('  -H "Content-Type: application/json" \\')
        lines.append('  -H "Authorization: Bearer YOUR_API_KEY"')
        
        # Handle request body
        if body_params and method in ["POST", "PUT", "PATCH"]:
            body_obj = {}
            for param in body_params:
                example_value = self._get_example_value(param, quote_strings=False)
                body_obj[param.name] = example_value
                
            import json
            body_json = json.dumps(body_obj, indent=2)
            lines.append(f" \\\n  -d '{body_json}'")
            
        return "\n".join(lines)
        
    def _generate_java_example(self, endpoint: Endpoint, base_url: str) -> str:
        """Generate Java example using HttpClient."""
        url = f"{base_url.rstrip('/')}{endpoint.path}"
        method = endpoint.method.value.upper()
        
        lines = [
            "import java.net.http.HttpClient;",
            "import java.net.http.HttpRequest;", 
            "import java.net.http.HttpResponse;",
            "import java.net.URI;",
            "import java.time.Duration;",
            "",
            "public class ApiExample {",
            "    public static void main(String[] args) throws Exception {",
            "        HttpClient client = HttpClient.newBuilder()",
            "            .connectTimeout(Duration.ofSeconds(10))",
            "            .build();",
            "",
            f'        String url = "{url}";',
            "",
            "        HttpRequest.Builder requestBuilder = HttpRequest.newBuilder()",
            "            .uri(URI.create(url))",
            "            .header(\"Content-Type\", \"application/json\")",
            "            .header(\"Authorization\", \"Bearer YOUR_API_KEY\")",
            f"            .{method}();"
        ]
        
        # Handle request body for POST/PUT/PATCH
        body_params = [p for p in endpoint.parameters if p.location == "body"]
        if body_params and method in ["POST", "PUT", "PATCH"]:
            lines.append("")
            lines.append("        String requestBody = \"{")
            for i, param in enumerate(body_params):
                example_value = self._get_example_value(param)
                comma = "," if i < len(body_params) - 1 else ""
                lines.append(f'            \\"{param.name}\\": {example_value}{comma}')
            lines.append("        }\";")
            lines.append("")
            lines.append("        HttpRequest request = requestBuilder")
            lines.append("            .POST(HttpRequest.BodyPublishers.ofString(requestBody))")
            lines.append("            .build();")
        else:
            lines.append("")
            lines.append("        HttpRequest request = requestBuilder.build();")
            
        lines.extend([
            "",
            "        HttpResponse<String> response = client.send(request,",
            "            HttpResponse.BodyHandlers.ofString());",
            "",
            "        System.out.println(\"Status: \" + response.statusCode());",
            "        System.out.println(\"Response: \" + response.body());",
            "    }",
            "}"
        ])
        
        return "\n".join(lines)
        
    def _generate_csharp_example(self, endpoint: Endpoint, base_url: str) -> str:
        """Generate C# example using HttpClient."""
        url = f"{base_url.rstrip('/')}{endpoint.path}"
        method = endpoint.method.value.upper()
        
        lines = [
            "using System;",
            "using System.Net.Http;",
            "using System.Text;",
            "using System.Threading.Tasks;",
            "using Newtonsoft.Json;",
            "",
            "class Program",
            "{",
            "    private static readonly HttpClient client = new HttpClient();",
            "",
            "    static async Task Main(string[] args)",
            "    {",
            f'        string url = "{url}";',
            "",
            "        client.DefaultRequestHeaders.Add(\"Authorization\", \"Bearer YOUR_API_KEY\");",
            ""
        ]
        
        # Handle request body
        body_params = [p for p in endpoint.parameters if p.location == "body"]
        if body_params and method in ["POST", "PUT", "PATCH"]:
            lines.append("        var requestData = new {")
            for param in body_params:
                example_value = self._get_example_value(param, quote_strings=False)
                lines.append(f"            {param.name} = {example_value},")
            lines.append("        };")
            lines.append("")
            lines.append("        string json = JsonConvert.SerializeObject(requestData);")
            lines.append("        var content = new StringContent(json, Encoding.UTF8, \"application/json\");")
            lines.append("")
            lines.append(f"        HttpResponseMessage response = await client.{method.title()}Async(url, content);")
        else:
            lines.append(f"        HttpResponseMessage response = await client.{method.title()}Async(url);")
            
        lines.extend([
            "",
            "        if (response.IsSuccessStatusCode)",
            "        {",
            "            string responseBody = await response.Content.ReadAsStringAsync();",
            "            Console.WriteLine(responseBody);",
            "        }",
            "        else",
            "        {",
            "            Console.WriteLine($\"Error: {response.StatusCode}\");",
            "        }",
            "    }",
            "}"
        ])
        
        return "\n".join(lines)
        
    def _generate_php_example(self, endpoint: Endpoint, base_url: str) -> str:
        """Generate PHP example using cURL."""
        url = f"{base_url.rstrip('/')}{endpoint.path}"
        method = endpoint.method.value.upper()
        
        lines = [
            "<?php",
            "",
            f'$url = "{url}";',
            "",
            "$headers = [",
            "    'Content-Type: application/json',",
            "    'Authorization: Bearer YOUR_API_KEY'",
            "];",
            "",
            "$ch = curl_init();",
            "curl_setopt($ch, CURLOPT_URL, $url);",
            "curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);",
            "curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);"
        ]
        
        # Handle different HTTP methods
        if method != "GET":
            lines.append(f"curl_setopt($ch, CURLOPT_CUSTOMREQUEST, '{method}');")
            
        # Handle request body
        body_params = [p for p in endpoint.parameters if p.location == "body"]
        if body_params and method in ["POST", "PUT", "PATCH"]:
            lines.append("")
            lines.append("$data = [")
            for param in body_params:
                example_value = self._get_example_value(param)
                lines.append(f"    '{param.name}' => {example_value},")
            lines.append("];")
            lines.append("")
            lines.append("curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($data));")
            
        lines.extend([
            "",
            "$response = curl_exec($ch);",
            "$httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);",
            "",
            "if ($response === false) {",
            "    echo 'cURL Error: ' . curl_error($ch);",
            "} else {",
            "    echo 'HTTP Code: ' . $httpCode . PHP_EOL;",
            "    echo 'Response: ' . $response . PHP_EOL;",
            "}",
            "",
            "curl_close($ch);",
            "?>"
        ])
        
        return "\n".join(lines)
        
    def _generate_ruby_example(self, endpoint: Endpoint, base_url: str) -> str:
        """Generate Ruby example using Net::HTTP."""
        url = f"{base_url.rstrip('/')}{endpoint.path}"
        method = endpoint.method.value.lower()
        
        lines = [
            "require 'net/http'",
            "require 'json'",
            "require 'uri'",
            "",
            f"url = URI('{url}')",
            "",
            "http = Net::HTTP.new(url.host, url.port)",
            "http.use_ssl = true if url.scheme == 'https'",
            "",
            f"request = Net::HTTP::{method.capitalize()}.new(url)",
            "request['Content-Type'] = 'application/json'",
            "request['Authorization'] = 'Bearer YOUR_API_KEY'",
        ]
        
        # Handle request body
        body_params = [p for p in endpoint.parameters if p.location == "body"]
        if body_params and method in ["post", "put", "patch"]:
            lines.append("")
            lines.append("data = {")
            for param in body_params:
                example_value = self._get_example_value(param)
                lines.append(f"  {param.name}: {example_value},")
            lines.append("}")
            lines.append("")
            lines.append("request.body = data.to_json")
            
        lines.extend([
            "",
            "response = http.request(request)",
            "",
            "if response.code.to_i == 200",
            "  result = JSON.parse(response.body)",
            "  puts JSON.pretty_generate(result)",
            "else",
            "  puts \"Error: #{response.code} - #{response.body}\"",
            "end"
        ])
        
        return "\n".join(lines)
        
    def _get_example_value(self, param: Parameter, quote_strings: bool = True) -> str:
        """
        Get example value for a parameter.
        
        Args:
            param: Parameter to get example for
            quote_strings: Whether to quote string values
            
        Returns:
            Example value as string
        """
        if param.example is not None:
            if isinstance(param.example, str) and quote_strings:
                return f'"{param.example}"'
            return str(param.example)
            
        # Generate example based on type
        type_examples = {
            "string": '"example_value"' if quote_strings else 'example_value',
            "integer": "123",
            "number": "123.45", 
            "boolean": "true",
            "array": "[]",
            "object": "{}"
        }
        
        example = type_examples.get(param.type.lower(), '"example"' if quote_strings else 'example')
        
        # Handle enum values
        if param.enum_values and len(param.enum_values) > 0:
            first_enum = param.enum_values[0]
            if quote_strings and isinstance(first_enum, str):
                return f'"{first_enum}"'
            return str(first_enum)
            
        return example


def init_documentation_generator() -> DocumentationGenerator:
    """
    Initialize global documentation generator instance.
    
    Returns:
        Initialized documentation generator
    """
    global documentation_generator
    documentation_generator = DocumentationGenerator()
    return documentation_generator


def initialize_documentation_generator() -> None:
    """
    Initialize documentation generator for application startup.
    
    This function is called during application startup to ensure
    the documentation generator is properly configured and ready for use.
    """
    logger.info("Initializing documentation generator...")
    
    try:
        # Initialize the global generator
        generator = init_documentation_generator()
        
        # Validate that dependencies are available
        if generator.genai_client is None:
            logger.warning("GenAI client not available for documentation generator")
        
        if generator.prompt_engine is None:
            logger.warning("Prompt engine not available for documentation generator")
            
        if generator.spec_analyzer is None:
            logger.warning("Specification analyzer not available for documentation generator")
        
        logger.info("Documentation generator initialized successfully")
        
    except Exception as e:
        logger.error(f"Failed to initialize documentation generator: {e}")
        raise