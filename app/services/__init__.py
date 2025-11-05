"""
Services package for the Spec Documentation API.
Contains business logic and external service integrations.
"""

from .genai_client import (
    GenAIClient,
    GenAIRequest,
    GenAIResponse,
    GenAIError,
    GenAITimeoutError,
    GenAIServiceUnavailableError,
    GenAIRateLimitError,
    get_genai_client,
    init_genai_client
)

from .prompt_templates import (
    PromptTemplateEngine,
    SpecificationAnalyzer,
    DocumentationSection,
    SpecificationType,
    PromptContext,
    get_prompt_engine,
    get_spec_analyzer
)

from .documentation_generator import (
    DocumentationGenerator,
    DocumentationRequest,
    DocumentationResult,
    OutputFormat,
    get_documentation_generator,
    init_documentation_generator
)

from .quality_scorer import (
    QualityScorer,
    get_quality_scorer,
    init_quality_scorer
)

from .quality_service import (
    QualityService,
    create_quality_service
)

__all__ = [
    # GenAI Client
    "GenAIClient",
    "GenAIRequest", 
    "GenAIResponse",
    "GenAIError",
    "GenAITimeoutError",
    "GenAIServiceUnavailableError",
    "GenAIRateLimitError",
    "get_genai_client",
    "init_genai_client",
    
    # Prompt Templates
    "PromptTemplateEngine",
    "SpecificationAnalyzer", 
    "DocumentationSection",
    "SpecificationType",
    "PromptContext",
    "get_prompt_engine",
    "get_spec_analyzer",
    
    # Documentation Generator
    "DocumentationGenerator",
    "DocumentationRequest",
    "DocumentationResult", 
    "OutputFormat",
    "get_documentation_generator",
    "init_documentation_generator",
    
    # Quality Scorer
    "QualityScorer",
    "get_quality_scorer",
    "init_quality_scorer",
    
    # Quality Service
    "QualityService",
    "create_quality_service"
]