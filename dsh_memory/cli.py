"""CLI 桥接：JSON-lines over stdio，供 JS bundle 通过子进程调用。

协议：stdin 每行一个请求 ``{"id": 1, "method": "...", "params": {...}}``，
stdout 每行一个响应 ``{"id": 1, "result": ...}`` 或 ``{"id": 1, "error": "..."}``。

支持的方法：
    save_memory, recall, recall_and_inject, save_knowledge_page,
    add_fact, add_preference, consolidate, stats, verify_integrity
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dsh_memory import MemoryPlugin

# 项目根 = 本文件所在目录的上一级
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _write(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _dispatch(plugin: MemoryPlugin, method: str, params: dict):
    repo = params.get("repo_id", "default")

    if method == "save_memory":
        return plugin.save_memory(
            params["content"],
            repo_id=repo,
            kind=params.get("kind", "episodic"),
            importance=float(params.get("importance", 0.5)),
            tags=params.get("tags") or None,
            source=params.get("source"),
        )

    if method == "recall":
        result = plugin.recall(params["message"], repo_id=repo,
                               top_k=params.get("top_k"))
        return [{"content": r["memory"]["content"], "score": r["score"]}
                for r in result]

    if method == "recall_and_inject":
        ctx = plugin.recall_and_inject(params["message"], repo_id=repo,
                                       top_k=params.get("top_k"))
        return {"system_prompt": ctx["system_prompt"], "hits": ctx["hits"]}

    if method == "save_knowledge_page":
        return plugin.save_knowledge_page(
            params["title"], params["content"], repo_id=repo,
            summary=params.get("summary"), tags=params.get("tags") or None,
            importance=float(params.get("importance", 0.5)),
        )

    if method == "add_fact":
        plugin.add_fact(params["fact"], repo_id=repo)
        return True

    if method == "add_preference":
        plugin.add_preference(params["pref"], repo_id=repo)
        return True

    if method == "consolidate":
        return plugin.consolidate(repo)

    if method == "stats":
        return plugin.stats(repo)

    if method == "verify_integrity":
        return plugin.verify_integrity(repo)

    raise ValueError(f"unknown method: {method}")


def main() -> None:
    plugin = MemoryPlugin(project_root=PROJECT_ROOT)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception as e:
            _write({"id": None, "error": f"bad json: {e}"})
            continue
        rid = req.get("id")
        method = req.get("method")
        params = req.get("params") or {}
        try:
            _write({"id": rid, "result": _dispatch(plugin, method, params)})
        except Exception as e:
            _write({"id": rid, "error": str(e)})


if __name__ == "__main__":
    main()
