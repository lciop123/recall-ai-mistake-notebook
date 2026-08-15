# -*- coding: utf-8 -*-
"""相似题检索与人工确认后的重复题合并。"""
from __future__ import annotations

import json
import re
from collections import Counter

from sqlmodel import Session, select

from app.ai import embedding_service
from app.core.exceptions import AppError
from app.models.models import Question, ReviewLog, ReviewSession, get_engine
from app.services.question_service import _norm_text, _to_out


def _tokens(text: str) -> set[str]:
    normalized = _norm_text(text)
    chinese_pairs = {normalized[index:index + 2] for index in range(max(0, len(normalized) - 1))}
    words = set(re.findall(r"[a-z0-9]+", normalized))
    return chinese_pairs | words


def _jaccard(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    return len(a & b) / len(a | b) if a and b else 0.0


def similar_questions(question_id: int, limit: int = 5) -> list[dict]:
    limit = max(1, min(int(limit), 20))
    with Session(get_engine()) as session:
        target = session.get(Question, question_id)
        if not target:
            raise AppError(40400, "错题不存在", 404)
        rows = session.exec(select(Question).where(Question.id != question_id)).all()
    embedding_ids = embedding_service.search(target.question_text, top_k=limit + 4) or []
    embedded_rank = {qid: index for index, qid in enumerate(embedding_ids) if qid != question_id}
    candidates = []
    for row in rows:
        lexical = _jaccard(target.question_text, row.question_text)
        same_point = bool(target.knowledge_point and target.knowledge_point == row.knowledge_point)
        vector_score = 1 - embedded_rank[row.id] / max(1, len(embedded_rank)) if row.id in embedded_rank else 0
        score = max(lexical, vector_score * 0.72, 0.45 if same_point else 0)
        if score < 0.18 and not same_point and row.id not in embedded_rank:
            continue
        reasons = []
        if same_point:
            reasons.append("同一知识点")
        if lexical >= 0.28:
            reasons.append("题干文字相近")
        if row.id in embedded_rank:
            reasons.append("语义相近")
        candidates.append({**_to_out(row), "similarity": round(score, 2), "reasons": reasons or ["主题相近"]})
    return sorted(candidates, key=lambda item: item["similarity"], reverse=True)[:limit]


def merge_duplicate(primary_id: int, duplicate_id: int) -> dict:
    if primary_id == duplicate_id:
        raise AppError(40001, "主题和重复题不能相同", 400)
    with Session(get_engine()) as session:
        primary = session.get(Question, primary_id)
        duplicate = session.get(Question, duplicate_id)
        if not primary or not duplicate:
            raise AppError(40400, "待合并错题不存在", 404)
        # 未提交会话里可能存有重复题 id；先阻止合并，避免之后提交时引用已删除题。
        active_sessions = session.exec(select(ReviewSession).where(ReviewSession.submitted_at == None)).all()
        for row in active_sessions:
            try:
                questions = json.loads(row.questions_json)
            except (TypeError, ValueError):
                continue
            if any(isinstance(item, dict) and duplicate_id in {item.get("id"), item.get("origin_id")} for item in questions):
                raise AppError(40900, "该重复题正在未完成练习中，请先完成或重新生成练习后再合并", 409)
        # 主题缺失的信息仅从重复项补齐，不覆盖用户在主题上已经维护的内容。
        for field in ("answer", "analysis", "knowledge_point", "error_detail", "image_path"):
            if not getattr(primary, field) and getattr(duplicate, field):
                setattr(primary, field, getattr(duplicate, field))
        logs = session.exec(select(ReviewLog).where(ReviewLog.question_id == duplicate_id)).all()
        for log in logs:
            log.question_id = primary_id
            session.add(log)
        session.add(primary)
        session.delete(duplicate)
        session.commit()
        session.refresh(primary)
    embedding_service.delete_question(duplicate_id)
    embedding_service.upsert_question(primary_id, primary.question_text)
    return {"primary": _to_out(primary), "merged_question_id": duplicate_id, "migrated_review_logs": len(logs)}
