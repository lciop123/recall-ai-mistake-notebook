# -*- coding: utf-8 -*-
"""一键复习：AI 变体题（失败降级原题）+ AI 批改（失败降级参考答案比对）

复习会话持久化到 review_sessions 表，后端重启后仍可提交。
"""
import json
import uuid
from datetime import datetime, timedelta
from difflib import SequenceMatcher

from sqlalchemy import update
from sqlmodel import Session, select

from app.ai import deepseek_client, embedding_service
from app.core.exceptions import AppError
from app.models.models import get_engine, Question, ReviewLog, ReviewSession
from app.services import sm2, question_service
from app.services.plan_service import _apply_review_outcome

# review_id -> {"questions": [{id, question_text, options, answer, analysis, is_variant}], "created_at"}
_reviews: dict = {}


def _pick_pool(s: Session, notebook_id=None, subject=None, limit: int = 20) -> list:
    conds = [Question.mastery_level < 5]
    if notebook_id:
        conds.append(Question.notebook_id == notebook_id)
    if subject:
        conds.append(Question.subject == subject)
    rows = s.exec(select(Question).where(*conds)
                  .order_by(Question.next_review_at.asc().nullsfirst())
                  .limit(limit)).all()
    return rows


def _save_session(review_id: str, questions: list, *, mode: str = "variant", config: dict | None = None) -> None:
    with Session(get_engine()) as s:
        s.add(ReviewSession(id=review_id, questions_json=json.dumps(questions, ensure_ascii=False),
                            mode=mode, config_json=json.dumps(config or {}, ensure_ascii=False)))
        # 保留最近 50 个已完成记录；未提交会话保留 24 小时，之后安全过期，避免无限积累并阻塞题目管理。
        old_done = s.exec(select(ReviewSession).where(ReviewSession.submitted_at != None)
                          .order_by(ReviewSession.created_at.desc()).offset(50)).all()
        stale_open = s.exec(select(ReviewSession).where(
            ReviewSession.submitted_at == None,
            ReviewSession.created_at < datetime.now() - timedelta(days=1),
        )).all()
        for item in [*old_done, *stale_open]:
            s.delete(item)
            _reviews.pop(item.id, None)
        s.commit()


def generate(notebook_id=None, subject=None, count: int = 5) -> dict:
    with Session(get_engine()) as s:
        pool = _pick_pool(s, notebook_id, subject, limit=max(count * 3, 10))
        if not pool:
            raise AppError(40001, "所选范围暂无错题，请先录入", 400)
        # 一道原题在一套练习中最多出现一次，避免一次提交重复推进同一 SM-2 状态。
        count = min(count, len(pool))
        pool_ids = [q.id for q in pool]
        questions = []
        variants = deepseek_client.generate_variants(
            [{"id": q.id, "question_text": q.question_text, "answer": q.answer, "analysis": q.analysis} for q in pool[:6]],
            count=count,
        )
        if variants:
            # 批量审核变体题（科学/自洽/可解）；审核不可用(限流等)时全部用原题兑底，宁可不出变体也不出错题
            checks = deepseek_client.verify_questions(variants[:count])
            if checks is None:
                checks = [{"valid": False, "reason": "AI 审核暂不可用"}] * len(variants[:count])
            for idx, v in enumerate(variants[:count]):
                qid = pool_ids[idx % len(pool_ids)]
                origin = next((q for q in pool if q.id == qid), None)
                ck = checks[idx] if idx < len(checks) else {"valid": True, "reason": ""}
                if not ck.get("valid", True):
                    # 重新生成一次单题
                    retry = deepseek_client.generate_variants(
                        [{"id": qid, "question_text": origin.question_text if origin else "",
                          "answer": origin.answer if origin else "", "analysis": origin.analysis if origin else ""}],
                        count=1)
                    if retry and retry[0].get("question_text"):
                        v2 = retry[0]
                        ck2 = deepseek_client.verify_questions([v2])
                        if ck2 and ck2[0].get("valid", False):
                            v = v2
                        else:
                            # 仍不合格 → 用原题兜底
                            v = {"question_text": origin.question_text if origin else v["question_text"],
                                 "options": [],
                                 "answer": origin.answer if origin else "",
                                 "analysis": origin.analysis if origin else "",
                                 "is_fallback_origin": True}
                    else:
                        v = {"question_text": origin.question_text if origin else v["question_text"],
                             "options": [],
                             "answer": origin.answer if origin else "",
                             "analysis": origin.analysis if origin else "",
                             "is_fallback_origin": True}
                questions.append({
                    "id": -(idx + 1),
                    "origin_id": qid,
                    "question_text": v["question_text"],
                    "options": v.get("options") or [],
                    "answer": v.get("answer", ""),
                    "analysis": v.get("analysis", ""),
                    "knowledge_point": v.get("knowledge_point") or (origin.knowledge_point if origin else ""),
                    "is_variant": not v.get("is_fallback_origin"),
                })
        # 变体题不足时用原题补齐
        if len(questions) < count:
            for q in pool:
                if len(questions) >= count:
                    break
                if all(x.get("origin_id", x["id"]) != q.id for x in questions):
                    questions.append({
                        "id": q.id, "origin_id": q.id, "question_text": q.question_text, "options": [],
                        "answer": q.answer, "analysis": q.analysis,
                        "knowledge_point": q.knowledge_point, "is_variant": False,
                    })
        review_id = uuid.uuid4().hex[:12]
        _save_session(review_id, questions, mode="variant", config={"subject": subject, "notebook_id": notebook_id})
        _reviews[review_id] = {"questions": questions, "created_at": datetime.now(), "mode": "variant"}
        return {"review_id": review_id, "questions": questions, "source": "ai" if variants else "fallback"}


def _safe_score(value: object) -> int:
    try:
        return max(0, min(100, int(float(value or 0))))
    except (TypeError, ValueError):
        return 0


def _feedback_fields(result: dict, correct: bool) -> tuple[str, str]:
    feedback = str(result.get("analysis") or result.get("feedback") or ("回答正确，继续保持。" if correct else "请对照参考答案检查解题过程。"))
    first_error = str(result.get("first_error_step") or ("" if correct else feedback))
    next_hint = str(result.get("next_hint") or ("尝试独立复述解法。" if correct else "先从题干条件和第一步推导重新检查。"))
    return first_error, next_hint


def _fallback_grade(questions: list, answers: dict) -> list:
    """无 AI 时：参考答案与用户答案做相似度比对"""
    results = []
    for q in questions:
        ref = (q.get("answer") or "").strip()
        user = (answers.get(q["id"]) or "").strip()
        if not ref:
            results.append({"id": q["id"], "correct": False, "score": 0, "analysis": "本题无参考答案，请人工核对", "first_error_step": "", "next_hint": "请先核对标准答案后再复习。"})
        else:
            ratio = SequenceMatcher(None, ref, user).ratio() if user else 0
            correct = bool(user) and (ratio >= 0.8 or ref in user or user in ref)
            results.append({"id": q["id"], "correct": correct, "score": 100 if correct else 0,
                            "analysis": "参考答案：" + ref[:200],
                            "first_error_step": "" if correct else "答案与参考答案不一致",
                            "next_hint": "对照参考答案重新写出关键步骤。" if not correct else "尝试不用参考答案再次作答。"})
    return results


def _load_review(review_id: str) -> dict:
    """优先内存，其次数据库（后端重启后恢复）"""
    if review_id in _reviews:
        return _reviews[review_id]
    with Session(get_engine()) as s:
        row = s.get(ReviewSession, review_id)
        if not row:
            raise AppError(40400, "复习会话不存在或已过期，请重新出题", 404)
        questions = json.loads(row.questions_json)
        _reviews[review_id] = {"questions": questions, "created_at": row.created_at, "mode": row.mode or "variant"}
        return _reviews[review_id]


def generate_exam(exam_date: str, subject: str | None = None, count: int = 10) -> dict:
    """生成考前专题卷：低掌握、逾期、累积错题优先，可靠地使用原题。"""
    try:
        exam = datetime.fromisoformat(exam_date).date()
    except ValueError:
        raise AppError(40001, "考试日期格式应为 YYYY-MM-DD", 400)
    if exam < datetime.now().date():
        raise AppError(40001, "考试日期不能早于今天", 400)
    count = max(1, min(int(count), 30))
    with Session(get_engine()) as s:
        conds = [Question.mastery_level < 5]
        if subject:
            conds.append(Question.subject == subject)
        pool = s.exec(select(Question).where(*conds)).all()
        logs = s.exec(select(ReviewLog)).all()
        wrong_counts = {}
        for log in logs:
            if not log.is_correct:
                wrong_counts[log.question_id] = wrong_counts.get(log.question_id, 0) + 1
        now = datetime.now()
        pool.sort(key=lambda q: (-(wrong_counts.get(q.id, 0) * 3 + (2 if q.next_review_at and q.next_review_at < now else 0) + (5 - q.mastery_level)), q.created_at))
        selected = pool[:count]
        if not selected:
            raise AppError(40001, "所选范围暂无可用于专题练习的错题", 400)
        questions = [{
            "id": q.id, "origin_id": q.id, "question_text": q.question_text, "options": [],
            "answer": q.answer, "analysis": q.analysis, "knowledge_point": q.knowledge_point,
            "is_variant": False,
        } for q in selected]
    review_id = uuid.uuid4().hex[:12]
    _save_session(review_id, questions, mode="exam", config={"exam_date": str(exam), "subject": subject, "count": count})
    _reviews[review_id] = {"questions": questions, "created_at": datetime.now(), "mode": "exam"}
    distribution = {}
    for question in questions:
        point = question["knowledge_point"] or "未分类"
        distribution[point] = distribution.get(point, 0) + 1
    return {"review_id": review_id, "questions": questions, "source": "exam", "exam_date": str(exam),
            "recommended_minutes": max(10, len(questions) * 5), "knowledge_distribution": distribution}


def add_question(review_id: str, question_id: int) -> dict:
    """把复习会话中的变体题（举一反三题）加入错题本"""
    review = _load_review(review_id)
    q = next((x for x in review["questions"] if x.get("id") == question_id), None)
    if not q:
        raise AppError(40400, "题目不在当前复习会话中", 404)
    origin = q.get("origin_id")
    with Session(get_engine()) as s:
        src = s.get(Question, origin) if origin else None
        subject = src.subject if src else "其他"
        dup = s.exec(select(Question).where(Question.question_text == q["question_text"])).first()
        if dup:
            raise AppError(40900, "该题已加入过错题本", 409)
    return question_service.create_from_extract({
        "subject": subject,
        "question_text": q["question_text"],
        "answer": q.get("answer", ""),
        "analysis": q.get("analysis", ""),
    }, source="review")


def submit(review_id: str, answers: dict) -> dict:
    review = _load_review(review_id)
    questions = review["questions"]
    ai_results = deepseek_client.grade(questions, answers)
    if isinstance(ai_results, list):
        # AI 返回的 id 不可靠：按数组顺序对齐 questions，id 以 questions 为准。
        results = []
        for i, q in enumerate(questions):
            r = ai_results[i] if i < len(ai_results) and isinstance(ai_results[i], dict) else {}
            correct = bool(r.get("correct"))
            first_error, next_hint = _feedback_fields(r, correct)
            results.append({
                "id": q["id"],
                "origin_id": q.get("origin_id", q["id"]),
                "correct": correct,
                "score": _safe_score(r.get("score")),
                "analysis": str(r.get("analysis") or r.get("feedback") or ""),
                "answer": str(r.get("answer") or ""),
                "first_error_step": first_error,
                "next_hint": next_hint,
            })
    else:
        results = _fallback_grade(questions, answers)
        for result in results:
            result["origin_id"] = next((q.get("origin_id", q["id"]) for q in questions if q["id"] == result["id"]), result["id"])

    # 在一个事务里更新全部题目并标记会话，避免重复提交或半套会话写入。
    updated = 0
    review_type = "exam" if review.get("mode") == "exam" else "variant"
    with Session(get_engine()) as session:
        # 条件更新是提交权的原子抢占：即使两个请求同时到达，也只有一个能写入 SM-2 日志。
        claimed = session.execute(
            update(ReviewSession)
            .where(ReviewSession.id == review_id, ReviewSession.submitted_at == None)
            .values(submitted_at=datetime.now())
        )
        if not claimed.rowcount:
            stored = session.get(ReviewSession, review_id)
            if not stored:
                raise AppError(40400, "复习会话不存在或已过期，请重新出题", 404)
            raise AppError(40900, "该复习会话已提交，结果已计入学习记录", 409)
        updated_origins: set[int] = set()
        for r in results:
            qid = r.get("origin_id") or r.get("id")
            if qid and qid > 0 and qid not in updated_origins:
                _apply_review_outcome(session, qid, 5 if r.get("correct") else 1,
                                      score=r.get("score", 0), review_type=review_type)
                updated_origins.add(qid)
                updated += 1
        session.commit()

    correct = sum(1 for r in results if r.get("correct"))
    return {
        "total": len(results), "correct": correct, "score": round(correct / len(results) * 100) if results else 0,
        "results": [{"id": r.get("id"), "correct": r.get("correct"), "score": r.get("score"),
                     "analysis": r.get("analysis", ""), "answer": r.get("answer", ""),
                     "first_error_step": r.get("first_error_step", ""), "next_hint": r.get("next_hint", "")} for r in results],
        "sm2_updated": updated,
    }


def history(page: int = 1, page_size: int = 20) -> dict:
    with Session(get_engine()) as s:
        from sqlmodel import func
        total = s.exec(select(func.count(ReviewLog.id))).one()
        rows = s.exec(select(ReviewLog).order_by(ReviewLog.reviewed_at.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
        items = [{"id": r.id, "question_id": r.question_id, "reviewed_at": str(r.reviewed_at),
                  "is_correct": r.is_correct, "score": r.score, "review_type": r.review_type} for r in rows]
        return {"items": items, "total": total, "page": page, "page_size": page_size}
