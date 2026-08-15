# -*- coding: utf-8 -*-
"""数据看板：KPI / 趋势 / 知识图谱 / 分布"""
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
import re

from sqlmodel import Session, select, func, or_

from app.models.models import get_engine, Question, ReviewLog


def _streak_days(subject: str | None = None) -> int:
    """连续打卡天数：按复习日期去重，从今天往回数。"""
    with Session(get_engine()) as s:
        question_ids = {q.id for q in s.exec(select(Question).where(*([Question.subject == subject] if subject else []))).all()}
        rows = s.exec(select(ReviewLog).where(ReviewLog.question_id.in_(question_ids))).all() if question_ids else []
        dates = {r.reviewed_at.date() for r in rows}
    if not dates:
        return 0
    streak = 0
    d = date.today()
    if d not in dates:
        d -= timedelta(days=1)  # 今天还没复习，从昨天开始算
    while d in dates:
        streak += 1
        d -= timedelta(days=1)
    return streak


def overview(subject: str | None = None) -> dict:
    today_end = datetime.combine(date.today(), datetime.max.time())
    week_start = datetime.combine(date.today() - timedelta(days=date.today().weekday()), datetime.min.time())
    with Session(get_engine()) as s:
        def sc(*conds):
            c = list(conds)
            if subject:
                c.append(Question.subject == subject)
            return s.exec(select(func.count(Question.id)).where(*c)).one()
        total = sc()
        due = sc(Question.mastery_level < 5,
                 or_(Question.next_review_at == None, Question.next_review_at <= today_end))
        question_ids = {q.id for q in s.exec(select(Question).where(*([Question.subject == subject] if subject else []))).all()}
        review_conds = [ReviewLog.reviewed_at >= week_start, ReviewLog.question_id.in_(question_ids)]
        week_reviewed = s.exec(select(func.count(ReviewLog.id)).where(*review_conds)).one()
        week_correct = s.exec(select(func.count(ReviewLog.id)).where(*review_conds,
                                                                      ReviewLog.is_correct == True)).one()
        return {
            "total": total, "due_today": due,
            "week_accuracy": round(week_correct / week_reviewed * 100) if week_reviewed else 0,
            "streak": _streak_days(subject),
        }


def trend(days: int = 7, subject: str | None = None) -> list:
    start = datetime.combine(date.today() - timedelta(days=days - 1), datetime.min.time())
    with Session(get_engine()) as s:
        q_rows = s.exec(select(Question).where(Question.created_at >= start,
                                               *([Question.subject == subject] if subject else []))).all()
        question_ids = {q.id for q in s.exec(select(Question).where(*([Question.subject == subject] if subject else []))).all()}
        r_rows = s.exec(select(ReviewLog).where(ReviewLog.reviewed_at >= start,
                                                ReviewLog.question_id.in_(question_ids))).all() if question_ids else []
    collected = Counter(q.created_at.date() for q in q_rows)
    reviewed = Counter(r.reviewed_at.date() for r in r_rows)
    correct = Counter(r.reviewed_at.date() for r in r_rows if r.is_correct)
    out = []
    for i in range(days):
        d = date.today() - timedelta(days=days - 1 - i)
        c = reviewed.get(d, 0)
        out.append({
            "date": str(d), "collected": collected.get(d, 0), "reviewed": c,
            "accuracy": round(correct.get(d, 0) / c * 100) if c else 0,
        })
    return out


def _knowledge_terms(name: str) -> set[str]:
    """提取可解释的知识点关键词，用于生成轻量关联边，不调用 AI 猜关系。"""
    text = re.sub(r"[的与和及、，。；：:（）()【】\[\]\\/<>\s]+", "", name or "")
    if not text or text == "未分类":
        return set()
    terms = set(re.findall(r"[A-Za-z][A-Za-z0-9]{1,}|\d+", text.lower()))
    # 中文知识点没有天然空格，用二字片段捕捉“函数/积分/极限”等共享主题。
    terms.update(text[i:i + 2] for i in range(len(text) - 1))
    return {term for term in terms if term not in {"基本", "相关", "方法", "理解", "计算"}}


def knowledge_graph(subject: str | None = None) -> dict:
    with Session(get_engine()) as s:
        rows = s.exec(select(Question).where(*([Question.subject == subject] if subject else []))).all()
    # 按学科聚合知识点，同时保留每个知识点的题量和平均掌握度。
    subj_points = defaultdict(list)
    for q in rows:
        subj_points[q.subject].append(q)
    nodes, links = [], []
    point_groups: dict[str, list[dict]] = defaultdict(list)
    for subject, qs in subj_points.items():
        sid = f"s:{subject}"
        nodes.append({"id": sid, "name": subject, "group": "subject", "count": len(qs), "mastery": 0})
        points = defaultdict(list)
        for q in qs:
            points[q.knowledge_point or "未分类"].append(q)
        for kp, plist in points.items():
            kpid = f"k:{subject}:{kp}"
            mastery = round(sum(q.mastery_level for q in plist) / len(plist), 1)
            nodes.append({"id": kpid, "name": kp, "group": "point", "count": len(plist), "mastery": mastery})
            links.append({"source": sid, "target": kpid, "kind": "belongs"})
            point_groups[subject].append({"id": kpid, "name": kp, "terms": _knowledge_terms(kp)})

    # 同一学科内共享明确关键词的知识点建立关联；每对只保留一次，避免图谱变成全连接。
    for group in point_groups.values():
        for i, left in enumerate(group):
            for right in group[i + 1:]:
                shared = left["terms"] & right["terms"]
                if shared:
                    links.append({
                        "source": left["id"], "target": right["id"], "kind": "related",
                        "keywords": sorted(shared)[:3],
                    })
    return {"nodes": nodes, "links": links}


def learning_plan(subject: str | None = None, limit: int = 3) -> list[dict]:
    """给出最多三个可行动的薄弱知识点，不使用 AI 也能稳定产生建议。"""
    now = datetime.now()
    with Session(get_engine()) as s:
        rows = s.exec(select(Question).where(*([Question.subject == subject] if subject else []))).all()
        qids = {q.id for q in rows}
        logs = s.exec(select(ReviewLog).where(ReviewLog.question_id.in_(qids))).all() if qids else []
    by_point: dict[tuple[str, str], list[Question]] = defaultdict(list)
    for q in rows:
        by_point[(q.subject, q.knowledge_point or "未分类")].append(q)
    wrong_by_question = Counter(log.question_id for log in logs if not log.is_correct)
    results = []
    for (subj, point), questions in by_point.items():
        wrong = sum(wrong_by_question[q.id] for q in questions)
        overdue = sum(1 for q in questions if q.next_review_at and q.next_review_at < now)
        mastery = sum(q.mastery_level for q in questions) / len(questions)
        score = wrong * 3 + overdue * 2 + (5 - mastery) * len(questions)
        if score <= 0:
            continue
        errors = Counter(q.error_type for q in questions)
        error_type = errors.most_common(1)[0][0] if errors else "其他"
        recommended = min(10, max(3, len(questions) + wrong + overdue))
        results.append({
            "subject": subj, "knowledge_point": point, "question_count": len(questions),
            "wrong_count": wrong, "overdue_count": overdue, "mastery": round(mastery, 1),
            "error_type": error_type, "recommended_count": recommended,
            "action": f"先复习 {min(3, recommended)} 道原题，再完成 {max(1, min(3, recommended - 3))} 道变式题",
            "priority": round(score, 2),
        })
    return sorted(results, key=lambda item: item["priority"], reverse=True)[:max(1, min(limit, 5))]


def alerts(subject: str | None = None) -> list[dict]:
    plans = learning_plan(subject, limit=5)
    out = []
    for item in plans:
        if item["overdue_count"]:
            out.append({"type": "overdue", "title": f"{item['knowledge_point']} 有 {item['overdue_count']} 道逾期题", "item": item})
        elif item["wrong_count"] >= 2:
            out.append({"type": "weak", "title": f"{item['knowledge_point']} 已累计错 {item['wrong_count']} 次", "item": item})
    return out[:3]


def distributions(subject: str | None = None) -> dict:
    with Session(get_engine()) as s:
        rows = s.exec(select(Question).where(*([Question.subject == subject] if subject else []))).all()
    subjects = Counter(q.subject for q in rows)
    errors = Counter(q.error_type for q in rows)
    return {
        "subjects": [{"name": k, "count": v} for k, v in subjects.most_common()],
        "error_types": [{"name": k, "count": v} for k, v in errors.most_common()],
    }
