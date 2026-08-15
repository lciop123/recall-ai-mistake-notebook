# -*- coding: utf-8 -*-
"""本地周学习报告。只聚合 SQLite 数据，不调用模型或外部服务。"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta

from sqlmodel import Session, select

from app.models.models import Question, ReviewLog, get_engine
from app.services import dashboard_service


def _week_start(value: str | None = None) -> date:
    if not value:
        return date.today() - timedelta(days=date.today().weekday())
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        from app.core.exceptions import AppError
        raise AppError(40001, "week_start 格式应为 YYYY-MM-DD", 400)
    return parsed - timedelta(days=parsed.weekday())


def weekly_summary(week_start: str | None = None, subject: str | None = None) -> dict:
    start_date = _week_start(week_start)
    start = datetime.combine(start_date, datetime.min.time())
    end = start + timedelta(days=7)
    with Session(get_engine()) as session:
        qconds = [Question.created_at >= start, Question.created_at < end]
        if subject:
            qconds.append(Question.subject == subject)
        new_questions = session.exec(select(Question).where(*qconds)).all()
        all_question_ids = {q.id for q in session.exec(select(Question).where(*([Question.subject == subject] if subject else []))).all()}
        logs = session.exec(select(ReviewLog).where(ReviewLog.reviewed_at >= start, ReviewLog.reviewed_at < end,
                                                    ReviewLog.question_id.in_(all_question_ids))).all() if all_question_ids else []

    reviewed = len(logs)
    correct = sum(1 for log in logs if log.is_correct)
    errors = Counter(q.error_type for q in new_questions)
    plans = dashboard_service.learning_plan(subject, limit=3)
    suggestions = []
    for item in plans:
        suggestions.append(f"优先处理「{item['knowledge_point']}」：{item['action']}。")
    if not suggestions:
        suggestions.append("保持每周至少两次复习，及时收录新错题。")
    return {
        "week_start": str(start_date), "week_end": str(start_date + timedelta(days=6)),
        "subject": subject or "全部学科", "new_questions": len(new_questions),
        "reviewed": reviewed, "correct": correct,
        "accuracy": round(correct / reviewed * 100) if reviewed else 0,
        "streak": dashboard_service._streak_days(subject),
        "top_error_types": [{"name": name, "count": count} for name, count in errors.most_common(3)],
        "learning_plan": plans, "suggestions": suggestions,
    }


def build_weekly_markdown(week_start: str | None = None, subject: str | None = None) -> str:
    report = weekly_summary(week_start, subject)
    lines = [
        "# Recall 周学习报告",
        "",
        f"- 周期：{report['week_start']} 至 {report['week_end']}",
        f"- 范围：{report['subject']}",
        "",
        "## 本周概览",
        f"- 新增错题：{report['new_questions']} 道",
        f"- 完成复习：{report['reviewed']} 次",
        f"- 复习正确率：{report['accuracy']}%",
        f"- 连续复习：{report['streak']} 天",
        "",
        "## 高频错因",
    ]
    if report["top_error_types"]:
        lines.extend(f"- {item['name']}：{item['count']} 道" for item in report["top_error_types"])
    else:
        lines.append("- 本周暂无新增错题记录")
    lines.extend(["", "## 下周建议"])
    lines.extend(f"- {suggestion}" for suggestion in report["suggestions"])
    return "\n".join(lines) + "\n"


def build_weekly_pdf(week_start: str | None = None, subject: str | None = None) -> bytes:
    """生成简洁周报 PDF，独立于题目导出且使用同一套中文字体回退。"""
    import io
    from html import escape
    from pathlib import Path
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    from app.services.export_service import FONT_CANDIDATES

    report = weekly_summary(week_start, subject)
    font_name = "Helvetica"
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                pdfmetrics.registerFont(TTFont("RecallReportCJK", path))
                font_name = "RecallReportCJK"
                break
            except Exception:
                continue
    title = ParagraphStyle("weekly-title", fontName=font_name, fontSize=18, leading=25, spaceAfter=10)
    heading = ParagraphStyle("weekly-heading", fontName=font_name, fontSize=12, leading=18, textColor=colors.HexColor("#007AFF"), spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("weekly-body", fontName=font_name, fontSize=10.5, leading=17)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm, leftMargin=18 * mm, rightMargin=18 * mm)
    story = [
        Paragraph("Recall · 周学习报告", title),
        Paragraph(escape(f"周期：{report['week_start']} 至 {report['week_end']} ｜ 范围：{report['subject']}"), body),
        Paragraph("本周概览", heading),
        Paragraph(escape(f"新增错题 {report['new_questions']} 道 ｜ 完成复习 {report['reviewed']} 次 ｜ 正确率 {report['accuracy']}% ｜ 连续复习 {report['streak']} 天"), body),
        Paragraph("高频错因", heading),
    ]
    if report["top_error_types"]:
        story.extend(Paragraph(escape(f"{row['name']}：{row['count']} 道"), body) for row in report["top_error_types"])
    else:
        story.append(Paragraph("本周暂无新增错题记录", body))
    story.append(Paragraph("下周建议", heading))
    story.extend(Paragraph(escape(item), body) for item in report["suggestions"])
    story.append(Spacer(1, 4))
    doc.build(story)
    return buf.getvalue()
