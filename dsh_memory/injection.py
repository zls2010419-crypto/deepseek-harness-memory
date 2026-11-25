"""缓存友好注入：把画像（稳定前缀）+ 关键命中（动态上下文）注入系统提示。

缓存友好的关键设计：
- 稳定块（人格 + 用户画像）永远放在最前、格式固定 → 命中 LLM 前缀缓存。
- 动态块（本次召回的关键命中）放最后、按稳定顺序排列 → 减少缓存失效。
- 每条消息只注入「关键命中」，避免无关记忆稀释注意力与浪费 token。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _estimate_tokens(text: str) -> int:
    """粗略 token 估算：中文按字符，英文按 1.3 词/字。"""
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return cjk + int(other / 4) + 1


class InjectionBuilder:
    def __init__(self, cfg, persona_text: str = ""):
        self.cfg = cfg
        self.persona_text = persona_text
        self.max_tokens = int(cfg.get("recall.max_tokens", 2000))

    def build(self, repo_id: str, message: str, key_hits: List[str],
              profile_text: str) -> Dict[str, Any]:
        """构建注入块，返回 {system_prompt, stable_prefix, dynamic_context}。"""
        stable = self.persona_text.strip()
        if profile_text and profile_text.strip():
            stable += ("\n\n" + profile_text.strip()) if stable else profile_text.strip()

        # 动态块：关键命中按稳定顺序去重、截断
        seen = set()
        hits = []
        budget = self.max_tokens
        for h in key_hits:
            if not h or h in seen:
                continue
            seen.add(h)
            cost = _estimate_tokens(h)
            if budget - cost < 200:  # 保留余量
                break
            hits.append(f"- {h}")
            budget -= cost

        dynamic = ("相关记忆：\n" + "\n".join(hits)) if hits else ""

        system_prompt = stable
        if dynamic:
            system_prompt = (stable + "\n\n" + dynamic).strip()

        return {
            "system_prompt": system_prompt,
            "stable_prefix": stable,
            "dynamic_context": dynamic,
        }
