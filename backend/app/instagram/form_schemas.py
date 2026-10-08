from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


# ── Form ─────────────────────────────────────────────────────────
class IGFormFieldInput(BaseModel):
    field_key: str
    label: str
    field_type: str = "text"
    required: bool = True
    options: list = []
    placeholder: str = ""
    phase: int = 1
    sort_order: int = 0
    ai_extract_hint: str = ""


class IGFormCreate(BaseModel):
    name: str
    display_name: str
    description: str = ""
    form_type: str = "simple"
    ai_prompt_hint: str = ""
    success_message: str = "Thank you! Your submission has been received."
    is_active: bool = True
    fields: List[IGFormFieldInput] = []


class IGFormUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    form_type: Optional[str] = None
    ai_prompt_hint: Optional[str] = None
    success_message: Optional[str] = None
    is_active: Optional[bool] = None


class IGFormFieldResponse(BaseModel):
    id: int
    field_key: str
    label: str
    field_type: str
    required: bool
    options: list
    placeholder: str
    phase: int
    sort_order: int
    ai_extract_hint: str

    class Config:
        from_attributes = True


class IGFormResponse(BaseModel):
    id: int
    name: str
    display_name: str
    description: str
    form_type: str
    ai_prompt_hint: str
    success_message: str
    is_active: bool
    fields: List[IGFormFieldResponse] = []
    submission_count: int = 0
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class IGFormUpdateFields(BaseModel):
    fields: List[IGFormFieldInput]


# ── Submissions ──────────────────────────────────────────────────
class IGFormSubmissionResponse(BaseModel):
    id: int
    form_id: int
    form_name: str = ""
    conversation_id: Optional[int]
    ig_user_id: str
    phase1_data: dict
    phase2_data: dict
    status: str
    lead_id: Optional[int]
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class IGFormPhase2Submit(BaseModel):
    phase2_data: dict = Field(default_factory=dict, max_length=50)
