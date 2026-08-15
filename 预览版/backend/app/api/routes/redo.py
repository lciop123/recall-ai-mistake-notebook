# -*- coding: utf-8 -*-
from fastapi import APIRouter

from app.api import ok
from app.schemas.schemas import RedoGradeRequest, RedoTypeRequest
from app.services import redo_service

router = APIRouter(prefix="/api/redo", tags=["redo"])


@router.post("/type")
def judge_type(data: RedoTypeRequest):
    """AI 判断题型：choice/fill/essay（选择题附带选项）"""
    return ok(redo_service.judge_type(data.question_id))


@router.post("/grade")
def grade(data: RedoGradeRequest):
    """批改：文本或手写图片作答；返回步骤反馈并写入一条复习记录。"""
    return ok(redo_service.grade(data.question_id, data.answer, data.image_path, data.type,
                                 data.subject, data.review_type))
