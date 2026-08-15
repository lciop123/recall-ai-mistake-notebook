# -*- coding: utf-8 -*-
from fastapi import APIRouter, UploadFile, File

from app.api import ok
from app.schemas.schemas import CaptureImport
from app.services import capture_service

router = APIRouter(prefix="/api/capture", tags=["capture"])

ALLOWED = {"image/jpeg", "image/png", "image/webp"}
MAX_SIZE = 2 * 1024 * 1024  # 2MB


@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    if file.content_type not in ALLOWED:
        return {"code": 40001, "message": "仅支持 jpg/png/webp 格式", "data": None}
    data = await file.read()
    if len(data) > MAX_SIZE:
        return {"code": 40001, "message": "图片大小超过 2MB，请压缩后上传", "data": None}
    task_id = capture_service.create_task(data, file.filename or "")
    return ok({"task_id": task_id})


@router.get("/tasks/{task_id}")
def get_task(task_id: str):
    return ok(capture_service.get_task(task_id))


@router.post("/import")
def import_selected(data: CaptureImport):
    result = capture_service.import_selected(data.task_id, data.question_ids)
    return ok(result, f"已导入 {result['imported']} 道错题")
