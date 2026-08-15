# -*- coding: utf-8 -*-
"""复习计划：SM-2 每日队列 / 考前冲刺 / 周汇总"""
from datetime import datetime, timedelta, date

from sqlmodel import Session, select, func, or_

from app.core.exceptions import AppError
from app.models.models import get_engine, Question, ReviewLog
from app.services import sm2
from app.services.question_service import _to_out


def daily(d: date | None = None, subject: str | None = None, limit: int = 20,
          knowledge_point: str | None = None) -> dict:
    """返回当天可执行的队列。

    逾期题优先，其次是当天到期题，最后才补入从未排期的新题；这能避免新题
    挤掉积压复习。返回的统计字段供仪表盘和卡片复习共享。
    """
    day = d or date.today()
    end = datetime.combine(day, datetime.max.time())
    start = datetime.combine(day, datetime.min.time())
    limit = max(1, min(limit, 100))
    conds = [Question.mastery_level < 5]
    if subject:
        conds.append(Question.subject == subject)
    if knowledge_point:
        conds.append(Question.knowledge_point == knowledge_point)
    with Session(get_engine()) as s:
        scheduled = s.exec(
            select(Question).where(*conds, Question.next_review_at != None, Question.next_review_at <= end)
            .order_by(Question.next_review_at.asc())
        ).all()
        overdue_count = sum(1 for q in scheduled if q.next_review_at and q.next_review_at < start)
        selected = scheduled[:limit]
        # 仅“今天”的入口补入未排期新题；查看历史日历时只显示该日及此前实际到期项。
        new_rows = s.exec(select(Question).where(*conds, Question.next_review_at == None)
                           .order_by(Question.created_at.asc())).all() if day == date.today() else []
        if len(selected) < limit:
            selected.extend(new_rows[:limit - len(selected)])
        total_available = len(scheduled) + len(new_rows)
        due = [_to_out(q) for q in selected]
        return {
            "date": str(day), "due": due, "overdue_count": overdue_count,
            "total_due": total_available, "remaining_count": max(0, total_available - len(selected)),
            "daily_limit": limit,
        }


def _apply_review_outcome(session: Session, question_id: int, quality: int, *, score: float | None = None,
                          review_type: str = "daily") -> dict:
    """在调用方事务内更新一题，避免批量提交产生半套会话结果。"""
    quality = max(0, min(5, int(quality)))
    q = session.get(Question, question_id)
    if not q:
        raise AppError(40400, "错题不存在", 404)
    rep, interval, ease = sm2.sm2_update(quality, q.repetition, q.interval, q.ease)
    q.repetition, q.interval, q.ease = rep, interval, ease
    q.mastery_level = sm2.mastery_from_repetition(rep)
    q.next_review_at = datetime.now() + timedelta(days=interval)
    q.updated_at = datetime.now()
    session.add(q)
    session.add(ReviewLog(question_id=q.id, is_correct=quality >= 3,
                          score=float(score if score is not None else (100 if quality >= 3 else 0)),
                          review_type=review_type[:16]))
    return {"question_id": q.id, "mastery_level": q.mastery_level,
            "next_review_at": str(q.next_review_at), "review_type": review_type}


def record_review_outcome(question_id: int, quality: int, *, score: float | None = None,
                          review_type: str = "daily") -> dict:
    """唯一的 SM-2/日志写入入口，供每日重做、普通重做和专题练习共享。"""
    with Session(get_engine()) as session:
        result = _apply_review_outcome(session, question_id, quality, score=score, review_type=review_type)
        session.commit()
        return result


def complete(question_id: int, quality: int) -> dict:
    return record_review_outcome(question_id, quality, review_type="daily")


def exam_plan(exam_date: datetime) -> dict:
    """考前 N 天计划：把到期/未掌握错题均分到考前每天"""
    days = max(1, (exam_date.date() - date.today()).days)
    if days > 60:
        days = 60
    with Session(get_engine()) as s:
        rows = s.exec(select(Question).where(Question.mastery_level < 5)
                      .order_by(Question.next_review_at.asc().nullsfirst())).all()
        total = len(rows)
    plan = []
    if total == 0:
        return {"days": days, "plan": [], "total": 0}
    per_day = max(1, (total + days - 1) // days)
    for i in range(min(days, 30)):
        day = exam_date.date() - timedelta(days=days - i)
        start, end = i * per_day, min(total, (i + 1) * per_day)
        count = max(0, end - start)
        plan.append({"date": str(day), "count": count, "progress": 0})
    return {"days": days, "plan": plan, "total": total}


def calendar(month: str | None = None, subject: str | None = None) -> dict:
    """按月聚合到期和完成数据，供补做日历使用。"""
    try:
        anchor = date.fromisoformat(f"{month}-01") if month else date.today().replace(day=1)
    except ValueError:
        raise AppError(40001, "月份格式应为 YYYY-MM", 400)
    next_month = (anchor.replace(day=28) + timedelta(days=4)).replace(day=1)
    end = next_month - timedelta(days=1)
    start_dt = datetime.combine(anchor, datetime.min.time())
    end_dt = datetime.combine(end, datetime.max.time())
    with Session(get_engine()) as s:
        qconds = [Question.next_review_at != None, Question.next_review_at >= start_dt, Question.next_review_at <= end_dt]
        if subject:
            qconds.append(Question.subject == subject)
        due_rows = s.exec(select(Question).where(*qconds)).all()
        qids = {q.id for q in s.exec(select(Question).where(Question.subject == subject)).all()} if subject else None
        logs = s.exec(select(ReviewLog).where(ReviewLog.reviewed_at >= start_dt, ReviewLog.reviewed_at <= end_dt)).all()
        if qids is not None:
            logs = [log for log in logs if log.question_id in qids]
    # 补齐整月日期，前端才能稳定绘制真正的月历而不是零散数据点。
    days: dict[str, dict] = {}
    cursor = anchor
    while cursor <= end:
        key = str(cursor)
        days[key] = {"date": key, "due": 0, "completed": 0}
        cursor += timedelta(days=1)
    for q in due_rows:
        key = str(q.next_review_at.date())
        days[key]["due"] += 1
    for log in logs:
        key = str(log.reviewed_at.date())
        days[key]["completed"] += 1
    return {"month": anchor.strftime("%Y-%m"), "days": list(days.values())}


def weekly() -> dict:
    week_start = datetime.combine(date.today() - timedelta(days=date.today().weekday()), datetime.min.time())
    with Session(get_engine()) as s:
        new_count = s.exec(select(func.count(Question.id)).where(Question.created_at >= week_start)).one()
        reviewed = s.exec(select(func.count(ReviewLog.id)).where(ReviewLog.reviewed_at >= week_start)).one()
        correct = s.exec(select(func.count(ReviewLog.id)).where(ReviewLog.reviewed_at >= week_start,
                                                                ReviewLog.is_correct == True)).one()
        return {"week_start": str(week_start.date()), "new_questions": new_count,
                "reviewed": reviewed, "correct": correct,
                "accuracy": round(correct / reviewed * 100) if reviewed else 0}
