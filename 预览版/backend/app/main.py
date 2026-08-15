# -*- coding: utf-8 -*-
"""Recall 后端入口：uvicorn app.main:app --reload --port 8000"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import (notebooks, questions, capture, reviews,
                            review_plan, dashboard, chat, export, health, ai, redo)
from app.core.config import IMAGE_DIR
from app.core.exceptions import register_exception_handlers
from app.models.models import create_db_and_tables

app = FastAPI(title="Recall API", version="0.1.0")

# 静态图片（对话图片 / 错题图片）
app.mount("/images", StaticFiles(directory=str(IMAGE_DIR)), name="images")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 本地演示放开；对外部署时按需收紧
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)


@app.on_event("startup")
def on_startup():
    create_db_and_tables()


for r in (health.router, notebooks.router, questions.router, capture.router,
          reviews.router, review_plan.router, dashboard.router, chat.router,
          export.router, ai.router, redo.router):
    app.include_router(r)
