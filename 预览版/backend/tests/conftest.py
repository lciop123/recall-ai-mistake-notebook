# -*- coding: utf-8 -*-
"""后端服务测试的隔离数据库与外部能力桩。"""
from __future__ import annotations

import pytest
from sqlmodel import SQLModel, Session, create_engine

from app.models.models import Question


@pytest.fixture
def db(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'recall-test.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    from app.services import (dashboard_service, notebook_service, plan_service,
                              question_service, report_service, review_service,
                              similarity_service)
    for module in (dashboard_service, notebook_service, plan_service, question_service,
                   report_service, review_service, similarity_service):
        monkeypatch.setattr(module, "get_engine", lambda: engine)

    # 测试永不加载模型、连接 Chroma 或写入真实向量索引。
    for module in (question_service.embedding_service, similarity_service.embedding_service):
        monkeypatch.setattr(module, "upsert_question", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(module, "delete_question", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(module, "search", lambda *_args, **_kwargs: None)
    return engine


@pytest.fixture
def add_question(db):
    def create(**overrides):
        payload = {
            "subject": "数学",
            "knowledge_point": "函数",
            "error_type": "概念不清",
            "difficulty": "中",
            "question_text": "默认题干",
            "answer": "默认答案",
            "analysis": "默认解析",
        }
        payload.update(overrides)
        with Session(db) as session:
            question = Question(**payload)
            session.add(question)
            session.commit()
            session.refresh(question)
            return question.id
    return create
