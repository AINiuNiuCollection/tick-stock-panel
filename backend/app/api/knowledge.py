"""知识库 API。

提供列表/详情/搜索/分类统计接口。
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.services.knowledge_store import knowledge_store

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.get("")
def list_entries(
    category: str | None = Query(None),
    q: str | None = Query(None),
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
):
    items, total = knowledge_store.query(
        category=category, q=q, limit=limit, offset=offset,
    )
    return {"items": items, "total": total}


@router.get("/categories")
def list_categories():
    return knowledge_store.categories_summary()


@router.get("/{entry_id}")
def get_entry(entry_id: str):
    entry = knowledge_store.get_by_id(entry_id)
    if entry is None:
        return {"detail": "条目不存在"}, 404
    return entry
