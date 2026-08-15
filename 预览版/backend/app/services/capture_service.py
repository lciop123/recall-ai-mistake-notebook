# -*- coding: utf-8 -*-
"""识图录入：异步任务（内存队列），OCR → DeepSeek 拆分多题 → 勾选导入"""
import threading
import uuid
from datetime import datetime

from app.ai import deepseek_client, ocr_service
from app.core.exceptions import AppError
from sqlmodel import Session, select
from app.models.models import get_engine, Question
from app.services import question_service

# task_id -> {"status": processing/done/failed, "message": str, "questions": [...], "progress": str}
_tasks: dict = {}
_lock = threading.Lock()


def _gen_task_id() -> str:
    return uuid.uuid4().hex[:12]


def create_task(image_bytes: bytes, filename: str = "") -> str:
    task_id = _gen_task_id()
    _tasks[task_id] = {
        "status": "processing", "message": "图片已上传，准备识别…", "questions": [],
        "progress": "图片已上传，正在准备双模型识别", "stage": "prepare", "elapsed_hint": "通常约 30-60 秒",
    }
    t = threading.Thread(target=_run_task, args=(task_id, image_bytes), daemon=True)
    t.start()
    return task_id


def _run_task(task_id: str, image_bytes: bytes):
    try:
        with _lock:
            _tasks[task_id].update({
                "progress": "正在并行调用 OCR 模型，优先采用最快两路结果", "stage": "ocr",
                "elapsed_hint": "正在识别公式、图形和题干…",
            })
        text, conf, srcs = ocr_service.recognize_cross(image_bytes)
        text = text or ""
        with _lock:
            source_text = " + ".join(srcs) if srcs else "可用模型"
            confidence_text = "结果一致" if conf == "high" else "已完成交叉核对，建议导入前快速检查"
            _tasks[task_id].update({
                "progress": f"OCR 完成（{source_text}，{confidence_text}），正在拆分题目", "stage": "split",
                "elapsed_hint": "正在识别每道题的边界与答案…",
            })
        questions = deepseek_client.split_questions(text)
        with _lock:
            _tasks[task_id].update({
                "progress": "正在归类知识点、错因并检查重复题", "stage": "classify",
                "elapsed_hint": "马上完成…",
            })
        if not questions:
            raise AppError(50300, "未能从图片中拆分出题目，请重拍或改用文本录入", 422)
        # 补临时 id，并标记是否已存在于错题本（重复的默认不勾选）
        from app.services.question_service import _norm_text
        with Session(get_engine()) as s:
            existing = [(q.id, _norm_text(q.question_text)) for q in s.exec(select(Question)).all()]
        existing_norm = {n for _, n in existing}
        for idx, q in enumerate(questions):
            q["temp_id"] = idx + 1
            q["question_text"] = deepseek_client.latex_friendly(q.get("question_text", "") or "")
            q["answer"] = deepseek_client.latex_friendly(q.get("answer", "") or "")
            q["analysis"] = deepseek_client.latex_friendly(q.get("analysis", "") or "")
            q["exists"] = _norm_text(q.get("question_text", "")) in existing_norm
        with _lock:
            _tasks[task_id].update({
                "status": "done", "message": f"识别完成，共 {len(questions)} 道题",
                "progress": "识别与归类完成", "stage": "done", "elapsed_hint": "可检查并导入题目",
                "questions": questions,
            })
    except Exception as e:
        with _lock:
            _tasks[task_id].update({
                "status": "failed", "message": str(getattr(e, "message", e)),
                "stage": "failed", "elapsed_hint": "可重新上传或改用文本录入",
            })
        # 清理过期任务（保留最近 50 个）
        if len(_tasks) > 50:
            for k in list(_tasks.keys())[:len(_tasks) - 50]:
                _tasks.pop(k, None)


def get_task(task_id: str) -> dict:
    with _lock:
        task = _tasks.get(task_id)
    if not task:
        raise AppError(40400, "识别任务不存在或已过期", 404)
    return {k: v for k, v in task.items()}


def import_selected(task_id: str, question_ids: list) -> dict:
    with _lock:
        task = _tasks.get(task_id)
        if not task or task["status"] != "done":
            raise AppError(40001, "识别任务未完成或已失效，请重新上传", 400)
        questions = task["questions"]
    imported = 0
    skipped = 0
    for q in questions:
        if q["temp_id"] not in question_ids:
            continue
        try:
            question_service.create_from_extract(q)
            imported += 1
        except AppError as e:
            if e.code == 40900:
                skipped += 1  # 已在错题本中，跳过
            else:
                raise
    if imported == 0 and skipped == 0:
        raise AppError(40001, "请至少选择一道题", 400)
    return {"imported": imported, "skipped": skipped}
