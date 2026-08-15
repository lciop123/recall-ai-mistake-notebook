# -*- coding: utf-8 -*-
from datetime import datetime, timedelta

import pytest
from sqlmodel import Session, select

from app.core.exceptions import AppError
from app.models.models import Question, ReviewLog, ReviewSession
from app.services import dashboard_service, plan_service, question_service, report_service, review_service, similarity_service


def test_daily_prioritizes_overdue_and_keeps_new_questions_in_total(db, add_question):
    overdue = add_question(knowledge_point="极限", question_text="逾期题", next_review_at=datetime.now() - timedelta(days=2))
    today = add_question(knowledge_point="极限", question_text="今日题", next_review_at=datetime.now())
    new = add_question(knowledge_point="极限", question_text="新题", next_review_at=None)
    add_question(knowledge_point="导数", question_text="其他知识点", next_review_at=datetime.now() - timedelta(days=1))

    result = plan_service.daily(knowledge_point="极限", limit=2)

    assert [row["id"] for row in result["due"]] == [overdue, today]
    assert result["overdue_count"] == 1
    assert result["total_due"] == 3
    assert result["remaining_count"] == 1
    assert new not in [row["id"] for row in result["due"]]


def test_bulk_update_normalizes_values_and_delete_cleans_review_logs(db, add_question):
    first = add_question(question_text="第一题")
    second = add_question(question_text="第二题")
    changed = question_service.bulk_update([first, second, 99999], {
        "subject": "高等数学", "error_type": "基础概念不清", "difficulty": "困难",
    })
    assert changed == {"updated": 2, "skipped_ids": [99999]}
    with Session(db) as session:
        rows = session.exec(select(Question).where(Question.id.in_([first, second]))).all()
        assert {row.subject for row in rows} == {"数学"}
        assert {row.error_type for row in rows} == {"概念不清"}
        assert {row.difficulty for row in rows} == {"难"}
        session.add(ReviewLog(question_id=first, is_correct=True, score=100))
        session.commit()
    question_service.delete_question(first)
    with Session(db) as session:
        assert session.get(Question, first) is None
        assert session.exec(select(ReviewLog).where(ReviewLog.question_id == first)).all() == []


def test_similarity_fallback_and_merge_preserves_logs(db, add_question):
    primary = add_question(question_text="求函数 f(x)=x^2 的导数", knowledge_point="求导")
    duplicate = add_question(question_text="求函数 f(x)=x^2 的导数", knowledge_point="求导", answer="2x")
    with Session(db) as session:
        session.add(ReviewLog(question_id=duplicate, is_correct=False, score=0))
        session.commit()

    found = similarity_service.similar_questions(primary)
    assert any(item["id"] == duplicate for item in found)
    result = similarity_service.merge_duplicate(primary, duplicate)
    assert result["migrated_review_logs"] == 1
    with Session(db) as session:
        assert session.get(Question, duplicate) is None
        assert session.exec(select(ReviewLog).where(ReviewLog.question_id == primary)).one().is_correct is False


def test_submitting_session_is_exactly_once(db, add_question, monkeypatch):
    question_id = add_question(question_text="1 + 1 = ?", answer="2")
    session_id = "once-only"
    with Session(db) as session:
        session.add(ReviewSession(id=session_id, questions_json='[{"id": 1, "origin_id": 1, "question_text": "1 + 1 = ?", "answer": "2", "analysis": "", "options": []}]'))
        session.commit()

    monkeypatch.setattr(review_service.deepseek_client, "grade", lambda *_args, **_kwargs: None)
    first = review_service.submit(session_id, {question_id: "2"})
    assert first["sm2_updated"] == 1
    with Session(db) as session:
        assert len(session.exec(select(ReviewLog).where(ReviewLog.question_id == question_id)).all()) == 1
        assert session.get(ReviewSession, session_id).submitted_at is not None
    with pytest.raises(AppError) as exc:
        review_service.submit(session_id, {question_id: "2"})
    assert exc.value.code == 40900


def test_weekly_report_ignores_deleted_or_unrelated_logs(db, add_question):
    math_id = add_question(subject="数学", error_type="粗心", question_text="数学题", created_at=datetime.now())
    english_id = add_question(subject="英语", question_text="English", created_at=datetime.now())
    with Session(db) as session:
        session.add(ReviewLog(question_id=math_id, is_correct=True, score=100, reviewed_at=datetime.now()))
        session.add(ReviewLog(question_id=english_id, is_correct=False, score=0, reviewed_at=datetime.now()))
        session.commit()
    report = report_service.weekly_summary(subject="数学")
    assert report["reviewed"] == 1
    assert report["accuracy"] == 100
    assert report["top_error_types"] == [{"name": "粗心", "count": 1}]
