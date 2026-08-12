"""
Output artifact ORM model.
"""
from sqlalchemy.orm import Mapped, mapped_column

from streamdoc.db import Base


class Output(Base):
    __tablename__ = "outputs"

    id: Mapped[str] = mapped_column(primary_key=True)
    video_id: Mapped[str] = mapped_column(default="")
    kind: Mapped[str] = mapped_column(default="pdf")
    path: Mapped[str] = mapped_column(default="")
    bytes: Mapped[int | None] = mapped_column(default=None)
    created_at: Mapped[str] = mapped_column(default="")
