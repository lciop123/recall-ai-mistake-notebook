# -*- coding: utf-8 -*-
from datetime import datetime
import json

from sqlmodel import Session, select, func

from app.ai import deepseek_client, embedding_service
from app.core.exceptions import AppError
from app.models.models import get_engine, Question, Notebook, ReviewLog, ReviewSession
from app.schemas.schemas import QuestionCreate, QuestionUpdate


def _to_out(q: Question) -> dict:
    return {
        "id": q.id, "notebook_id": q.notebook_id, "subject": q.subject,
        "knowledge_point": q.knowledge_point, "error_type": q.error_type,
        "error_detail": q.error_detail, "difficulty": q.difficulty, "question_text": q.question_text,
        "answer": q.answer, "analysis": q.analysis, "mastery_level": q.mastery_level,
        "image_path": q.image_path,
        "image_url": f"/images/{q.image_path}" if q.image_path else None,
        "next_review_at": str(q.next_review_at) if q.next_review_at else None,
        "created_at": str(q.created_at),
    }


def _normalize_question_fields(data: dict) -> dict:
    """统一清洗数学文本与受控分类，避免录入入口污染统计。"""
    from app.services.taxonomy_service import normalize_question_payload
    out = dict(data)
    for field in ("question_text", "answer", "analysis"):
        if field in out and out[field] is not None:
            out[field] = deepseek_client.normalize_math_text(out[field])
    return normalize_question_payload(out)


def classify_preview(question_text: str) -> dict:
    """纯 AI 归类预览，不写入题库也不触发向量索引。"""
    text = deepseek_client.normalize_math_text(question_text or "").strip()
    if not text:
        raise AppError(40001, "题干不能为空", 400)
    info = deepseek_client.classify(text)
    if not info:
        raise AppError(50300, "AI 归类暂不可用，请稍后重试或手动填写", 503)
    return _normalize_question_fields(info)


def create_question(data: QuestionCreate, auto_classify: bool = False) -> dict:
    payload = _normalize_question_fields(data.model_dump())
    supplied = data.model_fields_set
    with Session(get_engine()) as s:
        q = Question(**payload)
        if auto_classify:
            try:
                classified = classify_preview(q.question_text)
            except AppError:
                classified = None
            if classified:
                # 只补充请求未提供的默认字段，不覆盖用户明确选择的“其他”等分类。
                if "subject" not in supplied or not q.subject:
                    q.subject = classified["subject"]
                if "knowledge_point" not in supplied or not q.knowledge_point:
                    q.knowledge_point = classified["knowledge_point"]
                if "error_type" not in supplied or not q.error_type:
                    q.error_type = classified["error_type"]
                    q.error_detail = classified.get("error_detail", q.error_detail)
                if "difficulty" not in supplied:
                    q.difficulty = classified["difficulty"]
        s.add(q)
        s.commit()
        s.refresh(q)
        qid = q.id
        text = q.question_text
    embedding_service.upsert_question(qid, text)
    return _to_out(q)


DIFF_ORDER = {"易": 1, "中": 2, "难": 3}


def list_questions(notebook_id=None, subject=None, knowledge_point=None, error_type=None,
                   mastery=None, keyword=None, page: int = 1, page_size: int = 20,
                   sort_by: str = "created_at", order: str = "desc") -> dict:
    with Session(get_engine()) as s:
        conds = []
        if notebook_id:
            conds.append(Question.notebook_id == notebook_id)
        if subject:
            conds.append(Question.subject == subject)
        if knowledge_point:
            conds.append(Question.knowledge_point == knowledge_point)
        if error_type:
            conds.append(Question.error_type == error_type)
        if mastery is not None:
            conds.append(Question.mastery_level == mastery)
        if keyword:
            conds.append(Question.question_text.contains(keyword)
                         | Question.knowledge_point.contains(keyword)
                         | Question.subject.contains(keyword)
                         | Question.answer.contains(keyword))
        total = s.exec(select(func.count(Question.id)).where(*conds)).one()
        stmt = select(Question).where(*conds)
        # 排序：录入时间 / 难度（易=1 中=2 难=3）
        if sort_by == "difficulty":
            from sqlalchemy import case
            sort_col = case((Question.difficulty == "易", 1), (Question.difficulty == "中", 2),
                            (Question.difficulty == "难", 3), else_=2)
            stmt = stmt.order_by(sort_col.desc() if order == "desc" else sort_col.asc(),
                                 Question.created_at.desc())
        else:
            stmt = stmt.order_by(Question.created_at.desc() if order == "desc" else Question.created_at.asc())
        rows = s.exec(stmt.offset((page - 1) * page_size).limit(page_size)).all()
        return {"items": [_to_out(q) for q in rows], "total": total, "page": page, "page_size": page_size}



def search_questions(q: str, limit: int = 20) -> list:
    # 语义搜索优先；embedding 不可用时降级 LIKE
    ids = embedding_service.search(q, top_k=limit) if q else None
    with Session(get_engine()) as s:
        if ids:
            rows = [q for i in ids if (q := s.get(Question, i)) is not None]
            return [_to_out(x) for x in rows[:limit]]
        rows = s.exec(select(Question).where(
            Question.question_text.contains(q)
            | Question.knowledge_point.contains(q)
            | Question.subject.contains(q)
            | Question.answer.contains(q)
        ).order_by(Question.created_at.desc()).limit(limit)).all()
        return [_to_out(x) for x in rows]


def get_question(qid: int) -> dict:
    with Session(get_engine()) as s:
        q = s.get(Question, qid)
        if not q:
            raise AppError(40400, "错题不存在", 404)
        return _to_out(q)


def update_question(qid: int, data: QuestionUpdate) -> dict:
    with Session(get_engine()) as s:
        q = s.get(Question, qid)
        if not q:
            raise AppError(40400, "错题不存在", 404)
        payload = _normalize_question_fields(data.model_dump(exclude_unset=True))
        for k, v in payload.items():
            setattr(q, k, v)
        q.updated_at = datetime.now()
        s.add(q)
        s.commit()
        s.refresh(q)
        text = q.question_text
    embedding_service.upsert_question(qid, text)
    return _to_out(q)


def bulk_update(ids: list[int], data: dict) -> dict:
    """批量修改安全元数据；题干、答案与图片只允许逐题编辑。"""
    allowed = {key: value for key, value in data.items() if key in {"subject", "knowledge_point", "error_type", "difficulty"} and value is not None}
    if not allowed:
        raise AppError(40001, "请至少选择一个需要修改的字段", 400)
    allowed = _normalize_question_fields(allowed)
    with Session(get_engine()) as session:
        rows = session.exec(select(Question).where(Question.id.in_(ids))).all()
        found = {row.id for row in rows}
        for row in rows:
            for key, value in allowed.items():
                setattr(row, key, value)
            row.updated_at = datetime.now()
            session.add(row)
        session.commit()
    return {"updated": len(found), "skipped_ids": sorted(set(ids) - found)}


def _is_in_active_review(session: Session, question_id: int) -> bool:
    for row in session.exec(select(ReviewSession).where(ReviewSession.submitted_at == None)).all():
        try:
            questions = json.loads(row.questions_json)
        except (TypeError, ValueError):
            continue
        if any(isinstance(item, dict) and question_id in {item.get("id"), item.get("origin_id")} for item in questions):
            return True
    return False


def delete_question(qid: int):
    with Session(get_engine()) as s:
        q = s.get(Question, qid)
        if not q:
            raise AppError(40400, "错题不存在", 404)
        if _is_in_active_review(s, qid):
            raise AppError(40900, "该错题正在未完成练习中，请先完成或重新生成练习后再删除", 409)
        for log in s.exec(select(ReviewLog).where(ReviewLog.question_id == qid)).all():
            s.delete(log)
        s.delete(q)
        s.commit()
    embedding_service.delete_question(qid)


def delete_by_subject(subject: str) -> int:
    """删除某学科错题本（该学科全部错题 + 对应 notebook 记录），返回删除题数"""
    from app.models.models import Notebook
    deleted = 0
    with Session(get_engine()) as s:
        qs = s.exec(select(Question).where(Question.subject == subject)).all()
        qids = [q.id for q in qs]
        if any(_is_in_active_review(s, qid) for qid in qids):
            raise AppError(40900, "该学科有错题正在未完成练习中，请先完成或重新生成练习后再删除", 409)
        if qids:
            for log in s.exec(select(ReviewLog).where(ReviewLog.question_id.in_(qids))).all():
                s.delete(log)
        for q in qs:
            s.delete(q)
            deleted += 1
        nb = s.exec(select(Notebook).where(Notebook.name == subject + "错题本")).first()
        if nb:
            s.delete(nb)
        s.commit()
    for q in qs:
        embedding_service.delete_question(q.id)
    return deleted


def create_from_extract(data: dict, notebook_id: int | None = None, source: str = "manual", source_message_id: int | None = None) -> dict:
    """对话/识别导入共用：data 为结构化错题 dict。
    统一兜底：修复 LaTeX 控制字符 + 查重（字符串归一化 + AI 语义查重，重复则抛 409）。"""
    from app.ai.deepseek_client import normalize_math_text, semantic_duplicate
    from app.services.taxonomy_service import normalize_question_payload
    data = normalize_question_payload(data)
    question_text = normalize_math_text(str(data.get("question_text", "")).strip())
    if not question_text:
        raise AppError(40001, "题干不能为空", 400)
    answer = normalize_math_text(str(data.get("answer", "")))
    analysis = normalize_math_text(str(data.get("analysis", "")))
    # 题干查重（归一化：去定界符/空白/大小写）
    norm_q = _norm_text(question_text)
    with Session(get_engine()) as s:
        all_qs = s.exec(select(Question)).all()
        for old in all_qs:
            if _norm_text(old.question_text) == norm_q:
                raise AppError(40900, "该题已在错题本中，请勿重复添加", 409)
        # 字符串未命中 → AI 语义查重（忽略'用公式表达'等无效字段）
        dup = None
        if all_qs:
            dup = semantic_duplicate(question_text, [q.question_text for q in all_qs])
        if dup and dup.get("duplicate"):
            raise AppError(40900, "该题已在错题本中（AI 识别为重复），请勿重复添加", 409)
        q = Question(
            notebook_id=notebook_id,
            subject=data.get("subject", "其他"),
            knowledge_point=data.get("knowledge_point", ""),
            error_type=data.get("error_type", "其他"),
            error_detail=data.get("error_detail", ""),
            difficulty=data.get("difficulty", "中"),
            question_text=question_text,
            answer=answer,
            analysis=analysis,
            source=source,
            source_message_id=source_message_id,
        )
        s.add(q)
        s.commit()
        s.refresh(q)
        qid = q.id
        text = q.question_text
    embedding_service.upsert_question(qid, text)
    return _to_out(q)


def _norm_text(t: str) -> str:
    """题干归一化（查重用）：剔除无效词/定界符/空白/标点，幂统一"""
    import re
    t = re.sub(r'\\[\\(\\)\[\]]', '', t or '')
    # 无意义字段（差几个字的干扰词）
    for w in ('用公式表达', '已知', '试求', '求', '请', '计算', '解', '的值', '如下', '请问'):
        t = t.replace(w, '')
    t = re.sub(r'[\s，。、；：！？,.!?;:]+', '', t)
    t = re.sub(r'\^\{?\d+\}?', '^N', t)
    return t.lower()
