"""备忘录 JSON 存储。

与 JsonReportStore 同样的原子写 + 实例锁模式, 但不做自动裁剪
(备忘录是长期资产, 不能丢), 并支持服务端过滤 (tag/type/keyword)。

存储文件: data/user_data/memos.json (数组, pinned 优先 → updated_at 降序)
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

from app.market_time import cn_now

logger = logging.getLogger(__name__)

# 允许的备忘录类型
VALID_TYPES = {"note", "bug", "param", "idea", "todo", "insight"}


class MemoStore:
    """备忘录 JSON 存储 (原子写 + 实例锁, 不裁剪)。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def _path(self) -> Path:
        from app.config import settings
        p = settings.data_dir / "user_data" / "memos.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def list_all(self) -> list[dict]:
        """返回全部备忘录 (pinned 优先 → updated_at 降序)。"""
        p = self._path()
        if not p.exists():
            return []
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, list):
                # 兼容旧版 single-string 字段 → 转为 list
                for it in data:
                    for k in ("related_symbol", "related_strategy"):
                        v = it.get(k)
                        if v is None:
                            it[k] = []
                        elif isinstance(v, str):
                            it[k] = [v] if v else []
                        elif not isinstance(v, list):
                            it[k] = []
                return self._sort(data)
        except Exception as e:  # noqa: BLE001
            logger.warning("memos.json malformed: %s", e)
        return []

    @staticmethod
    def _sort(items: list[dict]) -> list[dict]:
        """置顶优先, 其次按 updated_at 降序。"""
        return sorted(
            items,
            key=lambda r: (r.get("pinned", False), r.get("updated_at", "")),
            reverse=True,
        )

    def _atomic_write(self, items: list[dict]) -> None:
        p = self._path()
        text = json.dumps(items, indent=2, ensure_ascii=False)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, p)

    @staticmethod
    def _now_iso() -> str:
        return cn_now().replace(tzinfo=None).isoformat(timespec="seconds")

    def _make_id(self) -> str:
        return f"memo_{int(time.time() * 1000)}_{os.urandom(2).hex()}"

    def query(
        self,
        *,
        tag: str | None = None,
        type_: str | None = None,
        q: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """过滤查询, 返回 (items, total)。"""
        items = self.list_all()
        filtered = []
        kw = (q or "").strip().lower()
        for it in items:
            if tag and tag not in it.get("tags", []):
                continue
            if type_ and it.get("type") != type_:
                continue
            if kw and kw not in (it.get("content", "") or "").lower() and kw not in (it.get("title", "") or "").lower():
                continue
            filtered.append(it)
        total = len(filtered)
        return filtered[offset : offset + limit], total

    def create(self, data: dict) -> dict:
        """新增备忘录。"""
        with self._lock:
            items = self.list_all()
            now = self._now_iso()
            entry = {
                "id": self._make_id(),
                "title": (data.get("title") or "").strip(),
                "content": (data.get("content") or "").strip(),
                "tags": list(data.get("tags") or []),
                "type": data.get("type") or "note",
                "pinned": bool(data.get("pinned", False)),
                "related_symbol": list(data.get("related_symbol") or []),
                "related_strategy": list(data.get("related_strategy") or []),
                "created_at": now,
                "updated_at": now,
            }
            if entry["type"] not in VALID_TYPES:
                entry["type"] = "note"
            items.append(entry)
            self._atomic_write(self._sort(items))
        logger.info("memo created: %s", entry["id"])
        return entry

    def update(self, memo_id: str, patch: dict) -> dict | None:
        """部分更新, 返回更新后的备忘录 (不存在返回 None)。"""
        with self._lock:
            items = self.list_all()
            for it in items:
                if it.get("id") == memo_id:
                    if "title" in patch:
                        it["title"] = patch["title"].strip()
                    if "content" in patch:
                        it["content"] = patch["content"].strip()
                    if "tags" in patch:
                        it["tags"] = list(patch["tags"])
                    if "type" in patch:
                        t = patch["type"]
                        it["type"] = t if t in VALID_TYPES else "note"
                    if "pinned" in patch:
                        it["pinned"] = bool(patch["pinned"])
                    if "related_symbol" in patch:
                        it["related_symbol"] = list(patch["related_symbol"] or [])
                    if "related_strategy" in patch:
                        it["related_strategy"] = list(patch["related_strategy"] or [])
                    it["updated_at"] = self._now_iso()
                    self._atomic_write(self._sort(items))
                    return it
        return None

    def delete(self, memo_id: str) -> bool:
        with self._lock:
            items = self.list_all()
            before = len(items)
            items = [it for it in items if it.get("id") != memo_id]
            if len(items) < before:
                self._atomic_write(items)
                return True
        return False

    def batch_delete(self, ids: list[str]) -> int:
        with self._lock:
            items = self.list_all()
            id_set = set(ids)
            kept = [it for it in items if it.get("id") not in id_set]
            deleted = len(items) - len(kept)
            if deleted > 0:
                self._atomic_write(kept)
            return deleted

    def toggle_pin(self, memo_id: str, pinned: bool) -> dict | None:
        with self._lock:
            items = self.list_all()
            for it in items:
                if it.get("id") == memo_id:
                    it["pinned"] = pinned
                    it["updated_at"] = self._now_iso()
                    self._atomic_write(self._sort(items))
                    return it
        return None

    def tags_summary(self) -> list[dict]:
        """标签使用频次统计 (降序)。"""
        items = self.list_all()
        counts: dict[str, int] = {}
        for it in items:
            for t in it.get("tags", []):
                counts[t] = counts.get(t, 0) + 1
        return [{"tag": k, "count": v} for k, v in sorted(counts.items(), key=lambda x: -x[1])]

    def export_markdown(self, year: int, month: int) -> str:
        """按年月聚合导出为 Markdown 文本。"""
        items = self.list_all()
        prefix = f"{year:04d}-{month:02d}-"
        month_items = [
            it for it in items
            if (it.get("created_at") or "").startswith(prefix)
        ]
        # 按日期分组
        by_day: dict[str, list[dict]] = {}
        for it in month_items:
            day = (it.get("created_at") or "")[:10]
            by_day.setdefault(day, []).append(it)

        lines: list[str] = []
        for day in sorted(by_day.keys()):
            lines.append(f"## {day}")
            lines.append("")
            for it in by_day[day]:
                tags_str = " ".join(f"#{t}" for t in it.get("tags", []))
                time_str = (it.get("created_at") or "")[11:16]
                type_label = it.get("type", "note")
                title = (it.get("title") or "").strip()
                header = f"- {time_str} #{type_label} {tags_str}"
                if title:
                    lines.append(f"{header}")
                    lines.append(f"  **{title}**")
                else:
                    lines.append(header)
                # 多行内容缩进
                for line in (it.get("content") or "").split("\n"):
                    lines.append(f"  {line}")
                lines.append("")
            lines.append("")

        if not lines:
            lines.append(f"# {year:04d}-{month:02d} 备忘录导出\n\n（本月无记录）\n")
        else:
            lines.insert(0, f"# {year:04d}-{month:02d} 备忘录导出\n")

        return "\n".join(lines)


# 单例
memo_store = MemoStore()
