"""Prompt template management for NotebookLM content generation."""

import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


class ContentType(str, Enum):
    """Supported content generation types."""
    SLIDE_DECK = "slide_deck"
    PODCAST = "podcast"  # audio overview
    INFOGRAPHIC = "infographic"
    REPORT = "report"
    INTERACTIVE_DASHBOARD = "interactive_dashboard"


@dataclass
class PromptTemplate:
    """A prompt template for content generation.
    
    Attributes:
        name: Template identifier
        description: Human-readable description
        target_types: Content types this template supports
        prompt: The prompt template string with {variable} placeholders
        variables: Default values for template variables
        template_kind: Discriminator between "content" prompts and "design"
            prompts. Only "content" and "design" are valid values.
    """
    name: str
    description: str
    target_types: list[ContentType] = field(default_factory=list)
    prompt: str = ""
    variables: dict[str, Any] = field(default_factory=dict)
    template_kind: str = "content"
    
    def render(self, content_type: ContentType, **variables) -> str:
        """Render the prompt template with variables.
        
        Args:
            content_type: The type of content being generated
            **variables: Additional template variables
            
        Returns:
            Rendered prompt string
            
        Raises:
            ValueError: If content_type not in target_types
        """
        if content_type not in self.target_types:
            raise ValueError(
                f"Template '{self.name}' does not support content type '{content_type}'"
            )
        
        # Merge default variables with provided ones
        merged_vars = {**self.variables, **variables}
        merged_vars["content_type"] = content_type.value
        
        return self.prompt.format(**merged_vars)


class PromptManager:
    """Manages prompt template loading and selection.
    
    This class handles loading templates from YAML files and provides
    methods for listing, selecting, and rendering templates.
    
    Args:
        templates_dir: Directory containing template YAML files
    """
    
    DEFAULT_TEMPLATES = {
        "financial_extraction": PromptTemplate(
            name="financial_extraction",
            description="Extract financial data, recommendations, and insights from video content",
            target_types=[ContentType.SLIDE_DECK, ContentType.INFOGRAPHIC, ContentType.REPORT],
            prompt="""Analyze this content and create a {content_type} that:
- Extracts all financial data, metrics, and key statistics
- Highlights investment recommendations and actionable insights
- Identifies market trends and predictions mentioned
- Disregards commercial content, advertisements, and promotional material
- Excludes irrelevant personal anecdotes or entertainment segments
- Focuses on substantive business and financial information

Format the output as a professional financial analysis suitable for investors.

Additional context: {context}
""",
            variables={"context": ""}
        ),
        "design_guidelines": PromptTemplate(
            name="design_guidelines",
            description="Visual design patterns for artifact generation",
            target_types=[ContentType.SLIDE_DECK, ContentType.INFOGRAPHIC],
            prompt="""When creating the visual design for this {content_type}:
- Use clean, professional layouts with consistent spacing
- Prioritize data visualization for financial metrics
- Use color schemes appropriate for business presentations
- Ensure text is readable and information hierarchy is clear
- Include charts/graphs where data supports it

Design style: {style}
""",
            variables={"style": "professional corporate"}
        ),
        "default": PromptTemplate(
            name="default",
            description="Default template for general content generation",
            target_types=[ContentType.SLIDE_DECK, ContentType.PODCAST, ContentType.INFOGRAPHIC, ContentType.REPORT],
            prompt="""Create a {content_type} based on the provided content.

Focus on:
- Key insights and main points
- Clear and concise presentation
- Professional quality output

Context: {context}
""",
            variables={"context": "YouTube video analysis"}
        )
    }
    
    def __init__(
        self,
        templates_dir: Path | str | None = None,
        sample_prompts_dir: Path | str | None = None,
    ):
        """Initialize the prompt manager.

        Args:
            templates_dir: Directory for user prompt templates (read + write).
                If empty, sample templates are copied here from sample_prompts_dir.
            sample_prompts_dir: Directory containing shipped sample templates
                (read-only). Defaults to assets/prompts/notebooklm.
        """
        self.templates_dir = Path(templates_dir) if templates_dir else None
        self.sample_prompts_dir = (
            Path(sample_prompts_dir) if sample_prompts_dir else None
        )
        self._templates: dict[str, PromptTemplate] = dict(self.DEFAULT_TEMPLATES)
        self._seed_from_samples()
        self._load_custom_templates()

    def _seed_from_samples(self) -> None:
        """Seed the templates directory from sample prompts on first run.

        If templates_dir exists but has no .yaml files, copy all .yaml files
        from sample_prompts_dir. This gives users a starting set of prompts
        in their gitignored config/ directory without polluting tracked files.
        User edits and new prompts stay in config/ and are never committed.
        """
        if not self.templates_dir or not self.sample_prompts_dir:
            return
        if not self.sample_prompts_dir.exists():
            return

        # Reason: only seed if the target dir is empty (first run or fresh clone).
        # If the user deleted all prompts, we respect that — no re-seeding.
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        existing = list(self.templates_dir.glob("*.yaml"))
        if existing:
            return

        for sample_file in self.sample_prompts_dir.glob("*.yaml"):
            dest = self.templates_dir / sample_file.name
            shutil.copy2(sample_file, dest)

    def _load_custom_templates(self) -> None:
        """Load custom templates from templates directory."""
        if not self.templates_dir or not self.templates_dir.exists():
            return
        
        for template_file in self.templates_dir.glob("*.yaml"):
            try:
                with open(template_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                
                if not data or "name" not in data:
                    continue
                
                # Convert target_types strings to ContentType enums
                target_types = []
                for t in data.get("target_types", []):
                    try:
                        target_types.append(ContentType(t))
                    except ValueError:
                        pass
                
                template = PromptTemplate(
                    name=data["name"],
                    description=data.get("description", ""),
                    target_types=target_types,
                    prompt=data.get("prompt", ""),
                    variables=data.get("variables", {}),
                    template_kind=data.get("template_kind", "content")
                )
                
                self._templates[template.name] = template
            except Exception:
                # Skip invalid templates
                continue
    
    def load_template(self, name: str) -> PromptTemplate:
        """Load a template by name.
        
        Args:
            name: Template identifier
            
        Returns:
            PromptTemplate instance
            
        Raises:
            KeyError: If template not found
        """
        if name not in self._templates:
            raise KeyError(f"Template '{name}' not found")
        return self._templates[name]
    
    def list_templates(
        self,
        content_type: ContentType | None = None
    ) -> list[PromptTemplate]:
        """List available templates, optionally filtered by content type.
        
        Args:
            content_type: Optional filter for content type support
            
        Returns:
            List of matching templates
        """
        templates = list(self._templates.values())
        
        if content_type:
            templates = [
                t for t in templates
                if content_type in t.target_types
            ]
        
        return sorted(templates, key=lambda t: t.name)
    
    def get_default_template(self, content_type: ContentType) -> PromptTemplate:
        """Get the default template for a content type.
        
        Priority:
        1. First template specifically for this content type
        2. Default template
        
        Args:
            content_type: Type of content to generate
            
        Returns:
            Default PromptTemplate for the content type
        """
        # Try content-specific defaults
        if content_type == ContentType.SLIDE_DECK:
            try:
                return self.load_template("financial_extraction")
            except KeyError:
                pass
        
        # Fall back to default
        return self._templates.get("default", list(self._templates.values())[0])
    
    def render_prompt(
        self,
        template_name: str,
        content_type: ContentType,
        **variables
    ) -> str:
        """Render a prompt from a template.
        
        Args:
            template_name: Name of template to use
            content_type: Type of content being generated
            **variables: Template variables
            
        Returns:
            Rendered prompt string
        """
        template = self.load_template(template_name)
        return template.render(content_type, **variables)
    
    def save_template(self, template: PromptTemplate) -> None:
        """Save a template to the templates directory.
        
        Args:
            template: Template to save
        """
        if not self.templates_dir:
            raise ValueError("Templates directory not configured")
        
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        
        template_file = self.templates_dir / f"{template.name}.yaml"
        
        data = {
            "name": template.name,
            "description": template.description,
            "target_types": [t.value for t in template.target_types],
            "prompt": template.prompt,
            "variables": template.variables,
            "template_kind": template.template_kind
        }
        
        with open(template_file, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
        
        # Update in-memory cache
        self._templates[template.name] = template
    
    def get_template_names(self) -> list[str]:
        """Get list of available template names.
        
        Returns:
            List of template identifiers
        """
        return list(self._templates.keys())
