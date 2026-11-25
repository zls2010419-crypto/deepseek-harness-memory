"""用户画像：从记忆里沉淀稳定的「事实」与「偏好」，注入系统提示。

- facts：关于用户的稳定事实（身份、技术栈、项目等）。
- preferences：偏好（风格、语言、工具等）。
- summary：一段可直接注入上下文的画像摘要。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .store import MemoryStore


class UserProfile:
    def __init__(self, store: MemoryStore):
        self.store = store

    def get(self, repo_id: str) -> Dict[str, Any]:
        return self.store.get_profile(repo_id)

    def add_fact(self, repo_id: str, fact: str) -> None:
        cur = self.store.get_profile(repo_id)
        facts = cur["facts"]
        if fact not in facts:
            facts.append(fact)
        self.store.set_profile(repo_id, facts=facts)

    def add_preference(self, repo_id: str, pref: str) -> None:
        cur = self.store.get_profile(repo_id)
        prefs = cur["preferences"]
        if pref not in prefs:
            prefs.append(pref)
        self.store.set_profile(repo_id, preferences=prefs)

    def rebuild_summary(self, repo_id: str) -> str:
        """基于事实与偏好重算画像摘要（规则式，可替换为 LLM 总结）。"""
        cur = self.store.get_profile(repo_id)
        facts = cur["facts"]
        prefs = cur["preferences"]
        parts = []
        if facts:
            parts.append("关于用户：" + "；".join(facts[:20]) + "。")
        if prefs:
            parts.append("用户偏好：" + "；".join(prefs[:20]) + "。")
        summary = " ".join(parts).strip()
        if summary:
            self.store.set_profile(repo_id, summary=summary)
        return summary

    def render(self, repo_id: str) -> str:
        """渲染为可注入系统提示的稳定文本块。"""
        cur = self.store.get_profile(repo_id)
        if cur["summary"]:
            return cur["summary"]
        return self.rebuild_summary(repo_id)
