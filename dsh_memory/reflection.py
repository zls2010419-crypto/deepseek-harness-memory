"""深度反思：把近期零散记忆提炼为更高层的知识 / 结论。

空闲窗口触发。反思产物写入 reflections 表，并按需回写为知识页或画像事实。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .store import MemoryStore


class Reflector:
    def __init__(self, store: MemoryStore, profile=None, cfg=None):
        self.store = store
        self.profile = profile
        self.cfg = cfg

    def reflect(self, repo_id: str, recent: Optional[List[Dict[str, Any]]] = None,
                llm_summarize: Optional[callable] = None) -> str:
        """对近期记忆做深度反思，返回反思文本。

        ``llm_summarize`` 为可选回调，接入方可将记忆批量交给大模型总结；
        未提供时用规则式摘要兜底。
        """
        recent = recent if recent is not None else self.store.list_memories(repo_id, limit=50)
        if not recent:
            return ""

        snippets = [m["content"] for m in recent[:20]]
        if llm_summarize is not None:
            text = llm_summarize(snippets)
        else:
            text = self._rule_based(snippets)

        if text:
            self.store.add_reflection(repo_id, text)
        return text

    def _rule_based(self, snippets: List[str]) -> str:
        """规则式反思：按记忆类别聚合，提炼高频主题。"""
        import collections
        kinds = collections.Counter()
        themes = collections.Counter()
        for s in snippets:
            kinds["记忆"] += 1
        # 简单主题提炼：按冒号/关键词切分
        for s in snippets:
            if "偏好" in s or "喜欢" in s or "prefer" in s.lower():
                themes["用户偏好"] += 1
            elif "项目" in s or "repo" in s.lower() or "仓库" in s:
                themes["项目相关"] += 1
            elif "技术" in s or "API" in s or "架构" in s:
                themes["技术方案"] += 1
            else:
                themes["一般记忆"] += 1

        lines = ["反思摘要（%s 条近期记忆）：" % len(snippets)]
        for theme, cnt in themes.most_common(5):
            lines.append(f"- {theme}: {cnt} 条")
        return "\n".join(lines)

    def distill_to_profile(self, repo_id: str) -> int:
        """把「偏好/事实」类记忆提炼进用户画像，返回新增条数。"""
        if self.profile is None:
            return 0
        added = 0
        for m in self.store.list_memories(repo_id, limit=200):
            content = m.get("content") or ""
            if "偏好" in content or "喜欢" in content:
                self.profile.add_preference(repo_id, content)
                added += 1
            elif m.get("kind") == "semantic":
                self.profile.add_fact(repo_id, content)
                added += 1
        if added:
            self.profile.rebuild_summary(repo_id)
        return added
