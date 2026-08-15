# -*- coding: utf-8 -*-
from sqlmodel import SQLModel, Field, Column, DateTime, Integer, String, Text, Float, ForeignKey
from datetime import datetime, date
from typing import Optional

from app.core.config import DB_PATH

SUBJECTS = ["语文", "数学", "英语", "物理", "化学", "生物", "政治", "历史", "地理", "专业课", "其他"]
ERROR_TYPES = ["概念不清", "审题失误", "粗心", "计算错误", "方法不当", "超纲", "其他"]
DIFFICULTIES = ["易", "中", "难"]
NOTEBOOK_COLORS = ["#007AFF", "#34C759", "#FF9500", "#AF52DE", "#FF2D55", "#5AC8FA", "#FFD60A", "#5856D6"]


class Notebook(SQLModel, table=True):
    __tablename__ = "notebooks"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=64)
    color: str = Field(default="#007AFF", max_length=16)
    created_at: datetime = Field(default_factory=datetime.now)


class Question(SQLModel, table=True):
    __tablename__ = "questions"
    id: Optional[int] = Field(default=None, primary_key=True)
    notebook_id: Optional[int] = Field(default=None, foreign_key="notebooks.id", index=True)
    subject: str = Field(default="其他", max_length=32, index=True)
    knowledge_point: str = Field(default="", max_length=64)
    error_type: str = Field(default="其他", max_length=32, index=True)
    # 受控错因之外的原始具体描述，避免把近义词拆散看板统计。
    error_detail: str = Field(default="", max_length=256)
    difficulty: str = Field(default="中", max_length=8)
    question_text: str = Field(sa_column=Column(Text))
    answer: str = Field(default="", sa_column=Column(Text))
    analysis: str = Field(default="", sa_column=Column(Text))
    image_path: Optional[str] = Field(default=None, max_length=256)
    # 来源标记（chat 对话提取 / manual 手动 / capture 识别）与来源消息 id（用于防重复加入）
    source: str = Field(default="manual", max_length=16)
    source_message_id: Optional[int] = Field(default=None, index=True)
    # SM-2 状态
    mastery_level: int = Field(default=0)
    repetition: int = Field(default=0)
    interval: int = Field(default=0)
    ease: float = Field(default=2.5)
    next_review_at: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class ReviewLog(SQLModel, table=True):
    __tablename__ = "review_logs"
    id: Optional[int] = Field(default=None, primary_key=True)
    question_id: int = Field(foreign_key="questions.id", index=True)
    reviewed_at: datetime = Field(default_factory=datetime.now, index=True)
    is_correct: bool = Field(default=False)
    score: float = Field(default=0)
    review_type: str = Field(default="daily", max_length=16)


class Conversation(SQLModel, table=True):
    __tablename__ = "conversations"
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(default="新对话", max_length=128)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    # 继承上下文：新会话会带上源会话最近 N 条消息，但界面不展示（避免长历史拖沓）
    inherit_from_id: Optional[int] = Field(default=None, index=True)
    inherit_last_count: int = Field(default=20)


class Message(SQLModel, table=True):
    __tablename__ = "messages"
    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: int = Field(foreign_key="conversations.id", index=True)
    role: str = Field(max_length=16)  # user / assistant
    content: str = Field(sa_column=Column(Text))
    image_path: Optional[str] = Field(default=None, max_length=255)  # 对话图片（可空）
    created_at: datetime = Field(default_factory=datetime.now)


class ReviewSession(SQLModel, table=True):
    """复习会话（持久化，避免后端重启导致已出题目丢失）"""
    __tablename__ = "review_sessions"
    id: Optional[str] = Field(default=None, primary_key=True)  # review_id
    questions_json: str = Field(sa_column=Column(Text))  # JSON 数组
    mode: str = Field(default="variant", max_length=16)
    config_json: str = Field(default="{}", sa_column=Column(Text))
    submitted_at: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.now)


def create_db_and_tables():
    from sqlmodel import create_engine
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    migrate(engine)


def migrate(engine):
    """轻量迁移：补充字段，并对历史数学文本做幂等规范化。"""
    with engine.connect() as conn:
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(questions)").fetchall()]
        if "source" not in cols:
            conn.exec_driver_sql("ALTER TABLE questions ADD COLUMN source VARCHAR(16) DEFAULT 'manual'")
        if "source_message_id" not in cols:
            conn.exec_driver_sql("ALTER TABLE questions ADD COLUMN source_message_id INTEGER")
        if "error_detail" not in cols:
            conn.exec_driver_sql("ALTER TABLE questions ADD COLUMN error_detail VARCHAR(256) DEFAULT ''")
        rcols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(review_sessions)").fetchall()]
        if "mode" not in rcols:
            conn.exec_driver_sql("ALTER TABLE review_sessions ADD COLUMN mode VARCHAR(16) DEFAULT 'variant'")
        if "config_json" not in rcols:
            conn.exec_driver_sql("ALTER TABLE review_sessions ADD COLUMN config_json TEXT DEFAULT '{}'")
        if "submitted_at" not in rcols:
            conn.exec_driver_sql("ALTER TABLE review_sessions ADD COLUMN submitted_at DATETIME")
        ccols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(conversations)").fetchall()]
        if "inherit_from_id" not in ccols:
            conn.exec_driver_sql("ALTER TABLE conversations ADD COLUMN inherit_from_id INTEGER")
        if "inherit_last_count" not in ccols:
            conn.exec_driver_sql("ALTER TABLE conversations ADD COLUMN inherit_last_count INTEGER DEFAULT 20")
        conn.commit()
    _normalize_legacy_math(engine)


def _normalize_legacy_math(engine):
    """幂等清洗历史公式及分类，保留原始错因描述而不丢失题目数据。"""
    from app.ai.deepseek_client import normalize_math_text
    from app.services.taxonomy_service import normalize_error_type, normalize_subject
    with engine.begin() as conn:
        questions = conn.exec_driver_sql(
            "SELECT id, question_text, answer, analysis, subject, error_type, error_detail FROM questions"
        ).fetchall()
        for row in questions:
            qid, question_text, answer, analysis, subject, error_type, error_detail = row
            cleaned = tuple(normalize_math_text(value or "") for value in (question_text, answer, analysis))
            subject_clean = normalize_subject(subject)
            error_clean, inferred_detail = normalize_error_type(error_type)
            detail_clean = (error_detail or inferred_detail or "")[:256]
            old = (question_text, answer, analysis, subject, error_type, error_detail or "")
            new = (*cleaned, subject_clean, error_clean, detail_clean)
            if new != old:
                conn.exec_driver_sql(
                    "UPDATE questions SET question_text = ?, answer = ?, analysis = ?, subject = ?, error_type = ?, error_detail = ? WHERE id = ?",
                    (*new, qid),
                )
        messages = conn.exec_driver_sql("SELECT id, content FROM messages").fetchall()
        for row in messages:
            cleaned = normalize_math_text(row[1] or "")
            if cleaned != row[1]:
                conn.exec_driver_sql("UPDATE messages SET content = ? WHERE id = ?", (cleaned, row[0]))


def get_engine():
    from sqlmodel import create_engine
    return create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
