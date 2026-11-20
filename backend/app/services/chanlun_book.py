"""《缠中说禅》108 课书籍数据。

全文已本地化 (chanlun_lessons/001.md ~ 108.md, 一课一文件,
抓取自 chanlun108.cn, 2026-11-20 快照), 不依赖外部网络。
文件格式: 首行 "# 标题", 空行后为正文 (段落以空行分隔)。
提供目录与单课内容查询。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_BOOK_TITLE = "缠中说禅"
_LESSONS_DIR = Path(__file__).parent / "chanlun_lessons"


@lru_cache(maxsize=1)
def _scan_lessons() -> dict[int, dict]:
    out: dict[int, dict] = {}
    for f in sorted(_LESSONS_DIR.glob("*.md")):
        try:
            no = int(f.stem)
        except ValueError:
            continue
        text = f.read_text(encoding="utf-8")
        head, _, body = text.partition("\n")
        title = head.lstrip("# ").strip()
        out[no] = {"no": no, "title": title, "content": body.strip()}
    return out


def list_lessons() -> list[dict]:
    """目录: [{no, title}]。"""
    return [
        {"no": k, "title": v["title"]} for k, v in sorted(_scan_lessons().items())
    ]


def get_lesson(no: int) -> dict | None:
    """单课: {no, title, content}。"""
    return _scan_lessons().get(no)


def book_title() -> str:
    return _BOOK_TITLE
