# 历史事件 source 解析: zh.wikipedia REST 搜索 API -> 首个命中条目 canonical URL
# 用法: NO_PROXY='*' python scripts/resolve_event_sources.py queries.json out.json
import json
import sys
import urllib.parse

import httpx

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
SEARCH = "https://zh.wikipedia.org/w/rest.php/v1/search/page"


def main() -> int:
    with open(sys.argv[1], encoding="utf-8") as f:
        queries = json.load(f)  # [{"id":..., "q":..., "prefer": [...]可选关键词}]
    out = []
    with httpx.Client(timeout=15.0, verify=False, headers=UA, follow_redirects=True) as c:
        for item in queries:
            src = None
            for q in item["q"] if isinstance(item["q"], list) else [item["q"]]:
                try:
                    r = c.get(SEARCH, params={"q": q, "limit": 5})
                    pages = (r.json() or {}).get("pages", [])
                except Exception as exc:  # noqa: BLE001
                    print(f"[ERR ] {item['id']}: {exc}")
                    continue
                # prefer 关键词命中, 否则取首条
                pages_sorted = sorted(
                    pages,
                    key=lambda p: -sum(1 for kw in item.get("prefer", []) if kw in p.get("excerpt", "") or kw in p.get("title", "")),
                )
                for p in pages_sorted[:3]:
                    title = p["key"]
                    url = f"https://zh.wikipedia.org/wiki/{urllib.parse.quote(title)}"
                    try:
                        pr = c.get(url)
                    except Exception:  # noqa: BLE001
                        continue
                    print(f"[{pr.status_code}] {item['id']} <- {title}")
                    if pr.status_code == 200:
                        src = url
                        break
                if src:
                    break
            out.append({"id": item["id"], "source": src})
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
