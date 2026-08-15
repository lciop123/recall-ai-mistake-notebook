# -*- coding: utf-8 -*-
from sqlmodel import Session, select, func, delete

from app.core.exceptions import AppError
from app.models.models import NOTEBOOK_COLORS, get_engine, Notebook, Question


def list_notebooks() -> list:
    with Session(get_engine()) as s:
        rows = s.exec(select(Notebook, func.count(Question.id))
                      .join(Question, Question.notebook_id == Notebook.id, isouter=True)
                      .group_by(Notebook.id)).all()
        return [{"id": n.id, "name": n.name, "color": n.color, "count": c, "created_at": str(n.created_at)} for n, c in rows]


def _normalize_color(color: str | None) -> str:
    value = (color or "").strip()
    return value if value in NOTEBOOK_COLORS else NOTEBOOK_COLORS[0]


def create_notebook(name: str, color: str) -> dict:
    name = name.strip()
    if not name:
        raise AppError(40001, "错题本名称不能为空", 400)
    with Session(get_engine()) as s:
        existing = s.exec(select(Notebook).where(Notebook.name == name)).first()
        if existing:
            raise AppError(40900, "同名错题本已存在", 409)
        nb = Notebook(name=name, color=_normalize_color(color))
        s.add(nb)
        s.commit()
        s.refresh(nb)
        return {"id": nb.id, "name": nb.name, "color": nb.color, "count": 0, "created_at": str(nb.created_at)}


def update_notebook(nb_id: int, name: str | None, color: str | None) -> dict:
    with Session(get_engine()) as s:
        nb = s.get(Notebook, nb_id)
        if not nb:
            raise AppError(40400, "错题本不存在", 404)
        if name is not None:
            clean_name = name.strip()
            if not clean_name:
                raise AppError(40001, "错题本名称不能为空", 400)
            existing = s.exec(select(Notebook).where(Notebook.name == clean_name, Notebook.id != nb_id)).first()
            if existing:
                raise AppError(40900, "同名错题本已存在", 409)
            nb.name = clean_name
        if color is not None:
            nb.color = _normalize_color(color)
        s.add(nb)
        s.commit()
        s.refresh(nb)
        return {"id": nb.id, "name": nb.name, "color": nb.color}


def delete_notebook(nb_id: int):
    with Session(get_engine()) as s:
        cnt = s.exec(select(func.count(Question.id)).where(Question.notebook_id == nb_id)).one()
        if cnt > 0:
            raise AppError(40900, f"错题本内还有 {cnt} 道错题，请先移出或删除", 409)
        nb = s.get(Notebook, nb_id)
        if not nb:
            raise AppError(40400, "错题本不存在", 404)
        s.delete(nb)
        s.commit()
