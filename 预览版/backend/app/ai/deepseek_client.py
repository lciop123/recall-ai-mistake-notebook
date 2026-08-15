# -*- coding: utf-8 -*-
"""DeepSeek API 客户端：统一封装、JSON 输出、流式与降级。

- 未配置 API Key 时：归类返回 None、生成/批改抛 50200（前端降级为原题复习/手动选择）。
- 所有调用走 openai SDK（DeepSeek 兼容 OpenAI 格式）。

LaTeX 转义修复：AI 常在 JSON 里直接写 \\bar 而未转义为 \\\\bar，
json.loads 会把 \\b/\\t/\\f/\\r 解析成控制字符（退格/制表/换页/回车），
导致公式显示为 ar{x}、ext{}、frac 等。这里统一恢复。
"""
import json
import re
import logging
from typing import AsyncGenerator, Optional

from app.core.config import (DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL,
                         ZHIPU_API_KEY, ZHIPU_BASE_URL,
                         LLM_ALT_NAME, LLM_ALT_KEY, LLM_ALT_BASE)
from app.core.exceptions import AppError

logger = logging.getLogger(__name__)

_client = None
_async_client = None
_vision_client = None
_JSON_OPTS = {"response_format": {"type": "json_object"}}

# 控制字符 → LaTeX 反斜杠原样（JSON 未转义反斜杠被解析后留下的痕迹）
_CONTROL_MAP = {
    "\x08": "\\b",   # \b → 退格（bar/beta/begin 等）
    "\x0c": "\\f",   # \f → 换页（frac）
    "\x0b": "\\v",   # \v → 垂直制表（vector）
    "\x07": "\\a",   # \a → 响铃（alpha 前）
    "\t": "\\t",     # \t → 制表（text/times 前）
    "\r": "\\r",     # \r → 回车（rho/right 前）
}

# JSON 把未转义的 LaTeX 解析成控制字符后，命令首字母会被吞掉：
# "\\frac" -> "\x0crac"，"\\text" -> "\text"。仅匹配这些已知后缀，避免破坏普通空白字符。
_CONTROL_LATEX_SUFFIXES = {
    "\x08": ("ar", "egin", "eta", "binom"),
    "\x0c": ("rac", "orall", "unction"),
    "\x0b": ("ec", "dots"),
    "\x07": ("lpha", "rcsin", "rctan"),
    "\t": ("ext", "imes", "an", "heta", "o"),
    "\r": ("ight", "ho"),
}


def repair_latex(text: str) -> str:
    """修复 AI/OCR 文本中的 LaTeX 转义，不把普通制表符误变成 LaTeX。"""
    if not text:
        return text
    out = str(text).replace("\ufffd", "□")
    # JSON 中未转义的 \bar、\frac 等命令可能先变成控制字符；只在后面确实接着命令剩余部分时恢复。
    for ctrl, rep in _CONTROL_MAP.items():
        suffixes = _CONTROL_LATEX_SUFFIXES[ctrl]
        pattern = re.escape(ctrl) + rf"(?={'|'.join(map(re.escape, suffixes))})"
        # replacement 参数会再次解释 \f / \t；用函数返回字面反斜杠命令。
        out = re.sub(pattern, lambda _m, value=rep: value, out)
    # 其余不可见控制字符不是公式内容：清成空格，保留换行和普通回车换行结构。
    out = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", out)
    # 模型有时过度转义，\\frac 只保留一个命令反斜杠。
    out = re.sub(r"\\\\(?=[A-Za-z])", r"\\", out)
    return out


_LATEX_UNICODE_MAP = [
    (r'\iint', '∬'),
    (r'\iiint', '∭'),
    (r'\oint', '∮'),
    (r'\sum', '∑'),
    (r'\prod', '∏'),
    (r'\int', '∫'),
    (r'\times', '×'),
    (r'\cdot', '·'),
    (r'\pm', '±'),
]

# 仅处理安全的简单下标（∬_S / ∬_{ABC} / ∫_0）。复杂下标如 ∫_{\overline{AB}}
# 必须保留其括号结构，不能为了隐藏下划线而篡改公式。
_LATEX_DROP_BRACED_SUB_RE = re.compile(r'([∬∫∮∑∏∭])_\{([A-Za-z0-9]+)\}')
_LATEX_DROP_PLAIN_SUB_RE = re.compile(r'([∬∫∮∑∏∭])_([A-Za-z0-9]+)')


def latex_friendly(text: str) -> str:
    """统一常见公式符号，保证数据库和 SSE 内容不会带控制字符或替换字符。"""
    if not text:
        return text
    out = repair_latex(text)
    # AI 有时输出 \( ... \) / \[ ... \]，统一成前端可识别的定界符。
    out = out.replace(r"\[", "$$").replace(r"\]", "$$")
    out = out.replace(r"\(", "$").replace(r"\)", "$")
    for cmd, uni in _LATEX_UNICODE_MAP:
        out = out.replace(cmd, uni)
    # 去掉 Unicode 符号后的简单字面下划线（∬_S → ∬S），复杂数学下标保持结构。
    out = _LATEX_DROP_BRACED_SUB_RE.sub(r'\1\2', out)
    out = _LATEX_DROP_PLAIN_SUB_RE.sub(r'\1\2', out)
    return out


def normalize_math_text(text: str) -> str:
    """所有用户可见题目、答案、解析的公式规范化入口。"""
    return latex_friendly(str(text or ""))


def repair_latex_deep(obj):
    """递归修复 dict/list/str 结构中的 LaTeX 控制字符。"""
    if isinstance(obj, str):
        return normalize_math_text(obj)
    if isinstance(obj, dict):
        return {k: repair_latex_deep(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [repair_latex_deep(v) for v in obj]
    return obj


def _json_loads_loose(s: str):
    """宽松 JSON 解析：AI 常在 JSON 字符串里未转义 LaTeX 反斜杠（\max、\begin{cases}），
    导致 Invalid \escape。这里把非法转义修复为字面反斜杠后再解析。"""
    import re as _re
    try:
        return json.loads(s)
    except Exception:
        fix = lambda m: "\\\\" + m.group(1)  # \x → \\x（字面反斜杠）
        try:
            return json.loads(_re.sub(r'\\([^"\\/bfnrtu])', fix, s))
        except Exception:
            # 控制字符（\bar→退格 等合法转义残留）再恢复
            s2 = _re.sub(r'\\([^"\\/bfnrtu])', fix, s)
            for ctrl, rep in _CONTROL_MAP.items():
                s2 = s2.replace(ctrl, rep)
            return json.loads(s2)


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(api_key=DEEPSEEK_API_KEY or "sk-none", base_url=DEEPSEEK_BASE_URL)
    return _client


_async_client_alt = None


def _get_async_client(model_key: str = "main"):
    """异步客户端：uvicorn/asyncio 环境下同步 SDK 的流式会被缓冲，流式输出必须用异步客户端。
    model_key: main=主模型, alt=备用模型（对话页可切换）"""
    global _async_client, _async_client_alt
    if model_key == "alt" and LLM_ALT_KEY:
        if _async_client_alt is None:
            from openai import AsyncOpenAI
            _async_client_alt = AsyncOpenAI(api_key=LLM_ALT_KEY, base_url=LLM_ALT_BASE)
        return _async_client_alt
    if _async_client is None:
        from openai import AsyncOpenAI
        _async_client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY or "sk-none", base_url=DEEPSEEK_BASE_URL)
    return _async_client


def _resolve_model(model_key: str) -> str:
    """按模型 key 返回实际模型名"""
    if model_key == "alt" and LLM_ALT_NAME:
        return LLM_ALT_NAME
    return DEEPSEEK_MODEL


def _get_async_vision_client():
    """视觉异步客户端（智谱 GLM-4V-Flash）：DeepSeek 无视觉能力，看图场景走智谱免费视觉模型"""
    global _vision_client
    if _vision_client is None:
        from openai import AsyncOpenAI
        _vision_client = AsyncOpenAI(api_key=ZHIPU_API_KEY or "sk-none", base_url=ZHIPU_BASE_URL)
    return _vision_client


def available() -> bool:
    return bool(DEEPSEEK_API_KEY)


def _chat_text(system: str, user: str, temperature: float = 0.2, max_tokens: int = 1500) -> Optional[str]:
    """请求纯文本输出（非 JSON，如 GeoGebra 命令），429 退避重试"""
    if not available():
        return None
    import time as _time
    for attempt in range(3):
        try:
            resp = _get_client().chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=temperature,
                max_tokens=max_tokens,
                extra_body={"thinking": {"type": "disabled"}},
            )
            return repair_latex(resp.choices[0].message.content or "")
        except Exception as e:
            is_rate = "429" in str(e) or "速率" in str(e)
            if is_rate and attempt < 2:
                wait = 2 * (2 ** attempt)
                logger.warning("LLM 限流，%.0fs 后重试: %s", wait, e)
                _time.sleep(wait)
                continue
            logger.warning("LLM 文本调用失败: %s", e)
            break
    return None


def _chat_json(system: str, user: str, temperature: float = 0.3, max_tokens: int = 2000, retries: int = 3) -> Optional[dict]:
    """请求 JSON 输出；429 限流时指数退避重试；仍失败返回 None"""
    if not available():
        return None
    import time as _time
    for attempt in range(retries):
        try:
            resp = _get_client().chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=temperature,
                max_tokens=max_tokens,
                extra_body={"thinking": {"type": "disabled"}},
                **_JSON_OPTS,
            )
            return repair_latex_deep(_json_loads_loose(resp.choices[0].message.content))
        except Exception as e:
            is_rate = "429" in str(e) or "速率" in str(e) or "rate" in str(e).lower()
            if is_rate and attempt < retries - 1:
                wait = 2 * (2 ** attempt)
                logger.warning("LLM 限流，%.0fs 后重试(%s): %s", wait, attempt + 1, e)
                _time.sleep(wait)
                continue
            logger.warning("LLM JSON 调用失败: %s", e)
            if attempt < retries - 1:
                continue
            break
    return None


SYSTEM_CLASSIFY = (
    "你是教育领域的错题归类助手。根据题目文本，输出 JSON："
    '{"subject": "学科", "knowledge_point": "知识点", "error_type": "错因", "difficulty": "易|中|难"}。'
    'subject 只能取：语文/数学/英语/物理/化学/生物/政治/历史/地理/专业课/其他；'
    'error_type 只能取：概念不清/审题失误/粗心/计算错误/方法不当/超纲/其他。只输出 JSON。'
)


def classify(question_text: str) -> Optional[dict]:
    result = _chat_json(SYSTEM_CLASSIFY, f"题目：{question_text[:2000]}")
    if result is None:
        return None
    return {
        "subject": result.get("subject", "其他"),
        "knowledge_point": str(result.get("knowledge_point", ""))[:64],
        "error_type": result.get("error_type", "其他"),
        "difficulty": result.get("difficulty", "中") if result.get("difficulty") in ("易", "中", "难") else "中",
    }


SYSTEM_SPLIT = (
    "你是一名试卷拆题助手。图片 OCR 文本中可能包含多道题，请识别并拆分，"
    "输出 JSON：{\"questions\": [{\"question_text\": \"题干\", \"answer\": \"答案\", \"analysis\": \"解析\", "
    '"subject": "学科", "knowledge_point": "知识点", "error_type": "错因", "type": "choice|fill|essay"}]}。'
    "subject 取值：语文/数学/英语/物理/化学/生物/政治/历史/地理/专业课/其他；"
    "error_type 取值：概念不清/审题失误/粗心/计算错误/方法不当/超纲/其他；"
    "type 判断：有 A/B/C/D 选项为 choice，答案为简短数值/单词/表达式为 fill，需完整过程为 essay。只输出 JSON。"
)


def split_questions(ocr_text: str) -> Optional[list]:
    result = _chat_json(SYSTEM_SPLIT, f"OCR 文本：\n{ocr_text[:6000]}", max_tokens=4000)
    if not result or "questions" not in result:
        return None
    questions = result["questions"]
    cleaned = []
    for q in questions:
        text = (q.get("question_text") or "").strip()
        if not text:
            continue
        cleaned.append({
            "question_text": text[:2000],
            "answer": (q.get("answer") or "")[:2000],
            "analysis": (q.get("analysis") or "")[:2000],
            "subject": q.get("subject", "其他"),
            "knowledge_point": str(q.get("knowledge_point", ""))[:64],
            "error_type": q.get("error_type", "其他"),
            "type": q.get("type") if q.get("type") in ("choice", "fill", "essay") else "fill",
            "difficulty": q.get("difficulty", "中") if q.get("difficulty") in ("易", "中", "难") else "中",
        })
    return cleaned


SYSTEM_VARIANT = (
    "你是出题老师。根据用户提供的错题，生成同知识点、同难度的变体题（数字/条件/设问方式变化）。"
    "输出 JSON：{\"questions\": [{\"id\": 原题的数字编号, \"question_text\": \"变体题题干\", \"options\": [\"A...\",\"B...\",\"C...\",\"D...\"] 或 [], \"answer\": \"答案\", \"analysis\": \"解析\", \"knowledge_point\": \"考察知识点（15字内，如：二次函数配方法求最值）\"}]}。"
    "要求：题干简短（不超过 60 字）；选择题选项每项不超过 20 字；答案直接给出（选项题给出字母）；解析不超过 2 句；"
    "knowledge_point 写具体考点。优先出选择题或填空题。只输出 JSON，不要输出任何其他文字。"
    "注意：原题若为带图形的立体几何/几何大题，变体题题干必须用文字完整描述几何体结构（如：正三棱柱 ABC-A1B1C1，底面边长为a，侧棱长为b…），不依赖图片也能独立解题；仅改变数字或条件，保持几何结构类型相同。"
)

SYSTEM_DUP = (
    "你是查重专员。判断【新题】是否与题库中任何一道题考察同一道题（内容重复），输出 JSON："
    '{"duplicate": true/false, "matched": 匹配题目编号或null, "reason": "一句话说明"}。'
    "判断规则："
    "1) 以下字段完全不参与判定，出现与否不影响重复结论：'用公式表达'、'已知'、'求'、'试求'、'计算'、'请'、'请问'、'的值'、标点、空格、LaTeX定界符、格式差异；"
    "2) 正例：'求函数 f(x)=x^2-4x+3 的最小值'与'求函数 f(x)=x^2-4x+3 的最小值，用公式表达'→重复；'已知函数 f(x)=x^2-4x+3，求最小值'与'求 f(x)=x^2-4x+3 的最小值'→重复；"
    "3) 反例：只改数字/变量名（x 改 t）不算重复；最小值改最大值不算重复；函数本身不同不算重复；"
    "4) 题目主体（函数表达式、已知条件、设问对象）完全一致才算重复。只输出 JSON。"
)

SYSTEM_VERIFY = (
    "你是严谨的题目审核员。检查下列题组中每一道题是否科学、正确、可解、自洽，重点排查："
    "1) 数学对象存在性：开口向上的二次函数没有最大值、开口向下的没有最小值、定义域不存在的极值等；"
    "2) 题干与设问一致（题干给函数却问毫不相关的东西）；"
    "3) 答案是否正确且与题干匹配；"
    "4) 条件是否充分可解（不缺少必要条件）；"
    "5) 选择题选项是否唯一正确答案；"
    "6) 题干是否自相矛盾或出现事实性错误。"
    "输出 JSON：{\"checks\": [{\"id\": 题号(从1开始), \"valid\": true/false, \"reason\": \"问题简述，无问题时为空字符串\"}]}。只输出 JSON。"
)


def _clean_id(value) -> int | None:
    """AI 输出的 id 可能为字符串/带前缀，尽力转 int"""
    import re
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        m = re.search(r"(\d+)", str(value))
        return int(m.group(1)) if m else None


def generate_variants(pool: list, count: int = 5) -> Optional[list]:
    """pool: [{id, question_text, answer, analysis}]"""
    if not available():
        return None
    if not pool:
        return []
    material = "\n\n".join(
        f"[题{idx + 1}] 题干：{q['question_text'][:300]}\n答案：{q.get('answer', '')[:150]}"
        for idx, q in enumerate(pool[:6])
    )
    result = _chat_json(SYSTEM_VARIANT, f"请生成 {count} 道变体题（可以少于 count，但至少 1 道）：\n{material}", temperature=0.7, max_tokens=2000)
    if not result or "questions" not in result:
        return None
    cleaned = []
    for q in result["questions"]:
        if not q.get("question_text"):
            continue
        cleaned.append({
            "id": _clean_id(q.get("id")),
            "question_text": q["question_text"],
            "options": q.get("options") or [],
            "answer": q.get("answer", ""),
            "analysis": q.get("analysis", ""),
            "knowledge_point": str(q.get("knowledge_point", ""))[:64],
        })
    return cleaned


def semantic_duplicate(new_text: str, candidates: list) -> Optional[dict]:
    """AI 语义查重：判断新题是否与任一候选题重复（忽略'用公式表达'等无效字段）。
    返回 {"duplicate": bool, "matched": int|None, "reason": str}；不可用时返回 None。"""
    if not candidates or not available():
        return None
    lines = "\n".join(f"{i + 1}. {t[:200]}" for i, t in enumerate(candidates))
    user = f"题库：\n{lines}\n\n新题：{new_text[:300]}\n请判断新题是否与题库重复。"
    result = _chat_json(SYSTEM_DUP, user, temperature=0.1, max_tokens=500)
    if not result:
        return None
    return {
        "duplicate": bool(result.get("duplicate")),
        "matched": result.get("matched"),
        "reason": result.get("reason", ""),
    }


def verify_questions(questions: list) -> Optional[list]:
    """批量审核题目（科学/自洽/可解），返回 [{"id": idx, "valid": bool, "reason": str}]。
    审核不可用时返回 None（调用方决定兜底策略，不静默放行）。"""
    if not questions:
        return []
    if not available():
        return None
    text = "\n\n".join(
        f"题{i + 1}：{q['question_text']}\n答案：{q.get('answer', '')}\n选项：{json.dumps(q.get('options') or [], ensure_ascii=False)}"
        for i, q in enumerate(questions))
    result = _chat_json(SYSTEM_VERIFY, text, temperature=0.1, max_tokens=2000)
    if not result or "checks" not in result:
        return None
    checks = {}
    for c in result.get("checks", []):
        try:
            checks[int(c.get("id")) - 1] = c
        except Exception:
            continue
    return [{"id": i, "valid": bool(checks.get(i, {}).get("valid", True)),
             "reason": checks.get(i, {}).get("reason", "")} for i in range(len(questions))]


SYSTEM_GRADE = (
    "你是批改老师。根据题目与用户答案，输出 JSON：{\"results\": [{\"id\": 题id, \"correct\": true/false, "
    "\"score\": 0-100, \"analysis\": \"本题解析，指出对错原因\", \"answer\": \"参考答案\", "
    "\"first_error_step\": \"首处错误步骤或空\", \"next_hint\": \"下一步提示\"}]}。"
    "简答题按要点酌情给分；若错误，必须指出首处错误及可执行下一步。只输出 JSON。"
)


def grade(questions: list, answers: dict) -> Optional[list]:
    """questions: [{id, question_text, answer, analysis}]; answers: {id: 用户答案}"""
    if not available():
        return None
    material = "\n\n".join(
        f"[题{q['id']}] 题干：{q['question_text'][:400]}\n参考答案：{q.get('answer', '')[:200]}\n用户答案：{answers.get(q['id'], '')}"
        for q in questions
    )
    result = _chat_json(SYSTEM_GRADE, f"请批改以下题目：\n{material}", temperature=0.2, max_tokens=3000)
    if not result or "results" not in result:
        return None
    return result["results"]


SYSTEM_EXTRACT = (
    "根据对话上下文提取一道错题（用户提问或 AI 讲解中涉及的题目），输出 JSON："
    '{"question_text": "题干", "answer": "答案", "analysis": "解析", "subject": "学科", '
    '"knowledge_point": "知识点", "error_type": "错因"}。若无法提取则 question_text 输出空字符串。只输出 JSON。'
)


def extract_question(history_text: str) -> Optional[dict]:
    result = _chat_json(SYSTEM_EXTRACT, f"对话内容：\n{history_text[:6000]}")
    if not result or not (result.get("question_text") or "").strip():
        return None
    return {
        "question_text": result["question_text"][:2000],
        "answer": (result.get("answer") or "")[:2000],
        "analysis": (result.get("analysis") or "")[:2000],
        "subject": result.get("subject", "其他"),
        "knowledge_point": str(result.get("knowledge_point", ""))[:64],
        "error_type": result.get("error_type", "其他"),
        "difficulty": "中",
    }


SYSTEM_ANSWER = (
    "你是解题老师。根据题目和学科生成答案和解析，严格输出 JSON（不要输出任何其他文字）："
    '{"answer": "答案", "analysis": "解题思路与解析"}。'
    "必须严格按照给定学科的知识体系作答：英语题按英语词汇/语法理解（star=星星/恒星等常见释义）；"
    "数学题按数学推理；语文/物理/化学/生物/政治/历史/地理/专业课按各自学科标准——严禁跨学科解释（如英语单词不要用数学概念解释）。"
    "answer 直接给出最终答案（数值/区间/表达式），数学表达式用 LaTeX 行内公式，如 $x \\in (-\\infty, -1) \\cup (1, +\\infty)$；"
    "analysis 是解题思路与解析，要求：清晰、明了、易懂——分步骤（每步一行，编号），"
    "公式用 LaTeX：行内 $...$，独立公式 $$...$$；关键方法先点明，再推导，最后结论；"
    "步骤之间逻辑连贯，适合学生自学理解。只输出 JSON。"
)


def generate_answer(question_text: str, subject: str = "") -> Optional[dict]:
    """根据题干生成答案+解析（LaTeX 公式，清晰易懂；按学科语境，避免跨学科误解）"""
    subj_hint = f"\n学科：{subject}" if subject else ""
    result = _chat_json(SYSTEM_ANSWER, f"题目：{question_text[:2000]}{subj_hint}", temperature=0.3, max_tokens=3000)
    if not result:
        return None
    return {
        "answer": (result.get("answer") or "")[:2000],
        "analysis": (result.get("analysis") or "")[:4000],
    }


SYSTEM_CHAT = (
    "你是学习答疑助手，用中文回答。格式要求严格：\n"
    "1. 适当分点：步骤/性质/要点用 \"- \" 或 \"1. \" 列表逐条列出，段落之间空行分隔，不要挤成一大段文字；\n"
    "2. 所有数学公式必须用 $...$（行内）或 $$...$$（独立行）包裹，严禁裸写 LaTeX 命令（如 \\frac、\\int、\\sum 必须写在 $ 内）；\n"
    "3. 解答要清晰明了易懂：先点明思路/方法，再分步推导，步骤完整、逻辑连贯，最后给出结论与易错点。\n"
)

_FF = chr(0xFF5C)  # 全角竖线 ｜（模型常把 | 输出成全角，re 不支持 \u 转义，用 chr 拼接）
_PIPE = r'[\s|' + _FF + r']+'  # 竖线/空白的任意组合（模型常输出 < | | DSML | | > 带空格变体）
_DSML_CLOSE = r'<\s*/?\s*' + _PIPE + r'\s*DSML\s*' + _PIPE + r'\s*/?\s*'
_DSML_TC_RE = re.compile(r'<\s*' + _PIPE + r'\s*DSML\s*' + _PIPE + r'\s*tool_calls\s*' + _PIPE + r'\s*>(.*?)' + _DSML_CLOSE + r'tool_calls\s*' + _PIPE + r'\s*>', re.S)
_DSML_INV_RE = re.compile(r'invoke\s+name="([^"]+)"[^>]*>(.*?)<[^>]*invoke[^>]*>', re.S)
_DSML_P_RE = re.compile(r'parameter\s+name="([^"]+)"[^>]*>(.*?)<[^>]*parameter[^>]*>', re.S)


def _parse_dsml_calls(text: str) -> list:
    """从文本中解析 DSML 工具调用块，返回 [{id, name, args}]，并从文本移除"""
    calls = []
    m = _DSML_TC_RE.search(text)
    if not m:
        return calls
    block = m.group(0)
    for inv in _DSML_INV_RE.finditer(m.group(1)):
        name = inv.group(1)
        args = {}
        for pm in _DSML_P_RE.finditer(inv.group(2)):
            args[pm.group(1)] = pm.group(2).strip()
        calls.append({"id": f"dsml_{len(calls)}", "name": name,
                      "args": json.dumps(args, ensure_ascii=False)})
    return calls


def _dsml_block(text: str) -> str | None:
    m = _DSML_TC_RE.search(text)
    return m.group(0) if m else None


# XML 风格工具调用：<tool_calls><invoke name="x"><parameter name="y">v</parameter></invoke></tool_calls>
# 注意：模型偶尔把闭合标签 </tool_calls> 输出成全角竖线变体 ｜｜tool_calls>（U+FF5C）
_XML_TC_RE = re.compile(r'<tool_calls>(.*?)(?:</tool_calls>|｜｜tool_calls>)', re.S)
_XML_INV_RE = re.compile(r'<invoke\s+name="([^"]+)"\s*>(.*?)</invoke>', re.S)
_XML_P_RE = re.compile(r'<parameter\s+name="([^"]+)"[^>]*>(.*?)</parameter>', re.S)


def _parse_xml_calls(text: str) -> tuple[list, str]:
    """解析 XML 风格工具调用块，返回 (calls, 移除块后的文本)"""
    m = _XML_TC_RE.search(text)
    if not m:
        return [], text
    block = m.group(0)
    calls = []
    for inv in _XML_INV_RE.finditer(m.group(1)):
        name = inv.group(1)
        args = {}
        for pm in _XML_P_RE.finditer(inv.group(2)):
            args[pm.group(1)] = pm.group(2).strip()
        calls.append({"id": f"xml_{len(calls)}", "name": name,
                      "args": json.dumps(args, ensure_ascii=False)})
    return calls, text.replace(block, "", 1)


async def chat_complete(messages: list, max_tokens: int = 4000, thinking: str = "off",
                        tools: list | None = None, model_key: str = "main",
                        temperature: float = 0.3) -> tuple[str, list, str]:
    """非流式对话补全（带工具）。返回 (content, tool_calls, reasoning_content)。
    一次性拿到完整结果：标准 tool_calls 或 DSML/XML 文本工具调用均解析，无流式边界问题。"""
    if not available():
        raise AppError(50200, "AI 服务未配置（缺少 DEEPSEEK_API_KEY），请先配置 .env", 503)
    model = _resolve_model(model_key)
    kwargs = {}
    if thinking == "off":
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        max_tokens = max(max_tokens, 4000)
    elif thinking == "standard":
        kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
        max_tokens = max(max_tokens, 16000)
    else:
        kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
        max_tokens = max(max_tokens, 32000)
    resp = await _get_async_client(model_key).chat.completions.create(
        model=model, messages=messages, max_tokens=max_tokens,
        temperature=temperature, stream=False,
        tools=tools, tool_choice="auto" if tools else None, **kwargs)
    msg = resp.choices[0].message
    content = msg.content or ""
    reasoning = getattr(msg, "reasoning_content", None) or ""
    tcs = []
    # 1) 标准结构化 tool_calls
    if getattr(msg, "tool_calls", None):
        for tc in msg.tool_calls:
            tcs.append({"id": tc.id or f"call_{len(tcs)}",
                        "name": tc.function.name or "",
                        "args": tc.function.arguments or "{}"})
    # 2) DSML 文本格式（<|DSML|tool_calls|>，兼容全角竖线 ｜｜DSML｜｜ 变体）
    if not tcs and "DSML" in content and "tool_calls" in content:
        block = _dsml_block(content)
        if block:
            tcs = _parse_dsml_calls(block)
            content = content.replace(block, "", 1)
    # 3) XML 风格（<tool_calls><invoke ...>）
    if not tcs and "<tool_calls>" in content:
        xml_calls, content = _parse_xml_calls(content)
        if xml_calls:
            tcs = xml_calls
    if content:
        content = repair_latex(content)
    return content, tcs, reasoning


async def chat_stream(messages: list, max_tokens: int = 1500, use_vision: bool = False,
                      thinking: str = "off", tools: list | None = None,
                      model_key: str = "main", temperature: float = 0.3) -> AsyncGenerator[str, None]:
    """SSE 流式聊天。messages: [{"role": "...", "content": "..."}]，带图消息 content 为数组。
    use_vision=True 时改用智谱 GLM-4V-Flash（免费视觉模型）看图回答。
    thinking: "off" 关闭思考（快速）；"standard" 标准思考；"deep" 深度思考（更充分）。
    tools: 可选工具定义列表（function calling）。
    使用异步客户端保证在 uvicorn 事件循环中真正逐 token 流式输出。"""
    if not available():
        raise AppError(50200, "AI 服务未配置（缺少 DEEPSEEK_API_KEY），请先配置 .env", 503)
    # 视觉场景：使用智谱 GLM-4V-Flash（前提是当前 provider 是智谱或兼容接口）
    model = "glm-4v-flash" if use_vision else _resolve_model(model_key)
    kwargs = {}
    if not use_vision:
        if thinking == "off":
            # 关闭思考（保持快速稳定）；预算给足，长推导/长解答不被截断
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
            max_tokens = max(max_tokens, 4000)
        elif thinking == "standard":
            # 标准思考：模型思考链可能很长，给足输出预算防止回答截断
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
            max_tokens = max(max_tokens, 32000)
        else:  # "deep" 深度思考：给足思考与回答空间
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
            max_tokens = max(max_tokens, 32000)
    try:
        if use_vision:
            # 视觉：智谱 GLM-4V-Flash（DeepSeek 无视觉能力）
            stream = await _get_async_vision_client().chat.completions.create(
                model="glm-4v-flash",
                messages=messages,
                max_tokens=1024,
                stream=True,
            )
        else:
            # 文本：主模型（DeepSeek-V4-Flash）或备用模型（对话页可切换）
            stream = await _get_async_client(model_key).chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
                tools=tools,
                tool_choice="auto" if tools else None,
                **kwargs,
            )
        sent_thinking_on = False
        sent_thinking_off = False
        tool_calls: dict = {}
        content_buf = ""
        # DSML 文本格式工具调用（思考模式下 deepseek-v4-flash 用此格式表达工具调用）
        _DSML_CLOSE = r'<\s*/?\s*\|\s*DSML\s*\|\s*/?\s*'
        _DSML_TC = re.compile(r'<\s*\|\s*DSML\s*\|\s*tool_calls\s*\|\s*>(.*?)' + _DSML_CLOSE + r'tool_calls\s*\|?\s*>', re.S)
        _DSML_INV = re.compile(r'<\s*\|\s*DSML\s*\|\s*invoke\s+name="([^"]+)"\s*>(.*?)' + _DSML_CLOSE + r'invoke\s*\|?\s*>', re.S)
        _DSML_P = re.compile(r'<\s*\|\s*DSML\s*\|\s*parameter\s+name="([^"]+)"[^>]*>(.*?)' + _DSML_CLOSE + r'parameter\s*\|?\s*>', re.S)
        async for chunk in stream:
            try:
                delta = chunk.choices[0].delta
                finish = chunk.choices[0].finish_reason
            except Exception:
                delta = None
                finish = None
            # 流式工具调用：按 index 累积（id/name/arguments 分片）
            if delta and getattr(delta, "tool_calls", None):
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls:
                        tool_calls[idx] = {"id": "", "name": "", "args": ""}
                    if tc.id:
                        tool_calls[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tool_calls[idx]["name"] += tc.function.name
                        if tc.function.arguments:
                            tool_calls[idx]["args"] += tc.function.arguments
            # 思考过程：仅上报状态（内容不输出，避免渲染负担与泄露）
            reasoning = getattr(delta, "reasoning_content", None) if delta else None
            content = getattr(delta, "content", None) if delta else None
            if reasoning and not sent_thinking_on:
                sent_thinking_on = True
                yield "event: thinking\ndata: 1\n\n"
            if content and sent_thinking_on and not sent_thinking_off:
                sent_thinking_off = True
                yield "event: thinking\ndata: 0\n\n"
            if content:
                content_buf += content
                # 检测完整 DSML 工具调用块
                m = _DSML_TC.search(content_buf)
                if m:
                    block = m.group(0)
                    calls = []
                    for inv in _DSML_INV.finditer(block):
                        name = inv.group(1)
                        args = {}
                        for pm in _DSML_P.finditer(inv.group(2)):
                            args[pm.group(1)] = pm.group(2).strip()
                        calls.append({"id": f"dsml_{len(calls)}", "name": name,
                                      "args": json.dumps(args, ensure_ascii=False)})
                    # 移除 DSML 块，保留块前正常文本
                    content_buf = content_buf.replace(block, "", 1)
                    if content_buf:
                        yield repair_latex(content_buf)
                        content_buf = ""
                    if calls:
                        yield f"event: tool_call\ndata: {json.dumps(calls, ensure_ascii=False)}\n\n"
                        return  # 等待上层执行工具后二轮
                # 无未闭合 DSML 标记：正常输出累积内容
                if "<|DSML|" not in content_buf and content_buf:
                    yield repair_latex(content_buf)
                    content_buf = ""
            if finish == "tool_calls":
                # 汇总所有工具调用，上报给上层执行
                import json as _json
                calls = [{"id": tool_calls[i]["id"], "name": tool_calls[i]["name"],
                          "args": tool_calls[i]["args"]} for i in sorted(tool_calls)]
                yield f"event: tool_call\ndata: {_json.dumps(calls, ensure_ascii=False)}\n\n"
                return
    except Exception as e:
        logger.error("LLM 流式失败(%s): %s", model, e)
        raise AppError(50200, f"AI 服务暂时不可用: {e}", 503)
