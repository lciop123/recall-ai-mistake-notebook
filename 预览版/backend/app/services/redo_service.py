# -*- coding: utf-8 -*-
"""错题重做服务：AI 判断题型（选择/填空/大题）+ 批改（大题支持拍照图片）"""
import base64
from io import BytesIO

from sqlmodel import Session, select

from app.ai import deepseek_client
from app.core.config import IMAGE_DIR
from app.core.exceptions import AppError
from app.models.models import get_engine, Question
from app.services.plan_service import record_review_outcome

SYSTEM_TYPE = (
    "你是出题老师。根据用户提供的错题（题干+答案+解析），自主判断适合的作答题型，输出 JSON："
    '{"type": "choice|fill|essay", "options": [...]}。'
    "规则：1) 如果原题本身就是选择题且有选项信息，type=choice，options 保留原选项（A./B./C./D. 完整格式）；"
    "2) 如果原题是填空题（答案简短，如数字、单词、表达式），type=fill，options=[]；"
    "3) 如果原题是解答题/大题（需要完整解题过程，如证明、应用题、计算题），type=essay，options=[]；"
    "4) 不要强行改编题型，保持原题风格。只输出 JSON。"
)

SYSTEM_GRADE = (
    "你是批改老师。根据【学科】、【题型】、题目、标准答案和学生的作答，按该学科的标准严格批改，输出 JSON："
    '{"correct": true/false, "score": 0-100整数, "feedback": "批改意见", "first_error_step": "首处错误步骤或空", "next_hint": "下一步提示"}。'
    "学科判定规则：\n"
    "- 英语：按英语词汇/语法/阅读理解标准判定——词汇题以常见词典释义为准，同义词、合理翻译均算对（如 star=星星/恒星/星均正确）；不要用数学或其他学科语境解释英语单词；\n"
    "- 数学：按数学严谨性判定（详见题型规则）；\n"
    "- 语文/政治/历史/地理/生物/物理/化学/专业课：按各自学科的知识体系判定，用词、定义、原理要符合该学科；\n"
    "题型与严格度：\n"
    "1) choice 选择题：答案选项与标准一致即对；\n"
    "2) fill 填空题：答案与标准一致即对（等价写法、同义词、合理翻译可算对）；\n"
    "3) essay 大题/证明题：必须包含【完整的解题思路、推导过程和最终结果】才可能判对——"
    "只有最终答案、没有过程 → 判错并提示补过程；过程有逻辑错误/思路不正确 → 判错并在反馈中明确指出哪一步错、为什么错；"
    "证明题尤其注重每一步推理的严谨性；过程大部分正确但结论或细节有小错可给部分分（score 按比例），否则 0 分。\n"
    "数学表达近似等价算对；反馈要具体（指出对/错在哪一步），不超过 2 句。只输出 JSON。"
)

SYSTEM_GRADE_IMAGE = (
    "你是批改老师。下面是题目、标准答案，以及学生手写作答的图片。"
    "请认真看图片中的作答内容，按【题型】严格批改，输出 JSON："
    '{"correct": true/false, "score": 0-100整数, "feedback": "批改意见", "first_error_step": "首处错误步骤或空", "next_hint": "下一步提示"}。'
    "题型规则：essay 大题/证明题必须包含【完整解题思路、推导过程和结果】才可能判对——"
    "只有最终答案没过程 → 判错并提示补过程；过程有逻辑错误 → 判错并明确指出哪一步错；证明题注重每一步严谨性；"
    "过程大部分正确但有小错可给部分分。看不清/无法辨认按答错处理并说明。只输出 JSON。"
)


def _get_question(question_id: int) -> Question:
    with Session(get_engine()) as s:
        q = s.get(Question, question_id)
        if not q:
            raise AppError(40400, "错题不存在", 404)
        return q


def judge_type(question_id: int) -> dict:
    """AI 判断题型；选择题附带选项"""
    q = _get_question(question_id)
    text = f"题干：{q.question_text}\n答案：{q.answer or '（无）'}\n解析：{(q.analysis or '')[:300]}"
    result = deepseek_client._chat_json(SYSTEM_TYPE, text, temperature=0.1)
    if not result:
        # 降级：有答案且简短 → fill，否则 essay
        t = "fill" if q.answer and len(q.answer) <= 30 else "essay"
        return {"type": t, "options": []}
    t = result.get("type")
    if t not in ("choice", "fill", "essay"):
        t = "fill"
    opts = result.get("options") or []
    return {"type": t, "options": opts}


def _safe_score(value: object) -> int:
    try:
        return max(0, min(100, int(float(value or 0))))
    except (TypeError, ValueError):
        return 0


def _outcome(result: dict, *, fallback_hint: str = "") -> dict:
    """稳定输出批改结果，避免 AI 缺字段时前端展示崩溃。"""
    correct = bool(result.get("correct"))
    score = _safe_score(result.get("score"))
    feedback = str(result.get("feedback") or ("作答正确，继续保持。" if correct else "请对照参考答案检查解题过程。"))
    return {
        "correct": correct, "score": score, "feedback": feedback,
        "first_error_step": str(result.get("first_error_step") or ("" if correct else feedback)),
        "next_hint": str(result.get("next_hint") or ("尝试独立复述解法。" if correct else fallback_hint or "从题干条件和第一步推导重新检查。")),
    }


def grade(question_id: int, answer: str = "", image_path: str | None = None, qtype: str = "fill", subject: str = "", review_type: str = "redo") -> dict:
    """批改并写入一条复习记录；文本和手写图片返回相同的步骤反馈契约。"""
    q = _get_question(question_id)
    if image_path:
        result = _outcome(_grade_image(q, image_path, qtype, subject))
        result["review"] = record_review_outcome(q.id, 5 if result["correct"] else 1, score=result["score"], review_type=review_type)
        return result
    if not answer.strip():
        raise AppError(40001, "请先作答再提交", 400)
    text = (
        f"学科：{subject or q.subject or '通用'}\n"
        f"题型：{qtype}\n"
        f"题目：{q.question_text}\n"
        f"标准答案：{q.answer or '（无）'}\n"
        f"解析：{(q.analysis or '')[:300]}\n"
        f"学生作答：{answer[:2000]}"
    )
    result = deepseek_client._chat_json(SYSTEM_GRADE, text, temperature=0.1)
    if not result:
        # 降级：简单字符串包含判断（大题无过程判错）
        ref = (q.answer or "").strip()
        correct = bool(ref) and answer.strip() in ref
        if qtype == "essay" and len(answer.strip()) < 20:
            correct = False
        result = {"correct": correct, "score": 100 if correct else 0,
                  "feedback": "（AI 降级判断）大题需提供完整解题过程" if qtype == "essay" and not correct else "（AI 降级判断）"}
    result = _outcome(result)
    result["review"] = record_review_outcome(q.id, 5 if result["correct"] else 1, score=result["score"], review_type=review_type)
    return result


def _grade_image(q: Question, image_path: str, qtype: str = "essay", subject: str = "") -> dict:
    """智谱 GLM-4V 看图批改（大题手写作答照片）"""
    from openai import OpenAI
    from app.core.config import ZHIPU_API_KEY, ZHIPU_BASE_URL
    if not ZHIPU_API_KEY:
        raise AppError(50300, "视觉 AI 服务未配置，无法看图批改", 503)
    try:
        img = (IMAGE_DIR / image_path).read_bytes()
    except Exception:
        raise AppError(40001, "图片不存在或已过期", 400)
    b64 = base64.b64encode(img).decode()
    data_url = f"data:image/png;base64,{b64}"
    client = OpenAI(api_key=ZHIPU_API_KEY, base_url=ZHIPU_BASE_URL or "https://open.bigmodel.cn/api/paas/v4/")
    user = (
        f"学科：{subject or q.subject or '通用'}\n"
        f"题型：{qtype}\n"
        f"题目：{q.question_text}\n"
        f"标准答案：{q.answer or '（无）'}\n"
        f"解析：{(q.analysis or '')[:300]}\n"
        "学生作答见图片，请按学科标准批改。"
    )
    try:
        resp = client.chat.completions.create(
            model="glm-4v-flash",
            messages=[{"role": "user", "content": [
                {"type": "text", "text": user},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]}],
            temperature=0.1,
            max_tokens=1024,
        )
        content = deepseek_client.repair_latex((resp.choices[0].message.content or "").strip())
        import json as _json
        result = _json.loads(content)
        return {
            "correct": bool(result.get("correct")),
            "score": _safe_score(result.get("score")),
            "feedback": result.get("feedback", ""),
            "first_error_step": result.get("first_error_step", ""),
            "next_hint": result.get("next_hint", ""),
        }
    except Exception as error:
        raise AppError(50300, f"视觉 AI 批改暂不可用：{str(error)[:120]}", 503)
