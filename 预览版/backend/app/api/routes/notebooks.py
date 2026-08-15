# -*- coding: utf-8 -*-
from fastapi import APIRouter

from app.api import ok
from app.schemas.schemas import NotebookCreate, NotebookUpdate
from app.services import notebook_service

router = APIRouter(prefix="/api/notebooks", tags=["notebooks"])


@router.get("")
def list_notebooks():
    return ok(notebook_service.list_notebooks())


@router.post("")
def create_notebook(data: NotebookCreate):
    return ok(notebook_service.create_notebook(data.name, data.color))


@router.patch("/{nb_id}")
def update_notebook(nb_id: int, data: NotebookUpdate):
    return ok(notebook_service.update_notebook(nb_id, data.name, data.color))


@router.delete("/{nb_id}")
def delete_notebook(nb_id: int):
    notebook_service.delete_notebook(nb_id)
    return ok(None, "已删除")
