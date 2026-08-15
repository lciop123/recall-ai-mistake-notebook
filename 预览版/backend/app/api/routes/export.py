# -*- coding: utf-8 -*-
from fastapi import APIRouter
from fastapi.responses import Response

from app.services import export_service, report_service

router = APIRouter(prefix="/api/export", tags=["export"])


@router.get("/markdown")
def export_markdown(notebook_id: int | None = None, subject: str | None = None,
                    include_answer: bool = True, include_analysis: bool = True):
    md = export_service.build_markdown(notebook_id, subject, include_answer, include_analysis)
    return Response(content=md, media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=recall_export.md"})


@router.get("/pdf")
def export_pdf(notebook_id: int | None = None, subject: str | None = None,
               include_answer: bool = True, include_analysis: bool = True):
    data = export_service.build_pdf(notebook_id, subject, include_answer, include_analysis)
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": "attachment; filename=recall_export.pdf"})


@router.get("/weekly/markdown")
def export_weekly_markdown(week_start: str | None = None, subject: str | None = None):
    md = report_service.build_weekly_markdown(week_start, subject)
    filename = f"recall_weekly_{report_service.weekly_summary(week_start, subject)['week_start']}.md"
    return Response(content=md, media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


@router.get("/weekly/pdf")
def export_weekly_pdf(week_start: str | None = None, subject: str | None = None):
    data = report_service.build_weekly_pdf(week_start, subject)
    filename = f"recall_weekly_{report_service.weekly_summary(week_start, subject)['week_start']}.pdf"
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})
