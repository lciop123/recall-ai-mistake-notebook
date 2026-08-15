# -*- coding: utf-8 -*-
"""全局配置：从 .env 读取，无 .env 时使用默认值（本地演示可跑）"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # backend/
load_dotenv(BASE_DIR / ".env")

DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "recall.db"
CHROMA_DIR = DATA_DIR / "chroma"
IMAGE_DIR = DATA_DIR / "images"
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

# LLM Provider（OpenAI 兼容，可切换任意一家）：
# LLM_API_KEY/LLM_BASE_URL/LLM_MODEL 优先，兼容旧 DEEPSEEK_* 变量
LLM_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL") or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.getenv("LLM_MODEL") or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# 兼容旧引用
DEEPSEEK_API_KEY = LLM_API_KEY
DEEPSEEK_BASE_URL = LLM_BASE_URL
DEEPSEEK_MODEL = LLM_MODEL

# 阿里云百炼 Qwen-VL（免费视觉）
QWV_API_KEY = os.getenv("QWV_API_KEY", "")
QWV_BASE_URL = os.getenv("QWV_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
QWV_MODEL = os.getenv("QWV_MODEL", "qwen-vl-max")

# Mathpix（数学公式 OCR，专业识别，需 app_id + app_key）
MATHPIX_APP_ID = os.getenv("MATHPIX_APP_ID", "")
MATHPIX_APP_KEY = os.getenv("MATHPIX_APP_KEY", "")

# 备用模型（AI 对话页可切换）
LLM_ALT_NAME = os.getenv("LLM_ALT_NAME", "")
LLM_ALT_KEY = os.getenv("LLM_ALT_KEY", "")
LLM_ALT_BASE = os.getenv("LLM_ALT_BASE", "")


def llm_models() -> list[dict]:
    """返回可用的对话模型列表 [{key, name}]"""
    models = [{"key": "main", "name": LLM_MODEL}]
    if LLM_ALT_NAME and LLM_ALT_KEY:
        models.append({"key": "alt", "name": LLM_ALT_NAME})
    return models

# 视觉模型专用（DeepSeek 无视觉，OCR/看图回答/拍照批改用智谱 GLM-4V-Flash 免费）
ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY", "")
ZHIPU_BASE_URL = os.getenv("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")

# 向量模型（可选）
BGE_MODEL_NAME = os.getenv("BGE_MODEL_NAME", "BAAI/bge-small-zh-v1.5")

# OCR/embedding 可用性（安装可选依赖后自动置 True）
OCR_AVAILABLE = False
EMBEDDING_AVAILABLE = False
