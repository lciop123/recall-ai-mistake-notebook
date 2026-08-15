# -*- coding: utf-8 -*-
import asyncio
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.ai import deepseek_client
from app.api import ok
from app.core.exceptions import AppError

router = APIRouter(prefix="/api/ai", tags=["ai"])


class AIAnswerReq(BaseModel):
    question_text: str = Field(min_length=1)
    subject: str = ""


@router.post("/answer")
def generate_answer(data: AIAnswerReq):
    result = deepseek_client.generate_answer(data.question_text, data.subject)
    if not result:
        raise AppError(50200, "AI 服务暂时不可用，请稍后重试", 503)
    return ok(result)


SYSTEM_ANSWER_STREAM = (
    "你是解题老师。请按以下格式直接输出文本（不要输出 JSON）：\n"
    "第一行：答案：<最终答案>\n"
    "然后：解析：\n1. <第一步>\n2. <第二步>\n...\n"
    "要求：解答清晰明了易懂，先点明方法再分步推导，步骤完整；"
    "数学公式用 LaTeX 并加 $ 包裹（行内 $...$，独立公式 $$...$$）。"
)

SYSTEM_KNOWLEDGE = (
    "你是教学老师。根据题目及其考察的知识点，生成【知识点系统性学习】讲解，直接输出 Markdown 文本（不要 JSON），要求：\n"
    "1. 第一行标题：知识点：<知识点名称>\n"
    "2. 开篇用一句话说明这个知识点与本题的关系；\n"
    "3. 分节讲解（### 1. …、### 2. …），每节包含：含义、常用结构/公式（LaTeX 用 $ 包裹）、例（配中文解释）；\n"
    "4. 内容严谨、由浅入深、循序渐进，适合学生自学；最后加一节 ### 易错提醒。"
)

SYSTEM_GEOGEBRA = (
    "你是几何绘图助手。根据题目，生成【GeoGebra 命令序列】来画出题目示意图（辅助解题），要求：\n"
    "1. 只输出命令文本，每行一条 GeoGebra 命令，不要任何解释、不要 Markdown、不要 JSON；\n"
    "2. 常用命令示例：A=(0,0)、B=(4,0)、C=(2,3)、Polygon(A,B,C)、Segment(A,B)、Circle(A,B)、Line(A,B)、"
    "f(x)=x^2-4x+3、Intersect(f,g)、Angle(A,B,C)、Midpoint(A,B)、PerpendicularLine(A,B)、ParallelLine(A,C)、"
    "Vector((0,0),(2,3))、ShowLabel(A,true)、SetColor(A,\"blue\")、SetCoords(A,1,2)；\n"
    "3. 坐标/数值根据题目条件取合理值（题目没给就取简单整数）；标注关键点标签；\n"
    "4. 无法绘图（非几何题）时输出：// 无法绘图\n"
    "只输出命令，直接开始。"
)


@router.post("/answer-stream")
async def answer_stream(data: AIAnswerReq):
    """流式生成答案+解析（SSE），前端实时显示"""
    async def gen():
        subject_hint = f"\n学科：{data.subject}" if data.subject else ""
        messages = [
            {"role": "system", "content": SYSTEM_ANSWER_STREAM},
            {"role": "user", "content": f"题目：{data.question_text[:2000]}{subject_hint}"},
        ]
        try:
            async for delta in deepseek_client.chat_stream(messages, max_tokens=2500):
                delta = deepseek_client.latex_friendly(delta)
                # SSE 标准：多行内容拆成多个 data: 行（前端按 \n 还原）
                for part in delta.split("\n"):
                    yield f"data: {part}\n"
                yield "\n"
        except Exception as e:
            yield f"data: ⚠️ AI 服务暂时不可用：{e}\n\n"
        yield "event: done\ndata: done\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/knowledge-point")
async def knowledge_point(body: dict):
    """知识点系统学习（SSE 流式）"""
    question_text = (body.get("question_text") or "").strip()[:2000]
    knowledge = (body.get("knowledge_point") or "").strip()[:100]
    subject = (body.get("subject") or "").strip()[:30]
    if not question_text:
        return {"code": 40001, "message": "缺少题目", "data": None}

    async def gen():
        messages = [
            {"role": "system", "content": SYSTEM_KNOWLEDGE},
            {"role": "user", "content": f"知识点：{knowledge or '（未分类）'}\n题目：{question_text}"},
        ]
        try:
            # 知识点讲解：显式快速模式（thinking=off）+ 60s 超时保护（防止流式卡住一直转圈）
            from app.services.chat_service import _timed
            gen = deepseek_client.chat_stream(messages, max_tokens=2500, thinking="off")
            async for delta in _timed(gen, 60):
                for part in delta.split("\n"):
                    yield f"data: {part}\n"
                yield "\n"
        except asyncio.TimeoutError:
            yield "data: ⏳ 生成超时，请重试或换个问法\n\n"
        except Exception as e:
            yield f"data: ⚠️ AI 服务暂时不可用：{e}\n\n"
        yield "event: done\ndata: done\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/geogebra")
def geogebra_commands(body: dict):
    """根据几何题生成 GeoGebra 命令（一次性返回）"""
    question_text = (body.get("question_text") or "").strip()[:2000]
    subject = (body.get("subject") or "").strip()[:30]
    if not question_text:
        return {"code": 40001, "message": "缺少题目", "data": None}
    text = deepseek_client._chat_text(
        SYSTEM_GEOGEBRA,
        f"学科：{subject or '通用'}\n题目：{question_text}",
        temperature=0.2, max_tokens=1500)
    if not text:
        return ok({"commands": [], "message": "AI 生成失败"})
    lines = [l.strip() for l in text.split("\n") if l.strip() and not l.strip().startswith("//")]
    return ok({"commands": lines})


@router.post("/review-question")
async def review_question(body: dict):
    """AI 审核错题：检查题目-答案-解析的正确性，返回修正建议（可一键应用）"""
    question_text = (body.get("question_text") or "").strip()[:2000]
    answer = (body.get("answer") or "").strip()[:800]
    analysis = (body.get("analysis") or "").strip()[:1500]
    if not question_text:
        return {"code": 40001, "message": "缺少题目", "data": None}
    from app.services.chat_service import SYSTEM_VERIFY
    prompt = (
        "请审核这道错题的【答案】和【解析】是否正确完整（数学推导、符号、区域、数值）。\n"
        f"题目：{question_text}\n"
        f"答案：{answer or '（空）'}\n"
        f"解析：{analysis or '（空）'}\n\n"
        "输出严格 JSON（不要多余文字）：\n"
        "{\"correct\": true/false, \"issue\": \"问题描述（无则空字符串）\", "
        "\"suggested_answer\": \"修正后的答案（无则保持原文）\", "
        "\"suggested_analysis\": \"修正后的解析（无则保持原文）\"}"
    )
    text = await asyncio.to_thread(
        deepseek_client._chat_json, SYSTEM_VERIFY, prompt,
        temperature=0.1, max_tokens=800)
    if not isinstance(text, dict):
        return ok({"correct": True, "issue": "", "suggested_answer": "", "suggested_analysis": ""})
    return ok({
        "correct": bool(text.get("correct", True)),
        "issue": str(text.get("issue", "") or ""),
        "suggested_answer": deepseek_client.latex_friendly(str(text.get("suggested_answer", "") or "")),
        "suggested_analysis": deepseek_client.latex_friendly(str(text.get("suggested_analysis", "") or "")),
    })


@router.post("/fix-formulas")
async def fix_formulas(body: dict):
    """一键修正：AI 修复题目/答案/解析中未正常转化的数学公式符号"""
    question_text = (body.get("question_text") or "").strip()
    answer = (body.get("answer") or "").strip()
    analysis = (body.get("analysis") or "").strip()
    if not question_text:
        return {"code": 40001, "message": "缺少题目", "data": None}
    prompt = (
        "你是数学公式符号修正助手。修复下面文本中所有【未正常转化的数学公式符号】：\n"
        "1. 残留的 LaTeX 命令改为符号：\iint→∬、\iiint→∭、\int→∫、\sum→∑、\prod→∏、"
        "\oint→∮、\times→×、\cdot→·、\pm→±、\rightarrow→→、\leq→≤、\geq→≥、\neq→≠、"
        "\infty→∞、\pi→π、\alpha→α、\beta→β、\theta→θ、\Delta→Δ\n"
        "2. 但 \frac、\sqrt、^{}、_{}、\left、\right、\begin 等【结构命令保留】（渲染必需）\n"
        "3. 纠正明显的 OCR 误识别（如全角括号、字母/数字混淆、乱码）\n"
        "4. 只修公式符号，绝不改动题目内容文字和数字\n\n"
        f"题目：{question_text}\n"
        f"答案：{answer or '（空）'}\n"
        f"解析：{analysis or '（空）'}\n\n"
        "输出严格 JSON：{\"question_text\": \"修正后的题目\", \"answer\": \"修正后的答案\", \"analysis\": \"修正后的解析\"}"
    )
    text = await asyncio.to_thread(
        deepseek_client._chat_json, "你是数学公式符号修正助手，严格输出 JSON。", prompt,
        temperature=0.1, max_tokens=1500)
    if not isinstance(text, dict):
        text = {}
    # 双保险：AI 修正 + 规则替换兜底（AI 漏掉的残留命令也统一转换）
    return ok({
        "question_text": deepseek_client.latex_friendly(str(text.get("question_text") or question_text)),
        "answer": deepseek_client.latex_friendly(str(text.get("answer") or answer)),
        "analysis": deepseek_client.latex_friendly(str(text.get("analysis") or analysis)),
    })
