"""自动召回引擎。

给定一条消息，综合三路信号召回最相关的记忆：

1. 语义相似度（向量余弦）
2. 关键词命中（token 重叠）
3. 记忆图谱扩展（沿「标签节点」共享关系扩散到相关记忆）

最终按加权打分排序，并结合艾宾浩斯遗忘曲线对久未复习的记忆做衰减，
返回 Top-K 命中的记忆列表。
"""
from __future__ import annotations

import json
import math
import time
from typing import Any, Dict, List, Optional

from .embedder import bytes_to_vec, cosine, _tokenize
from .forgetting import ForgettingCurve


class RecallEngine:
    def __init__(self, store, embedder, cfg):
        self.store = store
        self.embedder = embedder
        self.cfg = cfg
        self.forgetting = ForgettingCurve(cfg)

    # ------------------------------------------------------------------ 打分
    def _score(self, qvec, memory: Dict[str, Any], q_tokens: set,
               now_ts: float) -> float:
        rec = self.cfg.get("recall", {})
        w_sim = float(rec.get("similarity_weight", 0.40))
        w_imp = float(rec.get("importance_weight", 0.35))
        w_rec = float(rec.get("recency_weight", 0.25))

        # 语义相似度
        sim = 0.0
        if memory.get("embedding"):
            try:
                sim = max(cosine(qvec, bytes_to_vec(memory["embedding"])), 0.0)
            except Exception:
                sim = 0.0

        # 关键词命中（可显著提升召回，弥补弱向量环境）
        m_tokens = set(_tokenize(memory["content"] or ""))
        overlap = len(q_tokens & m_tokens) / (len(q_tokens) or 1)
        sim = max(sim, min(overlap * 2.0, 1.0) * 0.6)

        imp = float(memory.get("importance") or 0.5)
        age = max(0.0, now_ts - float(memory.get("created_at") or now_ts))
        recency = math.exp(-age / (24 * 3600))

        score = w_sim * sim + w_imp * imp + w_rec * recency

        if self.cfg.get("forgetting.enabled", True):
            score *= self.forgetting.retention(age_days=age / 86400.0)
        return score

    # ------------------------------------------------------------------ 召回
    def recall(self, repo_id: str, message: str,
               top_k: Optional[int] = None) -> List[Dict[str, Any]]:
        rec = self.cfg.get("recall", {})
        top_k = top_k or int(rec.get("top_k", 8))
        min_score = float(rec.get("min_score", 0.30))

        qvec = self.embedder.embed(message)
        q_tokens = set(_tokenize(message))
        now_ts = time.time()

        scored = []
        for m in self.store.list_memories(repo_id):
            s = self._score(qvec, m, q_tokens, now_ts)
            if s >= min_score:
                scored.append({"memory": m, "score": s})

        if rec.get("graph_expand", True) and scored:
            self._graph_expand(repo_id, scored)

        scored.sort(key=lambda x: x["score"], reverse=True)
        seen: set = set()
        result: List[Dict[str, Any]] = []
        for item in scored:
            mid = item["memory"]["id"]
            if mid in seen:
                continue
            seen.add(mid)
            result.append({"memory": item["memory"], "score": item["score"]})
            if len(result) >= top_k:
                break
        return result

    def _graph_expand(self, repo_id: str, scored: List[Dict[str, Any]]) -> None:
        """沿共享标签节点，把相邻记忆以衰减权重补充进候选集。"""
        depth = int(self.cfg.get("recall.graph_expand_depth", 2))
        top_n = int(self.cfg.get("recall.top_k", 8))
        for item in scored[:top_n]:
            mid = item["memory"]["id"]
            base = item["score"]
            for related in self.store.related_memories(repo_id, mid, depth=depth):
                boost = base * 0.4 * (0.5 ** (related["distance"] - 1))
                scored.append({"memory": related["memory"], "score": boost})


def extract_key_hits(recall_result: List[Dict[str, Any]]) -> List[str]:
    """提取每条消息的「关键命中」摘要（供缓存友好注入使用）。"""
    return [(item["memory"].get("content") or "").strip()
            for item in recall_result if (item["memory"].get("content") or "").strip()]
