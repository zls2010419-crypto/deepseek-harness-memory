"""人格文件：加载 persona.yaml，渲染为稳定的系统提示前缀。

人格是「稳定块」的第一部分，格式固定以命中前缀缓存。
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from .config import load_yaml


class Persona:
    def __init__(self, project_root: str, file_rel: str = "persona/persona.yaml"):
        self.path = os.path.join(project_root, file_rel)
        self.data: Dict[str, Any] = {}

    def load(self) -> Dict[str, Any]:
        if os.path.exists(self.path):
            self.data = load_yaml(self.path) or {}
        return self.data

    def render(self) -> str:
        self.load()
        if not self.data:
            return ""
        name = self.data.get("name", "")
        traits = self.data.get("traits", [])
        tone = self.data.get("tone", "")
        values = self.data.get("values", [])
        goals = self.data.get("goals", [])

        lines = []
        if name:
            lines.append(f"你是 {name}。")
        if traits:
            lines.append("性格特质：" + "、".join(traits) + "。")
        if tone:
            lines.append(f"语气风格：{tone}。")
        if values:
            lines.append("核心原则：" + "；".join(values) + "。")
        if goals:
            lines.append("长期目标：" + "；".join(goals) + "。")
        return "\n".join(lines)
