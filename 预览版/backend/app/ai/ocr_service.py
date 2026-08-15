# -*- coding: utf-8 -*-
"""OCR 服务：优先 PaddleOCR（已安装时），否则用智谱 GLM-4V-Flash 免费视觉模型识别。

- PaddleOCR：本地识别，速度快（可选依赖，未安装自动跳过）
- GLM-4V-Flash：云端视觉模型，免费，识别错题截图效果好（含公式 LaTeX 输出）
- 两者都不可用 → 抛 50300，前端引导改用文本录入
"""
import base64
import logging
import re
import difflib
from io import BytesIO

from app.core.config import LLM_API_KEY, LLM_BASE_URL, QWV_API_KEY, QWV_BASE_URL, QWV_MODEL,\
    MATHPIX_APP_ID, MATHPIX_APP_KEY
from app.core.exceptions import AppError

logger = logging.getLogger(__name__)

_ocr = None
_LOAD_FAILED = False


def _get_ocr():
    """懒加载 PaddleOCR（可选）"""
    global _ocr, _LOAD_FAILED
    if _ocr is not None:
        return _ocr
    if _LOAD_FAILED:
        return None
    try:
        from paddleocr import PaddleOCR  # 可选依赖
        _ocr = PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False, lang="ch")
        logger.info("PaddleOCR 初始化完成")
        return _ocr
    except Exception as e:
        _LOAD_FAILED = True
        logger.info("PaddleOCR 不可用（将使用 GLM-4V-Flash 云端识别）: %s", e)
        return None


def _recognize_by_paddle(image_bytes: bytes) -> str:
    import numpy as np
    from PIL import Image
    img = Image.open(BytesIO(image_bytes)).convert("RGB")
    arr = np.array(img)
    ocr = _get_ocr()
    if ocr is None:
        return ""
    result = ocr.predict(arr)
    lines = []
    for page in result:
        if hasattr(page, "rec_texts"):
            lines.extend(page.rec_texts or [])
        elif isinstance(page, dict):
            lines.extend(page.get("rec_texts") or [])
    return "\n".join(lines).strip()


def _recognize_by_mathpix(image_bytes: bytes) -> str:
    """Mathpix API 数学公式 OCR（专业数学识别，支持手写/印刷公式 → LaTeX）"""
    if not MATHPIX_APP_ID or not MATHPIX_APP_KEY:
        return ""
    import base64
    try:
        import httpx
    except ImportError:
        import urllib.request

        def _post(url, data, headers):
            req = urllib.request.Request(url, data=json.dumps(data).encode(),
                                         headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())
        _post_ = _post
    else:
        def _post(url, data, headers):
            resp = httpx.post(url, json=data, headers=headers, timeout=60)
            resp.raise_for_status()
            return resp.json()
        _post_ = _post
    b64 = base64.b64encode(image_bytes).decode()
    payload = {
        "src": f"data:image/jpeg;base64,{b64}",
        "formats": ["text", "math_inline", "math_display"],
        "math_inline_delimiters": ["$", "$"],
        "math_display_delimiters": ["$$", "$$"],
        "rm_spaces": True,
    }
    j = _post_("https://api.mathpix.com/v3/latex", payload,
               {"app_id": MATHPIX_APP_ID, "app_key": MATHPIX_APP_KEY,
                "Content-Type": "application/json"})
    text = (j.get("text") or "").strip()
    md = j.get("math_display") or []
    if md:
        text = (text + "\n" + "\n".join(md)).strip()
    return text


def _latex_to_plain(t: str) -> str:
    """Mathpix LaTeX 结果 → 纯文本（用于交叉比对）"""
    t = re.sub(r'\\frac\{([^}]*)\}\{([^}]*)\}', r'\1/\2', t)
    t = re.sub(r'\\sqrt\{([^}]*)\}', r'sqrt(\1)', t)
    t = re.sub(r'\\left|\\right', '', t)
    t = re.sub(r'\\[a-zA-Z]+\*?', '', t)
    t = t.replace('{', '').replace('}', '')
    return t


def _recognize_by_qwen(image_bytes: bytes) -> str:
    """阿里云百炼 Qwen-VL 识别（免费额度大，数学 OCR 强）"""
    if not QWV_API_KEY:
        return ""
    from openai import OpenAI
    try:
        from PIL import Image
        img = Image.open(BytesIO(image_bytes)).convert("RGB")
        buf = BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
    except Exception:
        b64 = base64.b64encode(image_bytes).decode()
    data_url = f"data:image/png;base64,{b64}"
    client = OpenAI(api_key=QWV_API_KEY, base_url=QWV_BASE_URL or "https://dashscope.aliyuncs.com/compatible-mode/v1", timeout=25, max_retries=0)
    resp = client.chat.completions.create(
        model=QWV_MODEL or "qwen-vl-max",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": (
                    "你是高精度 OCR 工具。请逐字符完整转写图片中的数学题目，只输出题目文字，不要解释。"
                    "严格注意：1) 【负号】坐标与系数中的负号（-）极易漏读！如 A(-1/2, -1/2) 的每个负号都必须保留；"
                    "2) 上下标数字（x^2 vs x^3、下标 n+1）逐个确认；"
                    "3) 公式用 LaTeX：分数 \frac{}{}，积分 \int，根号 \sqrt{}，乘方 ^；"
                    "4) 保留选项 A/B/C/D；5) 中英文与标点保持原样；6) 若某字符不确定，宁可保留原文也不要猜测。"
                )},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }],
        temperature=0.0,
        max_tokens=2048,
    )
    text = (resp.choices[0].message.content or "").strip()
    from app.ai.deepseek_client import repair_latex
    text = repair_latex(text)
    if not text:
        raise AppError(50300, "识别失败：AI 未能识别到文字，请重拍或改用文本录入", 422)
    return text


def _recognize_by_luna(image_bytes: bytes) -> str:
    """gpt-5.6-luna 视觉识别（关闭思考模式，精度高于 GLM-4V）"""
    from app.core.config import LLM_ALT_KEY, LLM_ALT_BASE
    if not LLM_ALT_KEY:
        return ""
    from openai import OpenAI
    try:
        from PIL import Image
        img = Image.open(BytesIO(image_bytes)).convert("RGB")
        buf = BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
    except Exception:
        b64 = base64.b64encode(image_bytes).decode()
    data_url = f"data:image/png;base64,{b64}"
    client = OpenAI(api_key=LLM_ALT_KEY, base_url=LLM_ALT_BASE or "https://rehdasu.cn/v1", timeout=25, max_retries=0)
    resp = client.chat.completions.create(
        model="gpt-5.6-luna",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": (
                    "你是高精度 OCR 工具。请逐字符完整转写图片中的数学题目，只输出题目文字，不要解释。"
                    "严格注意：1) 【负号】坐标与系数中的负号（-）极易漏读！如 A(-1/2, -1/2) 的每个负号都必须保留；"
                    "2) 上下标数字（x^2 vs x^3、下标 n+1）逐个确认；"
                    "3) 公式用 LaTeX：分数 \\frac{}{}，积分 \\int，根号 \\sqrt{}，乘方 ^；"
                    "4) 保留选项 A/B/C/D；5) 中英文与标点保持原样；6) 若某字符不确定，宁可保留原文也不要猜测。"
                )},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }],
        temperature=0.0,
        max_tokens=2048,
        extra_body={"thinking": {"type": "disabled"}},  # 关闭思考模式
    )
    text = (resp.choices[0].message.content or "").strip()
    from app.ai.deepseek_client import repair_latex
    text = repair_latex(text)
    if not text:
        raise AppError(50300, "识别失败：AI 未能识别到文字，请重拍或改用文本录入", 422)
    return text


def _recognize_by_glm(image_bytes: bytes) -> str:
    """智谱 GLM-4V-Flash 视觉识别（免费，OpenAI 兼容接口）"""
    from app.core.config import ZHIPU_API_KEY, ZHIPU_BASE_URL
    if not ZHIPU_API_KEY:
        return ""
    from openai import OpenAI
    base_url = ZHIPU_BASE_URL or "https://open.bigmodel.cn/api/paas/v4/"
    # 识别图片 base64 → data URL
    try:
        from PIL import Image
        img = Image.open(BytesIO(image_bytes)).convert("RGB")
        buf = BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
    except Exception:
        b64 = base64.b64encode(image_bytes).decode()
    data_url = f"data:image/png;base64,{b64}"
    client = OpenAI(api_key=ZHIPU_API_KEY, base_url=base_url, timeout=25, max_retries=0)
    resp = client.chat.completions.create(
        model="glm-4v-flash",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": (
                    "你是 OCR 识别工具。请识别图片中的全部文字，只输出识别结果，不要任何解释。"
                    "要求：1) 保持原有换行与顺序；2) 数学公式用 LaTeX 语法输出（如 x^2、a_{n+1}、\\frac{1}{2}、\\int、\\sqrt{}）；"
                    "3) 选择题保留选项 A/B/C/D 内容；4) 中英文符号保持原样。"
                )},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }],
        temperature=0.1,
        max_tokens=1024,
    )
    text = (resp.choices[0].message.content or "").strip()
    from app.ai.deepseek_client import repair_latex
    text = repair_latex(text)
    if not text:
        raise AppError(50300, "识别失败：AI 未能识别到文字，请重拍或改用文本录入", 422)
    return text


def recognize(image_bytes: bytes) -> str:
    """识别图片，返回纯文本。失败抛 50300。"""
    # 1) 优先本地 PaddleOCR（如果可用）
    try:
        text = _recognize_by_paddle(image_bytes)
        if text:
            return text
    except Exception as e:
        logger.warning("PaddleOCR 识别失败，转云端: %s", e)
    # 2) 优先 Qwen-VL（阿里百炼，数学 OCR 强）
    try:
        text = _recognize_by_qwen(image_bytes)
        if text:
            return text
    except Exception as e:
        logger.warning("Qwen 识别失败: %s", str(e)[:120])
    # 3) 其次 gpt-5.6-luna（关闭思考）
    try:
        text = _recognize_by_luna(image_bytes)
        if text:
            return text
    except Exception as e:
        logger.warning("Luna 识别失败，降级 GLM-4V: %s", str(e)[:120])
    # 3) 智谱 GLM-4V-Flash 兜底
    try:
        return _recognize_by_glm(image_bytes)
    except AppError:
        raise
    except Exception as e:
        logger.error("GLM-4V 识别失败: %s", e)
        raise AppError(50300, f"识别失败: {e}，请重试或改用文本录入", 422)


def _normalize_ocr(text: str) -> str:
    """归一化用于交叉比对：去空白/换行，转小写，去常见标点差异"""
    t = text or ""
    t = re.sub(r'\s+', '', t)
    t = t.lower()
    t = re.sub(r'[，。；：、,.;:()（）\[\]{}]', '', t)
    t = re.sub("[‘’“”\"']", '', t)
    return t


def _sim(a: str, b: str) -> float:
    na, nb = _normalize_ocr(a), _normalize_ocr(b)
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


def _critical_diff(a: str, b: str) -> bool:
    """检测差异块中是否含方向/符号关键词（顺逆、正负、加减号）——数学题致命差异"""
    na, nb = _normalize_ocr(a), _normalize_ocr(b)
    sm = difflib.SequenceMatcher(None, na, nb)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ('replace', 'delete', 'insert'):
            da, db = na[i1:i2], nb[j1:j2]
            for ch in da + db:
                if ch in '+-−±顺逆正负':
                    return True
    return False


def recognize_cross(image_bytes: bytes) -> tuple[str, str, list[str]]:
    """双模型交叉验证识别（Qwen-VL + gpt-5.6-luna；两者都失败时 GLM 兜底）。

    返回 (final_text, confidence, sources)：
      confidence: 'high'  两模型一致（sim>=0.95 且无符号/方向差异）
                  'medium' 单模型可用或基本一致
                  'low'   差异大，最终文本不可靠
    """
    results = []  # (text, source)

    def _run_qwen():
        try:
            t = _recognize_by_qwen(image_bytes)
            return (t.strip(), "qwen") if t else None
        except Exception as e:
            logger.warning("交叉验证 Qwen 失败: %s", str(e)[:100])
            return None

    def _run_luna():
        try:
            t = _recognize_by_luna(image_bytes)
            return (t.strip(), "luna") if t else None
        except Exception as e:
            logger.warning("交叉验证 Luna 失败: %s", str(e)[:100])
            return None

    def _run_glm():
        try:
            t = _recognize_by_glm(image_bytes)
            return (t.strip(), "glm") if t else None
        except Exception as e:
            logger.warning("交叉验证 GLM 失败: %s", str(e)[:100])
            return None

    # 三个模型并发识别，取【最快返回的两个】做交叉比对（自动选择当前最快的搭配，自适应网络状况）
    from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
    executor = ThreadPoolExecutor(max_workers=3)
    try:
        pending = {
            executor.submit(_run_qwen): "qwen",
            executor.submit(_run_luna): "luna",
            executor.submit(_run_glm): "glm",
        }
        pending_set = set(pending)
        while pending_set and len(results) < 2:
            # 等待 60s：qwen/glm 实测约 48s 返回；luna 慢（>60s）自然被淘汰
            done, pending_set = wait(pending_set, return_when=FIRST_COMPLETED, timeout=60)
            if not done:
                break  # 超时：不再等，用已有的结果
            for fut in done:
                r = fut.result()
                if r:
                    results.append(r)
    finally:
        executor.shutdown(wait=False)  # 未完成的识别线程后台跑完即弃，不阻塞返回

    if not results:
        raise AppError(50300, "识别失败: 所有 OCR 模型均不可用，请重试或改用文本录入", 422)

    sources = [src for _, src in results]
    if len(results) == 1:
        # 只有一个模型可用：无法交叉，中等置信
        return results[0][0], "medium", sources

    # 两两比对，找最一致的对
    best_pair, best_sim = None, 0.0
    for i in range(len(results)):
        for j in range(i + 1, len(results)):
            sim = _sim(results[i][0], results[j][0])
            if sim > best_sim:
                best_pair, best_sim = (results[i], results[j]), sim
    final = results[0][0]  # 默认 qwen（数学强）
    if best_sim >= 0.95 and not _critical_diff(best_pair[0][0], best_pair[1][0]):
        # 两个模型高度一致且无符号/方向差异 → 高置信
        a, b = best_pair
        final = a[0] if a[1] == "qwen" else b[0] if b[1] == "qwen" else a[0]
        return final, "high", sources
    if best_sim >= 0.8 and not _critical_diff(best_pair[0][0], best_pair[1][0]):
        return results[0][0], "medium", sources
    # 差异大：三模型投票（两两 sim>=0.6 视为同一文本）
    votes = [0] * len(results)
    for i in range(len(results)):
        for j in range(len(results)):
            if i != j and _sim(results[i][0], results[j][0]) >= 0.6:
                votes[i] += 1
    winner = max(range(len(results)), key=lambda i: votes[i])
    final = results[winner][0]
    conf = "medium" if votes[winner] >= 2 else "low"
    return final, conf, sources
