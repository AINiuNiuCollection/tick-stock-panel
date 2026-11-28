# 探针: 历史 major 事件候选 source URL 批量验证 (P3-T6)
# 用法: NO_PROXY='*' python scripts/probe_event_sources.py candidates.json
# candidates.json: [{"id":..., "urls":[...]}...]; 输出每个事件首个 200 的 URL
import json
import sys

import httpx

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def main() -> int:
    with open(sys.argv[1], encoding="utf-8") as f:
        cands = json.load(f)
    out = []
    with httpx.Client(timeout=10.0, verify=False, headers=UA, follow_redirects=True) as c:
        for ev in cands:
            ok = None
            for url in ev["urls"]:
                try:
                    r = c.get(url)
                except Exception as exc:  # noqa: BLE001
                    print(f"[ERR ] {ev['id']} {url} -> {exc}")
                    continue
                print(f"[{r.status_code}] {ev['id']} {url}")
                if r.status_code == 200 and len(r.content) > 5000 and "verify" not in r.url.host:
                    ok = url
                    break
            out.append({"id": ev["id"], "source": ok})
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
