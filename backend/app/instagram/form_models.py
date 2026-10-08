import secrets
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Boolean, Text, DateTime,
    ForeignKey, JSON, Numeric, Index,
)
from sqlalchemy.orm import relationship
from ..db.base import Base


class IGForm(Base):
    __tablename__ = "ig_forms"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ig_account_id = Column(Integer, ForeignKey("ig_accounts.id", ondelete="CASCADE"), nullable=True)
    name = Column(String(100), nullable=False, unique=True)
    display_name = Column(String(100), nullable=False)
    description = Column(Text, default="")
    form_type = Column(String(20), default="simple")
    ai_prompt_hint = Column(Text, default="")
    success_message = Column(Text, default="Thank you! Your submission has been received.")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    fields = relationship("IGFormField", back_populates="form", cascade="all, delete-orphan", order_by="IGFormField.sort_order")
    submissions = relationship("IGFormSubmission", back_populates="form", cascade="all, delete-orphan")


class IGFormField(Base):
    __tablename__ = "ig_form_fields"
    id = Column(Integer, primary_key=True, autoincrement=True)
    form_id = Column(Integer, ForeignKey("ig_forms.id", ondelete="CASCADE"), nullable=False)
    field_key = Column(String(50), nullable=False)
    label = Column(String(100), nullable=False)
    field_type = Column(String(20), default="text")
    required = Column(Boolean, default=True)
    options = Column(JSON, default=list)
    placeholder = Column(String(200), default="")
    phase = Column(Integer, default=1)
    sort_order = Column(Integer, default=0)
    ai_extract_hint = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    form = relationship("IGForm", back_populates="fields")


class IGFormSubmission(Base):
    __tablename__ = "ig_form_submissions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    form_id = Column(Integer, ForeignKey("ig_forms.id"), nullable=False)
    conversation_id = Column(Integer, ForeignKey("ig_conversations.id"), nullable=True)
    ig_user_id = Column(String(100), nullable=False)
    phase1_data = Column(JSON, default=dict)
    phase2_data = Column(JSON, default=dict)
    status = Column(String(20), default="partial")
    current_field_index = Column(Integer, default=0)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=True)
    # unguessable id for the public hosted-form link; the sequential id is
    # never accepted there
    public_token = Column(String(64), nullable=True, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    form = relationship("IGForm", back_populates="submissions")
    conversation = relationship("IGConversation", backref="form_submissions")
    lead = relationship("Lead", backref="form_submissions")

    __table_args__ = (
        Index("ix_form_submission_conv", "conversation_id", "status"),
    )


def new_public_token() -> str:
    return secrets.token_urlsafe(24)
