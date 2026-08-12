"""Prompt template CRUD routes."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from streamdoc.api.schemas import (
    PromptTemplateCreate,
    PromptTemplateOut,
    PromptTemplateUpdate,
)
from streamdoc.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/prompts", tags=["prompts"])


def _get_manager():
    """Get the PromptManager instance."""
    from streamdoc.integrations.notebooklm.prompts import PromptManager
    return PromptManager(
        settings.notebooklm_templates_dir,
        settings.notebooklm_sample_prompts_dir,
    )


def _to_out(t) -> PromptTemplateOut:
    return PromptTemplateOut(
        name=t.name,
        description=t.description,
        target_types=[ct.value for ct in t.target_types],
        prompt=t.prompt,
        variables=t.variables,
    )


@router.get("", response_model=list[PromptTemplateOut])
def list_templates():
    """List all available prompt templates."""
    mgr = _get_manager()
    return [_to_out(t) for t in mgr.list_templates()]


@router.get("/{name}", response_model=PromptTemplateOut)
def get_template(name: str):
    """Get a single prompt template by name."""
    mgr = _get_manager()
    try:
        t = mgr.load_template(name)
        return _to_out(t)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Template '{name}' not found") from exc


@router.post("", response_model=PromptTemplateOut)
def create_template(body: PromptTemplateCreate):
    """Create a new prompt template."""
    from streamdoc.integrations.notebooklm.prompts import ContentType, PromptTemplate

    mgr = _get_manager()
    if body.name in mgr.get_template_names():
        raise HTTPException(status_code=409, detail=f"Template '{body.name}' already exists")

    target_types = []
    for t in body.target_types:
        try:
            target_types.append(ContentType(t))
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid content type: {t}")

    template = PromptTemplate(
        name=body.name,
        description=body.description,
        target_types=target_types,
        prompt=body.prompt,
        variables=body.variables,
    )

    try:
        mgr.save_template(template)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _to_out(template)


@router.put("/{name}", response_model=PromptTemplateOut)
def update_template(name: str, body: PromptTemplateUpdate):
    """Update an existing prompt template."""
    from streamdoc.integrations.notebooklm.prompts import ContentType, PromptTemplate

    mgr = _get_manager()
    try:
        existing = mgr.load_template(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Template '{name}' not found") from exc

    target_types = existing.target_types
    if body.target_types is not None:
        target_types = []
        for t in body.target_types:
            try:
                target_types.append(ContentType(t))
            except ValueError:
                raise HTTPException(status_code=422, detail=f"Invalid content type: {t}")

    template = PromptTemplate(
        name=name,
        description=body.description if body.description is not None else existing.description,
        target_types=target_types,
        prompt=body.prompt if body.prompt is not None else existing.prompt,
        variables=body.variables if body.variables is not None else existing.variables,
    )

    mgr.save_template(template)
    return _to_out(template)


@router.delete("/{name}")
def delete_template(name: str):
    """Delete a custom prompt template."""
    from pathlib import Path

    mgr = _get_manager()
    if not mgr.templates_dir:
        raise HTTPException(status_code=400, detail="Templates directory not configured")

    template_file: Path = mgr.templates_dir / f"{name}.yaml"
    if not template_file.exists():
        raise HTTPException(status_code=404, detail=f"Template file '{name}' not found")

    template_file.unlink()

    # Reason: remove from in-memory cache if present
    if name in mgr._templates:
        del mgr._templates[name]

    return {"deleted": name}
