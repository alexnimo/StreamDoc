"""Retention policy management for NotebookLM content."""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from streamdoc.db import Base
from streamdoc.integrations.notebooklm.exceptions import NotebookLMRetentionError

if TYPE_CHECKING:
    from streamdoc.integrations.notebooklm.client import NotebookLMClientWrapper


class NotebookLMContent(Base):
    """Database model for tracked NotebookLM content.
    
    This model tracks notebooks and their generated content for
    retention policy enforcement.
    """
    __tablename__ = "notebooklm_content"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("jobs.id"), nullable=True)
    preset_name: Mapped[str] = mapped_column(String(255))
    
    # Notebook info
    notebook_id: Mapped[str] = mapped_column(String(64), index=True)
    notebook_title: Mapped[str] = mapped_column(String(255))
    notebook_share_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    
    # Retention settings
    is_permanent: Mapped[bool] = mapped_column(Boolean, default=False)
    retention_hours: Mapped[float] = mapped_column(Float, default=24.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    
    # Artifacts (JSON: [{"type": "slide_deck", "id": "...", "local_path": "..."}])
    artifacts: Mapped[str] = mapped_column(Text, default="[]")
    
    # Status: active | expired | deleted
    status: Mapped[str] = mapped_column(String(32), default="active")
    
    def is_expired(self) -> bool:
        """Check if content has expired based on retention policy."""
        if self.is_permanent or self.status != "active":
            return False
        if not self.expires_at:
            self.expires_at = self.created_at + timedelta(hours=self.retention_hours)
        return datetime.utcnow() > self.expires_at
    
    def get_artifacts(self) -> list[dict]:
        """Parse artifacts JSON to list."""
        try:
            return json.loads(self.artifacts)
        except json.JSONDecodeError:
            return []
    
    def set_artifacts(self, artifacts: list[dict]) -> None:
        """Set artifacts list as JSON."""
        self.artifacts = json.dumps(artifacts)


class NotebookLMRetentionLog(Base):
    """Log of retention policy actions."""
    __tablename__ = "notebooklm_retention_log"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    content_id: Mapped[str] = mapped_column(String(36), ForeignKey("notebooklm_content.id"))
    action: Mapped[str] = mapped_column(String(32))  # deleted | extended | permanent
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)


@dataclass
class CleanupReport:
    """Report of retention cleanup operations.
    
    Attributes:
        deleted_notebooks: List of deleted notebook IDs
        deleted_artifacts: List of deleted artifact IDs
        deleted_local_files: List of deleted local file paths
        errors: List of errors encountered
        total_checked: Total number of content entries checked
    """
    deleted_notebooks: list[str] = field(default_factory=list)
    deleted_artifacts: list[str] = field(default_factory=list)
    deleted_local_files: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    total_checked: int = 0
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "deleted_notebooks": self.deleted_notebooks,
            "deleted_artifacts": self.deleted_artifacts,
            "deleted_local_files": self.deleted_local_files,
            "errors": self.errors,
            "total_checked": self.total_checked
        }


class RetentionManager:
    """Manages content retention policies for NotebookLM integration.
    
    This class handles:
    - Tracking content creation and expiration
    - Automatic cleanup of expired content
    - Extending retention for specific content
    - Marking content as permanent
    
    Args:
        client_wrapper: NotebookLM client wrapper for API calls
        db_session: SQLAlchemy database session
        default_retention_hours: Default retention period
    """
    
    def __init__(
        self,
        client_wrapper: "NotebookLMClientWrapper",
        db_session,
        default_retention_hours: float = 24.0
    ):
        self.client_wrapper = client_wrapper
        self.db_session = db_session
        self.default_retention_hours = default_retention_hours
    
    def register_notebook(
        self,
        notebook_id: str,
        title: str,
        preset_name: str,
        job_id: str | None = None,
        is_permanent: bool = False,
        retention_hours: float | None = None,
        share_url: str | None = None
    ) -> NotebookLMContent:
        """Register a new notebook for retention tracking.
        
        Args:
            notebook_id: NotebookLM notebook ID
            title: Notebook title
            preset_name: Associated preset name
            job_id: Optional job ID
            is_permanent: Whether to skip retention cleanup
            retention_hours: Custom retention period (uses default if not set)
            share_url: Share URL for the notebook
            
        Returns:
            Created NotebookLMContent record
        """
        hours = retention_hours or self.default_retention_hours
        
        if is_permanent:
            expires_at = None
        else:
            expires_at = datetime.utcnow() + timedelta(hours=hours)
        
        content = NotebookLMContent(
            id=str(uuid4()),
            job_id=job_id,
            preset_name=preset_name,
            notebook_id=notebook_id,
            notebook_title=title,
            notebook_share_url=share_url,
            is_permanent=is_permanent,
            retention_hours=hours,
            expires_at=expires_at,
            status="active"
        )
        
        self.db_session.add(content)
        self.db_session.commit()
        
        return content
    
    def register_artifact(
        self,
        content_id: str,
        artifact_type: str,
        artifact_id: str,
        local_path: Path | None = None
    ) -> None:
        """Register an artifact for a tracked notebook.
        
        Args:
            content_id: NotebookLMContent record ID
            artifact_type: Type of artifact (slide_deck, podcast, etc.)
            artifact_id: NotebookLM artifact ID
            local_path: Local file path if downloaded
        """
        content = self.db_session.query(NotebookLMContent).get(content_id)
        if not content:
            raise NotebookLMRetentionError(f"Content '{content_id}' not found")
        
        artifacts = content.get_artifacts()
        artifacts.append({
            "type": artifact_type,
            "id": artifact_id,
            "local_path": str(local_path) if local_path else None
        })
        content.set_artifacts(artifacts)
        
        self.db_session.commit()
    
    def get_active_content(self) -> list[NotebookLMContent]:
        """Get all active (non-deleted) tracked content.
        
        Returns:
            List of active NotebookLMContent records
        """
        return (
            self.db_session.query(NotebookLMContent)
            .filter(NotebookLMContent.status == "active")
            .all()
        )
    
    def get_expired_content(self) -> list[NotebookLMContent]:
        """Get content that has expired based on retention policy.
        
        Returns:
            List of expired NotebookLMContent records
        """
        all_active = self.get_active_content()
        return [c for c in all_active if c.is_expired()]
    
    async def cleanup_expired(
        self,
        dry_run: bool = False,
        delete_remote: bool = True,
        delete_local: bool = True
    ) -> CleanupReport:
        """Clean up expired content.
        
        This method:
        1. Finds all expired content
        2. Deletes artifacts from NotebookLM (if delete_remote)
        3. Deletes local downloaded files (if delete_local)
        4. Updates database records
        
        Args:
            dry_run: If True, only report what would be deleted
            delete_remote: Whether to delete from NotebookLM
            delete_local: Whether to delete local files
            
        Returns:
            CleanupReport with results
        """
        report = CleanupReport()
        expired = self.get_expired_content()
        report.total_checked = len(self.get_active_content())
        
        for content in expired:
            try:
                # Delete artifacts from NotebookLM
                if delete_remote and not dry_run:
                    artifacts = content.get_artifacts()
                    for artifact in artifacts:
                        try:
                            await self.client_wrapper.artifacts.delete(
                                content.notebook_id,
                                artifact["id"]
                            )
                            report.deleted_artifacts.append(artifact["id"])
                        except Exception as e:
                            report.errors.append(
                                f"Failed to delete artifact {artifact['id']}: {e}"
                            )
                    
                    # Delete the notebook itself
                    try:
                        await self.client_wrapper.notebooks.delete(content.notebook_id)
                        report.deleted_notebooks.append(content.notebook_id)
                    except Exception as e:
                        report.errors.append(
                            f"Failed to delete notebook {content.notebook_id}: {e}"
                        )
                else:
                    # Dry run - just record what would be deleted
                    artifacts = content.get_artifacts()
                    for artifact in artifacts:
                        report.deleted_artifacts.append(artifact["id"])
                    report.deleted_notebooks.append(content.notebook_id)
                
                # Delete local files
                if delete_local or dry_run:
                    artifacts = content.get_artifacts()
                    for artifact in artifacts:
                        local_path = artifact.get("local_path")
                        if local_path:
                            path = Path(local_path)
                            if path.exists() and not dry_run:
                                path.unlink()
                            report.deleted_local_files.append(str(local_path))
                
                # Update database record
                if not dry_run:
                    content.status = "deleted"
                    
                    # Log the action
                    log = NotebookLMRetentionLog(
                        content_id=content.id,
                        action="deleted",
                        details=f"Expired after {content.retention_hours} hours"
                    )
                    self.db_session.add(log)
                    self.db_session.commit()
                    
            except Exception as e:
                report.errors.append(f"Failed to cleanup content {content.id}: {e}")
        
        if not dry_run:
            self.db_session.commit()
        
        return report
    
    def extend_retention(
        self,
        content_id: str,
        hours: float
    ) -> NotebookLMContent:
        """Extend retention period for content.
        
        Args:
            content_id: NotebookLMContent record ID
            hours: New retention period from now
            
        Returns:
            Updated NotebookLMContent record
            
        Raises:
            NotebookLMRetentionError: If content not found
        """
        content = self.db_session.query(NotebookLMContent).get(content_id)
        if not content:
            raise NotebookLMRetentionError(f"Content '{content_id}' not found")
        
        if content.is_permanent:
            raise NotebookLMRetentionError("Cannot extend permanent content")
        
        content.retention_hours = hours
        content.expires_at = datetime.utcnow() + timedelta(hours=hours)
        
        # Log the action
        log = NotebookLMRetentionLog(
            content_id=content.id,
            action="extended",
            details=f"Extended to {hours} hours"
        )
        self.db_session.add(log)
        self.db_session.commit()
        
        return content
    
    def mark_permanent(self, content_id: str) -> NotebookLMContent:
        """Mark content as permanent (no retention cleanup).
        
        Args:
            content_id: NotebookLMContent record ID
            
        Returns:
            Updated NotebookLMContent record
            
        Raises:
            NotebookLMRetentionError: If content not found
        """
        content = self.db_session.query(NotebookLMContent).get(content_id)
        if not content:
            raise NotebookLMRetentionError(f"Content '{content_id}' not found")
        
        content.is_permanent = True
        content.expires_at = None
        
        # Log the action
        log = NotebookLMRetentionLog(
            content_id=content.id,
            action="permanent",
            details="Marked as permanent"
        )
        self.db_session.add(log)
        self.db_session.commit()
        
        return content
    
    def get_content_by_notebook_id(
        self,
        notebook_id: str
    ) -> NotebookLMContent | None:
        """Get tracked content by NotebookLM notebook ID.
        
        Args:
            notebook_id: NotebookLM notebook ID
            
        Returns:
            NotebookLMContent record or None
        """
        return (
            self.db_session.query(NotebookLMContent)
            .filter(NotebookLMContent.notebook_id == notebook_id)
            .first()
        )
    
    def get_content_by_job(
        self,
        job_id: str
    ) -> list[NotebookLMContent]:
        """Get all tracked content for a job.
        
        Args:
            job_id: Job ID
            
        Returns:
            List of NotebookLMContent records
        """
        return (
            self.db_session.query(NotebookLMContent)
            .filter(NotebookLMContent.job_id == job_id)
            .all()
        )
