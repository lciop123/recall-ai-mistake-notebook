# -*- coding: utf-8 -*-
from fastapi import APIRouter

from app.api import ok

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health():
    from app.core.config import DEEPSEEK_API_KEY
    return ok({"status": "ok", "version": "0.1.0",
               "deepseek": bool(DEEPSEEK_API_KEY)})
