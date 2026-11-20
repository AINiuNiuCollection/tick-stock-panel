"""知识库 API。

提供列表/详情/搜索/分类统计接口。
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.services import chanlun_book
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


# ---- 《缠中说禅》108 课 (本地化全文) ----
# 注意: 必须定义在 /{entry_id} 之前, 否则会被通配路径吞掉

@router.get("/chanlun")
def chanlun_toc():
    """《缠中说禅》108 课目录。"""
    lessons = chanlun_book.list_lessons()
    return {"book": chanlun_book.book_title(), "total": len(lessons), "lessons": lessons}


@router.get("/chanlun/{lesson_no}")
def chanlun_lesson(lesson_no: int):
    """《缠中说禅》单课全文。"""
    if lesson_no < 1 or lesson_no > 108:
        return {"detail": "课程编号必须在 1-108 之间"}
    lesson = chanlun_book.get_lesson(lesson_no)
    if lesson is None:
        return {"detail": "课程不存在"}
    return lesson


@router.get("/{entry_id}")
def get_entry(entry_id: str):
    entry = knowledge_store.get_by_id(entry_id)
    if entry is None:
        return {"detail": "条目不存在"}, 404
    return entry
