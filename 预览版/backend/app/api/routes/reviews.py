# -*- coding: utf-8 -*-
from fastapi import APIRouter

from app.api import ok
from app.schemas.schemas import ExamGenerate, ReviewGenerate, ReviewSubmit
from app.services import review_service

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


@router.post("/generate")
def generate(data: ReviewGenerate):
    return ok(review_service.generate(data.notebook_id, data.subject, data.count))


@router.post("/exam/generate")
def generate_exam(data: ExamGenerate):
    return ok(review_service.generate_exam(data.exam_date, data.subject, data.count))


@router.post("/{review_id}/submit")
def submit(review_id: str, data: ReviewSubmit):
    answers = {a.question_id: a.answer for a in data.answers}
    return ok(review_service.submit(review_id, answers))


@router.get("/history")
def history(page: int = 1, page_size: int = 20):
    return ok(review_service.history(page, page_size))


@router.post("/{review_id}/add-question")
def add_question(review_id: str, body: dict):
    return ok(review_service.add_question(review_id, int(body.get("question_id"))), "已加入错题本")
