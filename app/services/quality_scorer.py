"""
Quality scoring service for evaluating documentation quality.
"""
import logging
import re
from typing import Dict, List, Optional
from uuid import UUID

from app.models.quality import (
    QualityMetrics,
    QualityFeedback,
    QualityMetricType,
    QualityScore,
    QualityTrend
)

logger = logging.getLogger(__name__)


class QualityScorer:
    """Service for calculating documentation quality scores."""
    
    def __init__(self):
        """Initialize the quality scorer."""
        self.logger = logging.getLogger(__name__)
    
    def calculate_quality_metrics(
        self,
        documentation: str,
        specification: Dict,
        spec_format: str
    ) -> QualityMetrics:
        """
        Calculate quality metrics for generated documentation.
        
        Args:
            documentation: Generated documentation content
            specification: Original specification data
            spec_format: Format of the specification (openapi, graphql, etc.)
            
        Returns:
            QualityMetrics with scores and feedback
        """
        self.logger.info(f"Calculating quality metrics for {spec_format} documentation")
        
        # Calculate individual metric scores
        completeness_score = self._calculate_completeness(documentation, specification, spec_format)
        clarity_score = self._calculate_clarity(documentation)
        accuracy_score = self._calculate_accuracy(documentation, specification, spec_format)
        
        # Generate feedback for each metric
        feedback = []
        feedback.extend(self._generate_completeness_feedback(completeness_score, documentation, specification))
        feedback.extend(self._generate_clarity_feedback(clarity_score, documentation))
        feedback.extend(self._generate_accuracy_feedback(accuracy_score, documentation, specification))
        
        return QualityMetrics(
            completeness=completeness_score,
            clarity=clarity_score,
            accuracy=accuracy_score,
            feedback=feedback
        )
    
    def _calculate_completeness(self, documentation: str, specification: Dict, spec_format: str) -> int:
        """
        Calculate completeness score based on coverage of specification elements.
        
        Args:
            documentation: Generated documentation content
            specification: Original specification data
            spec_format: Format of the specification
            
        Returns:
            Completeness score (0-100)
        """
        score = 0
        max_score = 100
        
        # Check for essential documentation sections
        essential_sections = [
            "overview", "introduction", "description",
            "endpoint", "api", "method",
            "parameter", "response", "example"
        ]
        
        doc_lower = documentation.lower()
        sections_found = sum(1 for section in essential_sections if section in doc_lower)
        section_score = min(40, (sections_found / len(essential_sections)) * 40)
        score += section_score
        
        # Check specification-specific completeness
        if spec_format == "openapi":
            score += self._check_openapi_completeness(documentation, specification)
        elif spec_format == "graphql":
            score += self._check_graphql_completeness(documentation, specification)
        else:
            score += 30  # Default score for other formats
        
        # Check for code examples
        code_patterns = [r'```\w+', r'`[^`]+`', r'curl\s+', r'POST\s+', r'GET\s+']
        code_examples = sum(1 for pattern in code_patterns if re.search(pattern, documentation))
        example_score = min(30, code_examples * 10)
        score += example_score
        
        return min(max_score, int(score))
    
    def _calculate_clarity(self, documentation: str) -> int:
        """
        Calculate clarity score based on readability and structure.
        
        Args:
            documentation: Generated documentation content
            
        Returns:
            Clarity score (0-100)
        """
        score = 0
        
        # Check for proper structure (headers, lists, etc.)
        structure_patterns = [
            r'^#+\s+',  # Headers
            r'^\*\s+',  # Bullet points
            r'^\d+\.\s+',  # Numbered lists
            r'^\|\s+',  # Tables
        ]
        
        lines = documentation.split('\n')
        structured_lines = 0
        for line in lines:
            if any(re.match(pattern, line.strip()) for pattern in structure_patterns):
                structured_lines += 1
        
        if lines:
            structure_score = min(30, (structured_lines / len(lines)) * 100)
            score += structure_score
        
        # Check sentence length (shorter sentences are clearer)
        sentences = re.split(r'[.!?]+', documentation)
        if sentences:
            avg_sentence_length = sum(len(s.split()) for s in sentences) / len(sentences)
            # Optimal sentence length is 15-20 words
            if avg_sentence_length <= 20:
                length_score = 25
            elif avg_sentence_length <= 30:
                length_score = 15
            else:
                length_score = 5
            score += length_score
        
        # Check for technical jargon explanation
        jargon_indicators = ['i.e.', 'e.g.', 'that is', 'in other words', 'specifically']
        jargon_score = min(25, sum(5 for indicator in jargon_indicators if indicator in documentation.lower()))
        score += jargon_score
        
        # Check for consistent formatting
        consistency_score = 20  # Base score, could be enhanced with more sophisticated checks
        score += consistency_score
        
        return min(100, int(score))
    
    def _calculate_accuracy(self, documentation: str, specification: Dict, spec_format: str) -> int:
        """
        Calculate accuracy score based on alignment with specification.
        
        Args:
            documentation: Generated documentation content
            specification: Original specification data
            spec_format: Format of the specification
            
        Returns:
            Accuracy score (0-100)
        """
        score = 80  # Base accuracy score
        
        # Check for specification-specific accuracy
        if spec_format == "openapi" and isinstance(specification, dict):
            score += self._check_openapi_accuracy(documentation, specification)
        elif spec_format == "graphql":
            score += self._check_graphql_accuracy(documentation, specification)
        
        # Check for common accuracy issues
        doc_lower = documentation.lower()
        
        # Penalize for placeholder text
        placeholders = ['todo', 'tbd', 'placeholder', 'example.com', 'lorem ipsum']
        placeholder_penalty = sum(5 for placeholder in placeholders if placeholder in doc_lower)
        score -= placeholder_penalty
        
        # Penalize for inconsistent terminology
        # This is a simplified check - could be enhanced with NLP
        if 'api' in doc_lower and 'endpoint' in doc_lower:
            score += 5  # Bonus for consistent API terminology
        
        return max(0, min(100, int(score)))
    
    def _check_openapi_completeness(self, documentation: str, specification: Dict) -> int:
        """Check OpenAPI-specific completeness."""
        score = 0
        doc_lower = documentation.lower()
        
        # Check if paths are documented
        if 'paths' in specification:
            paths_documented = sum(1 for path in specification['paths'].keys() 
                                 if path.lower() in doc_lower)
            if specification['paths']:
                score += (paths_documented / len(specification['paths'])) * 20
        
        # Check if components/schemas are documented
        if 'components' in specification and 'schemas' in specification['components']:
            schemas = specification['components']['schemas']
            schemas_documented = sum(1 for schema in schemas.keys() 
                                   if schema.lower() in doc_lower)
            if schemas:
                score += (schemas_documented / len(schemas)) * 10
        
        return min(30, int(score))
    
    def _check_graphql_completeness(self, documentation: str, specification: Dict) -> int:
        """Check GraphQL-specific completeness."""
        score = 20  # Base score for GraphQL
        doc_lower = documentation.lower()
        
        # Check for GraphQL-specific terms
        graphql_terms = ['query', 'mutation', 'subscription', 'type', 'field']
        terms_found = sum(1 for term in graphql_terms if term in doc_lower)
        score += (terms_found / len(graphql_terms)) * 10
        
        return min(30, int(score))
    
    def _check_openapi_accuracy(self, documentation: str, specification: Dict) -> int:
        """Check OpenAPI-specific accuracy."""
        score = 0
        
        # Check if HTTP methods are correctly documented
        if 'paths' in specification:
            for path_data in specification['paths'].values():
                for method in path_data.keys():
                    if method.upper() in documentation.upper():
                        score += 2
        
        return min(20, int(score))
    
    def _check_graphql_accuracy(self, documentation: str, specification: Dict) -> int:
        """Check GraphQL-specific accuracy."""
        return 15  # Base accuracy score for GraphQL
    
    def _generate_completeness_feedback(
        self, 
        score: int, 
        documentation: str, 
        specification: Dict
    ) -> List[QualityFeedback]:
        """Generate feedback for completeness score."""
        suggestions = []
        
        if score < 70:
            suggestions.append("Add more detailed descriptions for API endpoints")
            suggestions.append("Include more code examples in different programming languages")
        
        if score < 50:
            suggestions.append("Ensure all specification elements are documented")
            suggestions.append("Add comprehensive parameter and response descriptions")
        
        return [QualityFeedback(
            metric_type=QualityMetricType.COMPLETENESS,
            score=score,
            suggestions=suggestions,
            details={"section": "completeness_analysis"}
        )]
    
    def _generate_clarity_feedback(self, score: int, documentation: str) -> List[QualityFeedback]:
        """Generate feedback for clarity score."""
        suggestions = []
        
        if score < 70:
            suggestions.append("Use shorter, more concise sentences")
            suggestions.append("Add more structure with headers and bullet points")
        
        if score < 50:
            suggestions.append("Explain technical terms and jargon")
            suggestions.append("Improve formatting and organization")
        
        return [QualityFeedback(
            metric_type=QualityMetricType.CLARITY,
            score=score,
            suggestions=suggestions,
            details={"section": "clarity_analysis"}
        )]
    
    def _generate_accuracy_feedback(
        self, 
        score: int, 
        documentation: str, 
        specification: Dict
    ) -> List[QualityFeedback]:
        """Generate feedback for accuracy score."""
        suggestions = []
        
        if score < 70:
            suggestions.append("Verify all endpoint descriptions match the specification")
            suggestions.append("Remove placeholder text and ensure all examples are valid")
        
        if score < 50:
            suggestions.append("Review parameter types and response formats for accuracy")
            suggestions.append("Ensure consistent terminology throughout the documentation")
        
        return [QualityFeedback(
            metric_type=QualityMetricType.ACCURACY,
            score=score,
            suggestions=suggestions,
            details={"section": "accuracy_analysis"}
        )]


# Global instance
_quality_scorer: Optional[QualityScorer] = None


def get_quality_scorer() -> QualityScorer:
    """Get the global quality scorer instance."""
    global _quality_scorer
    if _quality_scorer is None:
        _quality_scorer = QualityScorer()
    return _quality_scorer


def init_quality_scorer() -> QualityScorer:
    """Initialize and return a new quality scorer instance."""
    global _quality_scorer
    _quality_scorer = QualityScorer()
    return _quality_scorer