# -*- coding: utf-8 -*-
from fastapi import APIRouter

from app.api import ok
from app.services import dashboard_service

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/overview")
def overview(subject: str | None = None):
    return ok(dashboard_service.overview(subject))


@router.get("/trend")
def trend(days: int = 7, subject: str | None = None):
    return ok(dashboard_service.trend(days, subject))


@router.get("/knowledge-graph")
def knowledge_graph(subject: str | None = None):
    return ok(dashboard_service.knowledge_graph(subject))


@router.get("/distributions")
def distributions(subject: str | None = None):
    return ok(dashboard_service.distributions(subject))


@router.get("/learning-plan")
def learning_plan(subject: str | None = None, limit: int = 3):
    return ok(dashboard_service.learning_plan(subject, limit))


@router.get("/alerts")
def alerts(subject: str | None = None):
    return ok(dashboard_service.alerts(subject))
