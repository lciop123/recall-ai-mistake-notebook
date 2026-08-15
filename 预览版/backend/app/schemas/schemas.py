# -*- coding: utf-8 -*-
from pydantic import BaseModel, Field
from typing import Literal, Optional, List
from datetime import datetime

from app.models.models import SUBJECTS, ERROR_TYPES, DIFFICULTIES, NOTEBOOK_COLORS


# ---------- 统一响应 ----------
class ApiResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: Optional[object] = None


# ---------- 错题本 ----------
class NotebookCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    color: str = "#007AFF"


class NotebookUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None


# ---------- 错题 ----------
class QuestionCreate(BaseModel):
    notebook_id: Optional[int] = None
    subject: str = "其他"
    knowledge_point: str = ""
    error_type: str = "其他"
    error_detail: str = ""
    difficulty: str = "中"
    question_text: str = Field(min_length=1)
    answer: str = ""
    analysis: str = ""
    image_path: Optional[str] = None


class QuestionUpdate(BaseModel):
    notebook_id: Optional[int] = None
    subject: Optional[str] = None
    knowledge_point: Optional[str] = None
    error_type: Optional[str] = None
    error_detail: Optional[str] = None
    difficulty: Optional[str] = None
    question_text: Optional[str] = None
    answer: Optional[str] = None
    analysis: Optional[str] = None
    image_path: Optional[str] = None


class QuestionBulkUpdate(BaseModel):
    ids: List[int] = Field(min_length=1, max_length=200)
    subject: Optional[str] = None
    knowledge_point: Optional[str] = Field(default=None, max_length=64)
    error_type: Optional[str] = None
    difficulty: Optional[str] = None


class DuplicateMerge(BaseModel):
    primary_id: int = Field(gt=0)
    duplicate_id: int = Field(gt=0)


class RedoTypeRequest(BaseModel):
    question_id: int = Field(gt=0)


class RedoGradeRequest(BaseModel):
    question_id: int = Field(gt=0)
    answer: str = ""
    image_path: Optional[str] = None
    type: Literal["choice", "fill", "essay"] = "fill"
    subject: str = ""
    review_type: Literal["redo", "daily", "exam"] = "redo"


class QuestionOut(BaseModel):
    id: int
    notebook_id: Optional[int]
    subject: str
    knowledge_point: str
    error_type: str
    error_detail: str = ""
    difficulty: str
    question_text: str
    answer: str
    analysis: str
    mastery_level: int
    next_review_at: Optional[datetime]
    created_at: datetime


class PageOut(BaseModel):
    items: list
    total: int
    page: int
    page_size: int


# ---------- 识图录入 ----------
class CaptureImport(BaseModel):
    task_id: str
    question_ids: List[int] = Field(min_length=1)


# ---------- 复习 ----------
class ReviewGenerate(BaseModel):
    notebook_id: Optional[int] = None
    subject: Optional[str] = None
    count: int = Field(default=5, ge=1, le=20)


class AnswerItem(BaseModel):
    question_id: int
    answer: str


class ReviewSubmit(BaseModel):
    answers: List[AnswerItem] = Field(min_length=1)


class PlanComplete(BaseModel):
    question_id: int
    quality: int = Field(ge=0, le=5)


class ExamPlan(BaseModel):
    exam_date: datetime


class ExamGenerate(BaseModel):
    exam_date: str = Field(min_length=10, max_length=10)
    subject: Optional[str] = None
    count: int = Field(default=10, ge=1, le=30)
