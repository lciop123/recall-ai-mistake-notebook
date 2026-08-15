# -*- coding: utf-8 -*-
"""AI 对话：会话 CRUD + SSE 流式 + 一键加入错题本 + 图片问答"""
import asyncio
import base64
import json
import logging
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator

logger = logging.getLogger(__name__)

from sqlmodel import Session, select

from app.ai import deepseek_client
from app.services.math_tool import TOOL_SCHEMA, run_math_calc
from app.ai import ocr_service
from app.core.config import IMAGE_DIR
from app.core.exceptions import AppError
from app.models.models import get_engine, Conversation, Message, Question
from app.services import question_service


def save_image(data: bytes, content_type: str) -> dict:
    """保存对话图片到 data/images/chat/，返回 image_path（相对 /images）"""
    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(content_type, ".png")
    d = IMAGE_DIR / "chat"
    d.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex[:12]}{ext}"
    (d / name).write_bytes(data)
    return {"image_path": f"chat/{name}", "url": f"/images/chat/{name}"}


def list_conversations() -> list:
    with Session(get_engine()) as s:
        rows = s.exec(select(Conversation).order_by(Conversation.updated_at.desc()).limit(50)).all()
        out = []
        for c in rows:
            last = s.exec(select(Message).where(Message.conversation_id == c.id)
                          .order_by(Message.created_at.desc()).limit(1)).first()
            out.append({"id": c.id, "title": c.title, "last": last.content[:40] if last else "",
                        "updated_at": str(c.updated_at)})
        return out


def create_conversation() -> dict:
    with Session(get_engine()) as s:
        c = Conversation(title="新对话")
        s.add(c)
        s.commit()
        s.refresh(c)
        return {"id": c.id, "title": c.title, "created_at": str(c.created_at)}


def create_inherited_conversation(from_id: int, last_count: int = 20) -> dict:
    """创建继承上下文的新会话：模型会带上源会话最近 N 条消息，界面从空白开始。"""
    with Session(get_engine()) as s:
        src = s.get(Conversation, from_id)
        if not src:
            raise AppError(40400, "源会话不存在", 404)
        count = max(1, min(int(last_count or 20), 50))
        c = Conversation(title="新对话（继承上下文）", inherit_from_id=src.id, inherit_last_count=count)
        s.add(c)
        s.commit()
        s.refresh(c)
        return {"id": c.id, "title": c.title, "inherit_from_id": c.inherit_from_id, "inherit_last_count": c.inherit_last_count}


def _conversation_messages(s, conv_id: int):
    """当前会话消息 + 继承上下文（源会话最近 N 条），按时间正序。
    继承的消息只在给模型时出现，不写入当前会话、不在界面展示。"""
    msgs = list(s.exec(select(Message).where(Message.conversation_id == conv_id)
                       .order_by(Message.created_at.asc()).limit(20)).all())
    conv = s.get(Conversation, conv_id)
    if conv and conv.inherit_from_id:
        inherited = list(s.exec(select(Message).where(Message.conversation_id == conv.inherit_from_id)
                                .order_by(Message.created_at.desc())
                                .limit(conv.inherit_last_count or 20)).all())
        inherited.reverse()
        msgs = inherited + msgs
    return msgs


def get_messages(conv_id: int) -> list:
    with Session(get_engine()) as s:
        rows = s.exec(select(Message).where(Message.conversation_id == conv_id)
                      .order_by(Message.created_at.asc())).all()
        return [{"id": m.id, "role": m.role, "content": m.content,
                 "image_path": m.image_path,
                 "image_url": f"/images/{m.image_path}" if m.image_path else None,
                 "created_at": str(m.created_at)} for m in rows]


def delete_conversation(conv_id: int):
    with Session(get_engine()) as s:
        c = s.get(Conversation, conv_id)
        if not c:
            raise AppError(40400, "会话不存在", 404)
        msgs = s.exec(select(Message).where(Message.conversation_id == conv_id)).all()
        for m in msgs:
            s.delete(m)
        s.delete(c)
        s.commit()


def regenerate(conv_id: int, message_id: int) -> dict:
    """重新生成：删除指定 AI 消息及其之后的消息，返回最后一条用户消息用于重新提问"""
    with Session(get_engine()) as s:
        target = s.get(Message, message_id)
        if not target or target.conversation_id != conv_id or target.role != "assistant":
            raise AppError(40001, "消息不存在或类型不符", 400)
        msgs = s.exec(select(Message).where(Message.conversation_id == conv_id)
                      .order_by(Message.created_at.asc())).all()
        # 删除该消息及之后所有消息
        deleting = False
        last_user = None
        last_user_image = None
        for m in msgs:
            if m.id == target.id:
                deleting = True
            if deleting:
                s.delete(m)
            elif m.role == "user":
                last_user = m.content
                last_user_image = m.image_path
        s.commit()
        if last_user is None:
            raise AppError(40001, "没有可重新生成的消息", 400)
        return {"last_user_content": last_user, "last_user_image": last_user_image}


def _save(conv_id: int, role: str, content: str, image_path: str | None = None) -> int:
    # 会话内容也可能来自 OCR 或 AI 流，落库前走和错题相同的公式清洗路径。
    content = deepseek_client.normalize_math_text(content)
    with Session(get_engine()) as s:
        m = Message(conversation_id=conv_id, role=role, content=content, image_path=image_path)
        s.add(m)
        c = s.get(Conversation, conv_id)
        if c:
            c.updated_at = datetime.now()
            if role == "user" and c.title == "新对话":
                c.title = (content or "图片提问")[:20]
            s.add(c)
        s.commit()
        s.refresh(m)
        return m.id


def _to_multimodal(role: str, content: str, image_path: str | None = None) -> dict:
    """把历史消息转成 LLM 消息（带图时用多模态 content 数组）"""
    if image_path:
        try:
            img = (IMAGE_DIR / image_path).read_bytes()
            b64 = base64.b64encode(img).decode()
            return {"role": role, "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": content or "请分析这张图片"},
            ]}
        except Exception:
            pass
    return {"role": role, "content": content or "（图片）"}


def _timed(agen, seconds: float):
    """包装异步生成器：两次产出间隔超过 seconds 秒则抛 asyncio.TimeoutError（用于思考模式超时保护）"""
    import asyncio

    async def wrap():
        it = agen.__aiter__()
        while True:
            try:
                item = await asyncio.wait_for(it.__anext__(), timeout=seconds)
            except StopAsyncIteration:
                return
            yield item

    return wrap()


# 数学/理科题启发式检测（命中才触发 AI 复核，闲聊不消耗）
_MATH_RE = re.compile(
    r"[∫√∑∂π∇∞]|\\frac|\\int|\\sqrt|\\sum|x\^|sin|cos|tan|log|ln|"
    r"方程|函数|积分|导数|极限|证明|计算|求解|求值|不等式|数列|三角|几何|概率|统计|矩阵|向量|椭圆|双曲线|抛物线",
    re.I,
)


def _is_math(text: str) -> bool:
    return bool(text and _MATH_RE.search(text))


_MULTI_Q_RE = re.compile(
    r'例\s*[一二三四五六七八九十1234567890]|第[一二三四五六七八九十1234567890]+题|'
    r'^\s*[（(]?[1234567890][)）、.]\s*[^。\n]{4,}|[①②③④⑤⑥⑦⑧⑨⑩]', re.M)


def _is_complex_math(text: str) -> bool:
    """复杂数学题检测：多题连问（例1/例2、第1题、①②③ 等）或超长题面 → 需深度思考"""
    if not _is_math(text):
        return False
    if _MULTI_Q_RE.search(text):
        return True
    return len(text) > 260


def _build_question_context() -> str:
    """构建错题本上下文：最近错题 + 薄弱知识点（截断控制 token）"""
    try:
        from app.models.models import Question
        from sqlmodel import select as _select
        with Session(get_engine()) as s:
            rows = s.exec(_select(Question).order_by(Question.created_at.desc()).limit(6)).all()
            if not rows:
                return ""
            items = []
            for q in rows:
                qs = (q.question_text or "").replace("\n", " ")[:80]
                reason = (q.error_reason or "").replace("\n", " ")[:40]
                items.append(f"- [{q.subject or ''}] {qs}{('（错因：' + reason + '）') if reason else ''}")
            return "最近错题：\n" + "\n".join(items)[:900]
    except Exception:
        return ""


SYSTEM_VERIFY = (
    "你是数学/理科答案复核员。检查以下题目与解答：\n"
    "1. 解题方法是否正确（如曲线积分先判断闭/开曲线、格林公式适用条件、补线方向等）；\n"
    "2. 【重点】补线后的区域面积：开弧补线围成的通常只是曲线的一部分。例如本题：A、B 在直线 y=x 上且直线过椭圆中心 → 区域是半椭圆，面积 = π/(2√3) ≈ 0.9069，闭合积分应为 6×0.9069 ≈ 5.44；若解答用了整椭圆面积 π/√3 ≈ 1.8138（闭合积分 ≈ 2√3π ≈ 10.88）或答案数值明显偏大，一律判为 incorrect！\n"
    "3. 计算过程有无错误（代数、符号、积分限、奇偶性、公式推导）；\n"
    "4. 最终答案数值/符号/量级是否合理：开弧积分数值不应等于或超过整椭圆/整圆积分；是否答非所问；\n"
    "5. 解答是否给出最终结果：以'需要计算机软件'、'太复杂'、'无法计算'、'留给读者'等结束、或没有明确最终答案的，一律判为 incorrect！\n"
    "6. 只判断对错，不要自己重新解题，不要输出解题过程。\n"
    "只输出严格 JSON：{\"correct\": true 或 false, \"issue\": \"若错误，简述核心问题（30字内）\"}\n"
    "不要输出其他任何内容。"
)


async def solve_question(conv_id: int | None, user_content: str,
                        image_path: str | None = None,
                        thinking: str = "off",
                        model_key: str = "main",
                        temperature: float | None = None,
                        detail: str = "standard",
                        use_my_questions: bool = True,
                        question_text: str | None = None) -> dict:
    """一次性求解（新架构核心）：非流式生成 → 工具计算 → 复核 → 返回完整结果。
    数学题专用；后端完成全部工作，前端零解析。"""
    import json as _json
    if conv_id is None:
        c = create_conversation()
        conv_id = c["id"]
    _save(conv_id, "user", user_content, image_path=image_path)
    with Session(get_engine()) as s:
        msgs = _conversation_messages(s, conv_id)
        # 统一纯文本历史：主模型（DeepSeek）无视觉，历史图片消息不能以 image_url 发送（否则 400），
        # 图片内容只通过当前请求的 OCR 分支转成文字；历史图片消息保留文字部分。
        history = [{"role": m.role, "content": m.content or ""} for m in msgs]
        if history and history[-1]["role"] == "user" and not history[-1]["content"]:
            history[-1]["content"] = "（图片）"
    # 图片：OCR 提取文字交给主模型（若用户提供 question_text 则直接用，跳过 OCR）
    ocr_text = ""
    ocr_confident = False
    ocr_sources: list[str] = []
    _solve_t0 = time.time()  # 总超时从 OCR 开始计时
    _SOLVE_TIMEOUT = 600     # 主循环总超时（秒）：极长保险（10 分钟），正常不触发——让模型把题算完
    if image_path:
        if question_text and question_text.strip():
            # 用户编辑/提供的题面：优先使用
            ocr_text = question_text.strip()
            ocr_confident = True
            history = [{"role": m.role, "content": m.content or ""} for m in msgs]
            if history and history[-1]["role"] == "user":
                history[-1]["content"] += f"\n\n【图片题目文字（用户确认版，请据此解题）】：\n{ocr_text}"
            user_content = f"{user_content}\n{ocr_text}"
        else:
            try:
                # 交叉验证：多模型识别 + 一致性比对（线程池异步执行，避免同步 OCR 阻塞 event loop 导致 health 无响应）
                ocr_text, ocr_conf, ocr_sources = await asyncio.to_thread(
                    ocr_service.recognize_cross,
                    (IMAGE_DIR / image_path).read_bytes())
                ocr_text = (ocr_text or "").strip()
                ocr_text = deepseek_client.latex_friendly(ocr_text)
                ocr_confident = ocr_conf == "high"
                if len(ocr_text) > 5:
                    history = [{"role": m.role, "content": m.content or ""} for m in msgs]
                    if history and history[-1]["role"] == "user":
                        ocr_flag = "✅" if ocr_confident else "⚠️"
                        history[-1]["content"] += f"\n\n【图片题目文字（OCR 交叉验证{ocr_flag}，请据此解题）】：\n{ocr_text}"
                    user_content = f"{user_content}\n{ocr_text}"
                else:
                    # OCR 为空：降级为纯文本（去掉图片消息，避免主模型不支持 image_url 报错）
                    history = [{"role": m.role, "content": m.content or ""} for m in msgs]
                    if history and history[-1]["role"] == "user":
                        history[-1]["content"] += "\n\n（图片未能自动识别，请手打题目文字后重新发送）"
            except Exception as e:
                logger.warning("solve OCR 失败: %s", e)
                # 降级为纯文本，避免 400
                history = [{"role": m.role, "content": m.content or ""} for m in msgs]
                if history and history[-1]["role"] == "user":
                    history[-1]["content"] += "\n\n（图片未能自动识别，请手打题目文字后重新发送）"
    # 自动调配：数学题 → 低温度(严谨) + 详尽；其他 → 平衡 + 标准
    is_math_q = _is_math(user_content)
    if temperature is None:
        temperature = 0.1 if is_math_q else 0.3
    if detail == "standard" and is_math_q:
        detail = "detailed"
    # 系统提示词
    system = deepseek_client.SYSTEM_CHAT
    if detail == "brief":
        system += "\n回答要求【简明】：只给核心思路、关键步骤和最终答案（3-5 步内），不展开多余内容。"
    elif detail == "detailed":
        system += ("\n回答要求【详尽】：像老师讲课一样：先讲思路来源，分步完整推导，"
                   "多种方法对比（如可用），最后给出易错点总结。")
    if use_my_questions:
        weak = _build_question_context()
        if weak:
            system += "\n\n【用户错题本背景（仅供参考，可结合回答）】\n" + weak
    history.insert(0, {"role": "system", "content": system})

    # 生成（带工具，最多 3 轮；任何模式都给足预算，保证算完）
    # 非数学题（知识点讲解/知识问答）：不需要思考模式，强制快速（off）
    if not _is_math(user_content):
        thinking = "off"
    # 复杂数学题（多题连问/超长题面）自动升级深度思考：用户无需手动切换（实测深度模式才做得对）
    if thinking != "deep" and _is_complex_math((user_content + "\n" + ocr_text).strip()):
        logger.warning("复杂数学题自动升级深度思考: 题面长度=%d", len(user_content) + len(ocr_text))
        thinking = "deep"

    # 输出长度预算（按题型自动调配）：知识/快速问答精简回答，数学题完整推导
    if not _is_math(user_content):
        _budget = 1200 if len(user_content) < 80 else 3000   # 短问题精炼（5-20s）；长讲解适中
        # 短问题追加简洁指令：让模型直接答要点，不写长篇
        if len(user_content) < 80 and history and history[-1]["role"] == "user":
            history[-1]["content"] += "\n\n（快速问答：请直接简洁回答，说清要点即可，不要写长篇）"
    else:
        _budget = 16000                                      # 数学题：完整推导不截断

    content = ""
    for _round in range(6):
        if time.time() - _solve_t0 > _SOLVE_TIMEOUT:
            logger.warning("solve 主循环超时(%ss)，跳出交兜底", int(time.time() - _solve_t0))
            break
        # 不用任何数学工具：模型直接推导解答（工具调用易误导且格式不稳）
        try:
            # 单次 AI 调用加 180s 超时：防止模型服务端挂起导致前端无限转圈
            c, tcs, rc = await asyncio.wait_for(
                deepseek_client.chat_complete(
                    history, thinking=thinking, tools=None,
                    model_key=model_key, temperature=temperature, max_tokens=_budget),
                timeout=180)
        except asyncio.TimeoutError:
            logger.warning("solve 单次生成超时(180s)，跳出交兜底")
            break
        if not tcs:
            content = c
            break
        # 理论上无工具不会出现 tcs；若出现（文本格式残留）则清理后作为内容
        content = c or ""
        break
    else:
        content = c or ""

    # 复核（数学题）：循环最多 2 轮——未算完/答案错误都会自动重答，保证任何模式都算完
    if content and _is_math(user_content):
        import re as _re
        for _rv in range(3):
            if not content:
                break
            # 未完成检测：尾部没有最终答案特征 → 判定未算完
            tail = content[-600:]
            unfinished = not bool(_re.search(r'boxed|答案\s*[：:]|最终结果|最终答案|结论', tail))
            verdict = None
            if not unfinished:
                try:
                    # 复核：纯模型判断（不用工具，避免误导）
                    verdict = await asyncio.to_thread(
                        deepseek_client._chat_json, SYSTEM_VERIFY,
                        f"题目：{user_content}\n\nAI解答：\n{content[:2500]}",
                        temperature=0.1, max_tokens=400)
                except Exception:
                    verdict = None
            if not (unfinished or (verdict is not None and verdict.get("correct") is False)):
                break  # 已算完且复核通过
            reason = ("上次解答未完成，必须算到最后给出最终答案"
                      if unfinished else ("存在错误：" + str(verdict.get("issue", ""))[:80]))
            reason += "。请重新完整推导一遍，务必检查符号与区域（如补线方向、正负号、半椭圆 vs 整椭圆面积），数值自洽后再给出最终答案"
            retry = list(history)
            if retry and retry[-1].get("role") == "user":
                retry[-1] = {**retry[-1],
                             "content": (retry[-1].get("content") or "")
                             + "\n\n【复核反馈】" + reason + "。请重新完整解答，必须给出最终答案，禁止省略。"}
            c2, tcs2, _rc2 = await deepseek_client.chat_complete(
                retry, thinking="off", tools=None,
                model_key=model_key, temperature=temperature, max_tokens=16000)
            if not tcs2 and c2:
                content = c2
            else:
                break  # 重答失败，保留原内容

    # 终极兜底：内容仍为空 → 快速模式（无工具）重试一次，保证有回答
    if not content:
        try:
            c3, tcs3, _rc3 = await asyncio.wait_for(
                deepseek_client.chat_complete(
                    history, thinking="off", tools=None,
                    model_key=model_key, temperature=0.3),
                timeout=120)
            if not tcs3 and c3:
                content = c3
        except asyncio.TimeoutError:
            logger.warning("solve 兜底超时，返回超时提示")
            content = "⏳ 题目较复杂，生成超时。可换「⚡快」模式，或把题目拆成小题重新提问。"
        except Exception as e:
            logger.warning("solve 兜底重试失败: %s", e)
    # 最后清理内容中的工具调用残留标记（XML / DSML / 全角竖线变体）
    # 工具调用残留无保留价值：从标记处直接删到结尾（保留标记之前的正文）
    if content:
        import re as _re2
        content = _re2.sub(r'<tool_calls>.*$', '', content, flags=_re2.S)
        _FF2 = chr(0xFF5C)  # 全角竖线 ｜
        content = _re2.sub(r'<[\s|' + _FF2 + r']*DSML[\s|' + _FF2 + r']*tool_calls[\s|' + _FF2 + r']*>.*$', '', content, flags=_re2.S)
        content = _re2.sub(r'<\s*tool_calls\s*>.*$', '', content, flags=_re2.S)
        content = content.strip()
    # 常用 LaTeX 命令转 Unicode（\iint → ∬），源码/预览都友好显示
    if content:
        content = deepseek_client.latex_friendly(content)
    assistant_msg_id = _save(conv_id, "assistant", content or "（未能生成回答，请重试）")
    # ocr_text：图片题附带识别文本，前端展示供用户核对（OCR 可能误读上下标）
    ocr_out = ocr_text if image_path else ""
    return {"conv_id": conv_id, "message_id": assistant_msg_id, "content": content,
            "ocr_text": ocr_out, "ocr_confident": ocr_confident,
            "ocr_sources": ocr_sources}


async def stream_solve_question(conv_id: int | None, user_content: str,
                                image_path: str | None = None,
                                thinking: str = "standard",
                                model_key: str = "main",
                                temperature: float | None = None,
                                detail: str = "standard",
                                use_my_questions: bool = True,
                                question_text: str | None = None) -> AsyncGenerator[str, None]:
    """求解 SSE：先推送可见阶段，再把已复核的终稿平滑分块送出。

    数学题必须在服务端完成复核后再展示，避免中途流出错误结论；等待期间通过
    stage/heartbeat 事件保持界面可感知，最终内容按小块输出而不是一次性灌入。
    """
    def event(name: str, payload: dict) -> str:
        return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    yield event("stage", {"text": "已收到问题，正在准备解答"})
    if image_path:
        yield event("stage", {"text": "正在并行识别图片中的题目与公式"})
    else:
        yield event("stage", {"text": "正在分析题意并组织推导"})

    task = asyncio.create_task(solve_question(
        conv_id, user_content, image_path=image_path, thinking=thinking,
        model_key=model_key, temperature=temperature, detail=detail,
        use_my_questions=use_my_questions, question_text=question_text,
    ))
    stages = [
        "正在推导关键步骤…",
        "正在检查计算与逻辑…",
        "正在复核最终答案…",
        "正在整理清晰的讲解…",
    ]
    stage_idx = 0
    try:
        while not task.done():
            try:
                result = await asyncio.wait_for(asyncio.shield(task), timeout=3.5)
                break
            except asyncio.TimeoutError:
                yield event("stage", {"text": stages[min(stage_idx, len(stages) - 1)]})
                stage_idx += 1
        else:
            result = await task
    except asyncio.CancelledError:
        # 浏览器主动停止/断开 SSE 时，取消尚未结束的求解，避免后台继续耗时并写入无效会话消息。
        if not task.done():
            task.cancel()
        raise
    except Exception as exc:
        logger.exception("solve-stream 失败")
        yield event("error", {"message": str(getattr(exc, "message", exc)) or "求解失败，请重试"})
        return

    content = result.get("content") or "No answer was generated. Please retry."
    yield event("meta", {
        "conv_id": result.get("conv_id"), "message_id": result.get("message_id"),
        "ocr_text": result.get("ocr_text") or "",
        "ocr_confident": bool(result.get("ocr_confident")),
        "ocr_sources": result.get("ocr_sources") or [],
    })
    yield event("stage", {"text": "解答已完成，正在呈现内容"})
    # 小块 + 极短让步：即使结果由完整复核后返回，页面也能稳定、连续地生长。
    for start in range(0, len(content), 28):
        yield event("delta", {"text": content[start:start + 28]})
        await asyncio.sleep(0.014)
    yield event("done", {"conv_id": result.get("conv_id"), "message_id": result.get("message_id")})


async def stream_chat(conv_id: int | None, user_content: str,
                      image_path: str | None = None,
                      thinking: str = "off",
                      model_key: str = "main",
                      temperature: float = 0.3,
                      detail: str = "standard",
                      use_my_questions: bool = True) -> AsyncGenerator[str, None]:
    if conv_id is None:
        c = create_conversation()
        conv_id = c["id"]
    _save(conv_id, "user", user_content, image_path=image_path)
    with Session(get_engine()) as s:
        msgs = _conversation_messages(s, conv_id)
        history = [_to_multimodal(m.role, m.content, m.image_path) for m in msgs]
    use_vision = any(isinstance(m["content"], list) for m in history)
    # 图片提问：先用 GLM-4V 提取题目文字（OCR），交给主模型解答。
    # 视觉模型数学能力弱（读题常错、不调用计算工具），OCR + 主模型(工具+复核) 质量高得多。
    if use_vision:
        ocr_text = ""
        img_path = None
        for m in msgs:
            if m.image_path:
                img_path = m.image_path
        if img_path:
            try:
                ocr_text = (ocr_service.recognize((IMAGE_DIR / img_path).read_bytes()) or "").strip()
            except Exception as e:
                logger.warning("图片 OCR 失败: %s", e)
        if len(ocr_text) > 5:
            # OCR 成功：转纯文本交给主模型
            text_history = []
            for m in msgs:
                if m.image_path:
                    text_history.append({"role": m.role,
                                         "content": (m.content or "（图片题目）")})
                else:
                    text_history.append({"role": m.role, "content": m.content or ""})
            if text_history and text_history[-1]["role"] == "user":
                text_history[-1]["content"] += f"\n\n【图片题目文字（OCR 识别，请据此解题）】：\n{ocr_text}"
            history = text_history
            use_vision = False
            user_content = f"{user_content}\n{ocr_text}"  # 用于数学检测/复核
    # 数学题缓冲模式：先内部生成+复核，通过后才输出（避免"先看到答案再被纠正"）
    buffer_mode = _is_math(user_content) and not use_vision
    # 注入系统提示词（Markdown + LaTeX 输出规范 + 详细度 + 错题本上下文）
    system = deepseek_client.SYSTEM_CHAT
    if detail == "brief":
        system += "\n回答要求【简明】：只给核心思路、关键步骤和最终答案（3-5 步内），不展开多余内容。"
    elif detail == "detailed":
        system += ("\n回答要求【详尽】：像老师讲课一样：先讲思路来源，分步完整推导，"
                   "多种方法对比（如可用），最后给出易错点总结。")
    if use_my_questions:
        weak = _build_question_context()
        if weak:
            system += "\n\n【用户错题本背景（仅供参考，可结合回答）】\n" + weak
    history.insert(0, {"role": "system", "content": system})
    full = ""
    timeout_sec = {"standard": 60, "deep": 150}.get(thinking, 0)
    tool_round = 0  # 工具调用轮次（最多 4 轮防死循环）
    try:
        while True:
            gen = deepseek_client.chat_stream(history, use_vision=use_vision,
                                              thinking=thinking, tools=None,
                                              model_key=model_key, temperature=temperature)
            if timeout_sec:
                gen = _timed(gen, timeout_sec)
            pending_tool = None
            round_full = ""
            try:
                async for delta in gen:
                    if delta.startswith("event: tool_call"):
                        # 模型请求调用工具：解析并暂停流式（由上层执行后二轮请求）
                        import json as _json
                        pending_tool = _json.loads(delta[len("event: tool_call\ndata: "):])
                        continue
                    if delta.startswith("event: "):
                        yield delta
                        continue
                    round_full += delta
                    if not buffer_mode:
                        # 非数学题：实时流式输出
                        for part in delta.split("\n"):
                            yield f"data: {part}\n"
                        yield "\n"
                    # 数学题（buffer_mode）：先缓冲，复核通过后再统一输出
            except AppError as e:
                # 备用模型不可用（key 失效/接口错误）→ 自动降级主模型重试，不空回复
                if model_key == "alt":
                    logger.warning("备用模型调用失败，降级主模型: %s", e)
                    yield "event: tool\ndata: ⚠️ 备用模型不可用，已自动切换主模型\n\n"
                    model_key = "main"
                    continue
                raise
            if pending_tool and tool_round < 4 and False:  # 已禁用数学工具（用户要求：不用积分工具，避免误导）
                tool_round += 1
                # 1) 先组装 assistant tool_calls 消息（必须在 tool 消息之前）
                assistant_tc = []
                for tc in pending_tool:
                    assistant_tc.append({
                        "id": tc.get("id") or f"call_{tool_round}_{len(assistant_tc)}",
                        "type": "function",
                        "function": {"name": tc.get("name") or "math_calc",
                                     "arguments": tc.get("args") or "{}"},
                    })
                history.append({"role": "assistant", "content": None, "tool_calls": assistant_tc})
                # 2) 执行工具并追加 tool 结果（与 tool_calls 一一对应）
                for i, tc in enumerate(pending_tool):
                    try:
                        args = _json.loads(tc.get("args") or "{}")
                    except Exception:
                        args = {}
                    expr = str(args.get("expr", ""))
                    note = str(args.get("note", ""))
                    result = run_math_calc(expr)
                    logger.info("math_calc: %s -> %s", expr, result[:60])
                    # 前端展示计算过程
                    yield f"event: tool\ndata: {note or expr}\n\n"
                    history.append({"role": "tool", "tool_call_id": assistant_tc[i]["id"],
                                    "content": result})
                # 3) 第二轮：模型基于工具结果继续（流式输出最终答案）
                continue
            full += round_full
            break
    except asyncio.TimeoutError:
        # 思考超时（模型思考链过长）→ 中断，由 finally 兑底降级快速回答
        logger.warning("思考模式超时(%.0fs)，降级快速回答", timeout_sec)
        full = ""
    finally:
        # 兑底：思考模式回答为空（模型思考链耗尽输出预算）→ 自动降级快速模式重试，保证用户总能拿到回答
        if not full and not use_vision and thinking != "off":
            yield "event: thinking\ndata: 0\n\n"  # 结束思考状态
            try:
                async for delta in deepseek_client.chat_stream(history, use_vision=False, thinking="off",
                                                                  model_key=model_key, temperature=temperature):
                    if delta.startswith("event: "):
                        continue
                    full += delta
                    if not buffer_mode:
                        for part in delta.split("\n"):
                            yield f"data: {part}\n"
                        yield "\n"
            except Exception as e:
                logger.warning("兑底重试失败: %s", e)
        # —— AI 复核（仅数学/理科题；图片题跳过，复核看不懂图）——
        if full and not use_vision and _is_math(user_content):
            yield "event: review\ndata: 1\n\n"  # 复核中
            try:
                verdict = await asyncio.to_thread(
                    deepseek_client._chat_json, SYSTEM_VERIFY,
                    f"题目：{user_content}\n\nAI解答：\n{full[:3000]}",
                    temperature=0.1, max_tokens=300,
                )
            except Exception as e:
                verdict = None
                logger.warning("复核调用失败: %s", e)
            if verdict is not None and verdict.get("correct") is False:
                # 复核未通过：携带复核问题重新生成（快速模式，避免再犯同样错误）
                issue = str(verdict.get("issue", ""))[:80]
                yield "event: review\ndata: 2\n\n"  # 重答中
                full = ""
                retry_history = list(history)
                if retry_history and retry_history[-1].get("role") == "user":
                    retry_history[-1] = {
                        **retry_history[-1],
                        "content": (retry_history[-1].get("content") or "")
                        + f"\n\n【复核反馈】上次解答存在错误：{issue}。请重新完整解答，必须给出最终答案，禁止省略、禁止说需要计算机软件。",
                    }
                try:
                    async for delta in deepseek_client.chat_stream(retry_history, use_vision=False, thinking="off",
                                                                          model_key=model_key, temperature=temperature):
                        if delta.startswith("event: "):
                            continue
                        full += delta
                        if not buffer_mode:
                            for part in delta.split("\n"):
                                yield f"data: {part}\n"
                            yield "\n"
                except Exception as e:
                    logger.warning("复核重答失败: %s", e)
            else:
                yield "event: review\ndata: 0\n\n"  # 复核通过
        # 数学题缓冲模式：复核完成后统一输出最终内容（用户看到的就是终稿）
        if buffer_mode and full:
            for part in full.split("\n"):
                yield f"data: {part}\n"
            yield "\n"
        assistant_msg_id = None
        if full:
            assistant_msg_id = _save(conv_id, "assistant", full)
        # done 事件回传会话 id 与真实消息 id（前端需用真实 id 做重新生成/加入错题本）
        yield f"event: done\ndata: {conv_id}\n\n"
        if assistant_msg_id:
            yield f"event: msg\ndata: {assistant_msg_id}\n\n"


def add_question(conv_id: int, message_id: int | None = None) -> dict:
    with Session(get_engine()) as s:
        # 防重复：该消息已提取过错题则拒绝
        if message_id:
            existing = s.exec(select(Question).where(Question.source == "chat",
                                                     Question.source_message_id == message_id)).first()
            if existing:
                raise AppError(40900, "该内容已加入错题本，请勿重复添加", 409)
        msgs = s.exec(select(Message).where(Message.conversation_id == conv_id)
                      .order_by(Message.created_at.desc()).limit(10)).all()
        history = "\n".join(f"{'用户' if m.role == 'user' else 'AI'}：{m.content}" for m in reversed(msgs))
    extracted = deepseek_client.extract_question(history)
    if not extracted:
        raise AppError(40001, "未能从对话中提取出错题，请重试或手动录入", 400)
    return question_service.create_from_extract(extracted, source="chat", source_message_id=message_id)


def added_questions(conv_id: int) -> list:
    """返回该会话已加入错题本的消息 id 列表"""
    with Session(get_engine()) as s:
        msg_ids = [m.id for m in s.exec(select(Message).where(Message.conversation_id == conv_id)).all()]
        if not msg_ids:
            return []
        rows = s.exec(select(Question).where(Question.source == "chat",
                                             Question.source_message_id.in_(msg_ids))).all()
        return [{"message_id": q.source_message_id, "question_id": q.id} for q in rows]
