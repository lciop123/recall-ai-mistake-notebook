# -*- coding: utf-8 -*-
from fastapi import APIRouter, Query, UploadFile, File

from app.api import ok
from app.schemas.schemas import DuplicateMerge, QuestionBulkUpdate, QuestionCreate, QuestionUpdate
from app.services import question_service, similarity_service
from app.services.chat_service import save_image

router = APIRouter(prefix="/api/questions", tags=["questions"])

ALLOWED_IMG = {"image/jpeg", "image/png", "image/webp"}
MAX_IMG = 4 * 1024 * 1024


@router.patch("/bulk")
def bulk_update(data: QuestionBulkUpdate):
    payload = data.model_dump(exclude={"ids"}, exclude_none=True)
    return ok(question_service.bulk_update(data.ids, payload))


@router.post("/image")
async def upload_image(file: UploadFile = File(...)):
    """题目配图上传（立体几何等带图题）"""
    if file.content_type not in ALLOWED_IMG:
        return {"code": 40001, "message": "仅支持 jpg/png/webp 格式", "data": None}
    data = await file.read()
    if len(data) > MAX_IMG:
        return {"code": 40001, "message": "图片大小超过 4MB", "data": None}
    return ok(save_image(data, file.content_type))


@router.post("/classify-preview")
def classify_preview(body: dict):
    return ok(question_service.classify_preview(str(body.get("question_text") or "")))


@router.post("")
def create_question(data: QuestionCreate, auto_classify: bool = Query(False)):
    return ok(question_service.create_question(data, auto_classify=auto_classify))


@router.get("")
def list_questions(
    notebook_id: int | None = None, subject: str | None = None,
    knowledge_point: str | None = None, error_type: str | None = None,
    mastery: int | None = None, keyword: str | None = None,
    page: int = 1, page_size: int = 20,
    sort_by: str = "created_at", order: str = "desc",
):
    return ok(question_service.list_questions(notebook_id, subject, knowledge_point, error_type,
                                              mastery, keyword, page, page_size, sort_by, order))


@router.get("/search")
def search(q: str, limit: int = 20):
    return ok(question_service.search_questions(q, limit))


@router.get("/{qid}/similar")
def similar_questions(qid: int, limit: int = 5):
    return ok(similarity_service.similar_questions(qid, limit))


@router.delete("/by-subject/{subject}")
def delete_by_subject(subject: str):
    n = question_service.delete_by_subject(subject)
    return ok({"deleted": n}, f"已删除「{subject}错题本」，共 {n} 道错题")


@router.get("/{qid}")
def get_question(qid: int):
    return ok(question_service.get_question(qid))


@router.patch("/{qid}")
def update_question(qid: int, data: QuestionUpdate):
    return ok(question_service.update_question(qid, data))


@router.post("/merge-duplicate")
def merge_duplicate(data: DuplicateMerge):
    return ok(similarity_service.merge_duplicate(data.primary_id, data.duplicate_id), "已合并重复题")


@router.delete("/{qid}")
def delete_question(qid: int):
    question_service.delete_question(qid)
    return ok(None, "已删除")
