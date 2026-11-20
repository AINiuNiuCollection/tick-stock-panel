"""《缠中说禅》108 课书籍数据。

全文已本地化 (chanlun_108.json, 抓取自 chanlun108.cn, 2026-11-20 快照),
不依赖外部网络。提供目录与单课内容查询。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_BOOK_TITLE = "缠中说禅"
_DATA_PATH = Path(__file__).parent / "chanlun_108.json"


@lru_cache(maxsize=1)
def _load_lessons() -> list[dict]:
    data = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    return sorted(data, key=lambda x: x["no"])


def list_lessons() -> list[dict]:
    """目录: [{no, title}]。"""
    return [{"no": l["no"], "title": l["title"]} for l in _load_lessons()]


def get_lesson(no: int) -> dict | None:
    """单课: {no, title, content}。"""
    for l in _load_lessons():
        if l["no"] == no:
            return l
    return None


def book_title() -> str:
    return _BOOK_TITLE
