# -*- coding: utf-8 -*-
import json

from fastapi import APIRouter, UploadFile, File
from fastapi.responses import StreamingResponse

from app.api import ok
from app.services import chat_service
from app.core.config import llm_models

router = APIRouter(prefix="/api/chat", tags=["chat"])

ALLOWED = {"image/jpeg", "image/png", "image/webp"}
MAX_SIZE = 4 * 1024 * 1024  # 4MB


@router.get("/conversations")
def list_conversations():
    return ok(chat_service.list_conversations())


@router.post("/conversations")
def create_conversation():
    return ok(chat_service.create_conversation())


@router.post("/conversations/inherit")
def create_inherited_conversation(body: dict):
    """创建继承上下文的新会话：模型记住源会话最近 N 条，界面从空白开始。"""
    from_id = int(body.get("from_id") or 0)
    if not from_id:
        return {"code": 40001, "message": "缺少源会话 id", "data": None}
    last_count = int(body.get("last_count") or 20)
    return ok(chat_service.create_inherited_conversation(from_id, last_count))


@router.get("/conversations/{conv_id}/messages")
def messages(conv_id: int):
    return ok(chat_service.get_messages(conv_id))


@router.delete("/conversations/{conv_id}")
def delete(conv_id: int):
    chat_service.delete_conversation(conv_id)
    return ok(None, "已删除")


@router.post("/conversations/{conv_id}/regenerate")
def regenerate(conv_id: int, body: dict):
    """重新生成：删除指定 AI 消息及其后消息，返回最后一条用户消息"""
    return ok(chat_service.regenerate(conv_id, int(body.get("message_id"))))


@router.post("/images")
async def upload_image(file: UploadFile = File(...)):
    """上传对话图片，返回可访问路径（给 AI 看图用）"""
    if file.content_type not in ALLOWED:
        return {"code": 40001, "message": "仅支持 jpg/png/webp 格式", "data": None}
    data = await file.read()
    if len(data) > MAX_SIZE:
        return {"code": 40001, "message": "图片大小超过 4MB，请压缩后上传", "data": None}
    return ok(chat_service.save_image(data, file.content_type))


@router.get("/models")
def models():
    return ok(llm_models())


@router.post("/solve")
async def solve(body: dict):
    """一次性求解（数学题专用）：后端完成生成+工具+复核，返回完整结果"""
    conv_id = body.get("conversation_id")
    content = (body.get("message") or "").strip()
    image_path = (body.get("image_path") or "").strip() or None
    thinking = body.get("thinking") if body.get("thinking") in ("off", "standard", "deep") else "standard"
    model_key = body.get("model") if body.get("model") in ("main", "alt") else "main"
    temperature = float(body.get("temperature", 0.3)) if isinstance(body.get("temperature"), (int, float)) else 0.3
    detail = body.get("detail") if body.get("detail") in ("brief", "standard", "detailed") else "standard"
    use_my_questions = bool(body.get("use_my_questions", True))
    question_text = (body.get("question_text") or "").strip() or None
    if not content and not image_path:
        return {"code": 40001, "message": "请输入问题或上传图片", "data": None}
    result = await chat_service.solve_question(
        conv_id, content, image_path=image_path, thinking=thinking,
        model_key=model_key, temperature=temperature,
        detail=detail, use_my_questions=use_my_questions,
        question_text=question_text)
    return ok(result)


@router.post("/solve-stream")
async def solve_stream(body: dict):
    """求解 SSE：阶段即时反馈 + 复核完成后平滑输出终稿。"""
    conv_id = body.get("conversation_id")
    content = (body.get("message") or "").strip()
    image_path = (body.get("image_path") or "").strip() or None
    thinking = body.get("thinking") if body.get("thinking") in ("off", "standard", "deep") else "standard"
    model_key = body.get("model") if body.get("model") in ("main", "alt") else "main"
    temperature = float(body.get("temperature", 0.3)) if isinstance(body.get("temperature"), (int, float)) else 0.3
    detail = body.get("detail") if body.get("detail") in ("brief", "standard", "detailed") else "standard"
    use_my_questions = bool(body.get("use_my_questions", True))
    question_text = (body.get("question_text") or "").strip() or None
    if not content and not image_path:
        return {"code": 40001, "message": "请输入问题或上传图片", "data": None}
    return StreamingResponse(
        chat_service.stream_solve_question(
            conv_id, content, image_path=image_path, thinking=thinking,
            model_key=model_key, temperature=temperature, detail=detail,
            use_my_questions=use_my_questions, question_text=question_text),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/stream")
async def stream(body: dict):
    conv_id = body.get("conversation_id")
    content = (body.get("message") or "").strip()
    image_path = (body.get("image_path") or "").strip() or None
    thinking = body.get("thinking") if body.get("thinking") in ("off", "standard", "deep") else "off"
    model_key = body.get("model") if body.get("model") in ("main", "alt") else "main"
    temperature = float(body.get("temperature", 0.3)) if isinstance(body.get("temperature"), (int, float)) else 0.3
    detail = body.get("detail") if body.get("detail") in ("brief", "standard", "detailed") else "standard"
    use_my_questions = bool(body.get("use_my_questions", True))
    if not content and not image_path:
        return {"code": 40001, "message": "请输入问题或上传图片", "data": None}
    return StreamingResponse(
        chat_service.stream_chat(conv_id, content, image_path=image_path, thinking=thinking,
                                 model_key=model_key, temperature=temperature,
                                 detail=detail, use_my_questions=use_my_questions),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/conversations/{conv_id}/added-questions")
def added_questions(conv_id: int):
    return ok(chat_service.added_questions(conv_id))


@router.post("/conversations/{conv_id}/add-question")
def add_question(conv_id: int, body: dict):
    return ok(chat_service.add_question(conv_id, body.get("message_id")))
