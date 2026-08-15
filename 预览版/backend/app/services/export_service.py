# -*- coding: utf-8 -*-
"""导出：Markdown（纯文本）/ PDF（ReportLab + 中文字体）"""
import io
import logging
from datetime import datetime
from html import escape
from pathlib import Path

from sqlmodel import Session, select

from app.core.config import DATA_DIR
from app.core.exceptions import AppError
from app.models.models import get_engine, Question
from app.services.question_service import _to_out

logger = logging.getLogger(__name__)

FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc", "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _pick_questions(notebook_id=None, subject=None) -> list:
    with Session(get_engine()) as s:
        conds = []
        if notebook_id:
            conds.append(Question.notebook_id == notebook_id)
        if subject:
            conds.append(Question.subject == subject)
        rows = s.exec(select(Question).where(*conds).order_by(Question.created_at.desc()).limit(500)).all()
        return [_to_out(q) for q in rows]


def build_markdown(notebook_id=None, subject=None, include_answer: bool = True, include_analysis: bool = True) -> str:
    qs = _pick_questions(notebook_id, subject)
    if not qs:
        raise AppError(40001, "导出范围内没有错题", 400)
    lines = [f"# Recall 错题本导出（共 {len(qs)} 题）\n"]
    for i, q in enumerate(qs, 1):
        lines.append(f"## 第 {i} 题 · {q['subject']} · {q['knowledge_point'] or '未分类'}")
        lines.append(f"\n**题目**：{q['question_text']}")
        if include_answer:
            lines.append(f"\n**答案**：{q['answer'] or '—'}")
        if include_analysis and q["analysis"]:
            lines.append(f"\n**解析**：{q['analysis']}")
        lines.append(f"\n> 错因：{q['error_type']} ｜ 难度：{q['difficulty']} ｜ 掌握度：{q['mastery_level']}/5\n")
        lines.append("---\n")
    return "\n".join(lines)


def build_pdf(notebook_id=None, subject=None, include_answer: bool = True, include_analysis: bool = True) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, KeepTogether

    qs = _pick_questions(notebook_id, subject)
    if not qs:
        raise AppError(40001, "导出范围内没有错题", 400)

    # 注册中文字体
    font_name = "Helvetica"
    for path in FONT_CANDIDATES:
        p = Path(path)
        if p.exists():
            try:
                pdfmetrics.registerFont(TTFont("CJK", str(p)))
                font_name = "CJK"
                break
            except Exception as e:
                logger.warning("字体注册失败 %s: %s", path, e)

    st_title = ParagraphStyle("t", fontName=font_name, fontSize=18, leading=24, spaceAfter=6)
    st_q = ParagraphStyle("q", fontName=font_name, fontSize=11, leading=17, spaceBefore=4)
    st_a = ParagraphStyle("a", fontName=font_name, fontSize=10.5, leading=16, textColor=colors.HexColor("#1D1D1F"))
    st_tag = ParagraphStyle("tag", fontName=font_name, fontSize=9, leading=13, textColor=colors.HexColor("#6E6E73"))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm,
                            leftMargin=16 * mm, rightMargin=16 * mm)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    story = [Paragraph("Recall · 错题本导出", st_title),
             Paragraph(f"共 {len(qs)} 题 ｜ 生成时间：{generated_at}", st_tag), Spacer(1, 6)]
    for i, q in enumerate(qs, 1):
        block = [
            Paragraph(escape(f"第 {i} 题 ｜ {q['subject']} ｜ {q['knowledge_point'] or '未分类'} ｜ 错因：{q['error_type']}"), st_tag),
            Paragraph(f"<b>题目：</b>{escape(q['question_text'])}", st_q),
        ]
        if include_answer:
            block.append(Paragraph(f"<b>答案：</b>{escape(q['answer'] or '—')}", st_a))
        if include_analysis and q["analysis"]:
            block.append(Paragraph(f"<b>解析：</b>{escape(q['analysis'])}", st_a))
        block.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#E5E5EA"), spaceBefore=4, spaceAfter=6))
        story.append(KeepTogether(block))
    doc.build(story)
    return buf.getvalue()
