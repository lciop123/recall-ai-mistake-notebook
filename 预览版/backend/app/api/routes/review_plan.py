# -*- coding: utf-8 -*-
from datetime import date

from fastapi import APIRouter

from app.api import ok
from app.schemas.schemas import PlanComplete, ExamPlan
from app.services import plan_service

router = APIRouter(prefix="/api/review-plan", tags=["review-plan"])


@router.get("/daily")
def daily(d: str | None = None, subject: str | None = None, limit: int = 20,
          knowledge_point: str | None = None):
    try:
        day = date.fromisoformat(d) if d else None
    except ValueError:
        from app.core.exceptions import AppError
        raise AppError(40001, "日期格式应为 YYYY-MM-DD", 400)
    return ok(plan_service.daily(day, subject, limit, knowledge_point))


@router.get("/calendar")
def calendar(month: str | None = None, subject: str | None = None):
    return ok(plan_service.calendar(month, subject))


@router.post("/complete")
def complete(data: PlanComplete):
    return ok(plan_service.complete(data.question_id, data.quality))


@router.post("/exam")
def exam(data: ExamPlan):
    return ok(plan_service.exam_plan(data.exam_date))


@router.get("/weekly")
def weekly():
    return ok(plan_service.weekly())
