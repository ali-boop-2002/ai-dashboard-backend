from sqlalchemy import Column, String, Integer, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, index=True)
    filename = Column(String, nullable=True)
    content_type = Column(String, nullable=True)
    source_type = Column(String, nullable=True)
    chunk_count = Column(Integer, nullable=False)
    uploader_id = Column(String, nullable=False, index=True)
    uploader_email = Column(String, nullable=True)
    pdf_sha256 = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
