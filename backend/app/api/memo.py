"""备忘录 API。

提供 CRUD + 过滤搜索 + 置顶 + 标签统计 + Markdown 导出。
"""
from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.services.memo_store import memo_store

router = APIRouter(prefix="/api/memo", tags=["memo"])


# ---- Pydantic models ----

class MemoCreate(BaseModel):
    title: str = ""
    content: str = Field(..., min_length=1)
    tags: list[str] = Field(default_factory=list)
    type: str = "note"
    pinned: bool = False
    related_symbol: list[str] = Field(default_factory=list)
    related_strategy: list[str] = Field(default_factory=list)


class MemoUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    tags: list[str] | None = None
    type: str | None = None
    pinned: bool | None = None
    related_symbol: list[str] | None = None
    related_strategy: list[str] | None = None


class PinUpdate(BaseModel):
    pinned: bool


class BatchDelete(BaseModel):
    ids: list[str]


# ---- Endpoints ----

@router.get("")
def list_memos(
    tag: str | None = Query(None),
    type: str | None = Query(None),
    q: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    items, total = memo_store.query(tag=tag, type_=type, q=q, limit=limit, offset=offset)
    return {"items": items, "total": total}


@router.post("")
def create_memo(body: MemoCreate):
    return memo_store.create(body.model_dump())


@router.patch("/{memo_id}")
def update_memo(memo_id: str, body: MemoUpdate):
    patch = body.model_dump(exclude_none=True)
    updated = memo_store.update(memo_id, patch)
    if updated is None:
        return {"detail": "备忘录不存在"}, 404
    return updated


@router.delete("/{memo_id}")
def delete_memo(memo_id: str):
    ok = memo_store.delete(memo_id)
    return {"ok": ok}


@router.post("/batch-delete")
def batch_delete_memos(body: BatchDelete):
    n = memo_store.batch_delete(body.ids)
    return {"deleted": n}


@router.patch("/{memo_id}/pin")
def toggle_pin(memo_id: str, body: PinUpdate):
    updated = memo_store.toggle_pin(memo_id, body.pinned)
    if updated is None:
        return {"detail": "备忘录不存在"}, 404
    return updated


@router.get("/tags")
def memo_tags():
    return memo_store.tags_summary()


@router.get("/export")
def export_memos(year: int = Query(...), month: int = Query(..., ge=1, le=12)):
    content = memo_store.export_markdown(year, month)
    return {"content": content}
