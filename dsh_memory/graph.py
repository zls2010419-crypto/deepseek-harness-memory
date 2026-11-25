"""记忆图谱：实体/概念节点 + 关系边 + 查询与统计。

- 节点：概念、实体、标签等，权重累积表示重要度。
- 边：has_tag（记忆→标签）、related_to（概念间关系）等。
- 提供邻居查询、连通分量统计、中心度等图谱分析能力。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .store import MemoryStore


class MemoryGraph:
    def __init__(self, store: MemoryStore):
        self.store = store

    def add_concept(self, repo_id: str, label: str, node_type: str = "concept",
                    weight: float = 1.0, metadata: Optional[dict] = None) -> str:
        return self.store.upsert_node(repo_id, label, node_type, weight, metadata)

    def relate(self, repo_id: str, source_label: str, target_label: str,
               relation: str = "related_to", weight: float = 1.0) -> None:
        sid = self.store.upsert_node(repo_id, source_label)
        tid = self.store.upsert_node(repo_id, target_label)
        self.store.add_edge(repo_id, sid, tid, relation, weight)

    def neighbors(self, repo_id: str, label: str,
                  depth: int = 2) -> List[Dict[str, Any]]:
        nid = self._node_id(repo_id, label)
        return self.store.neighbors(repo_id, nid, depth=depth)

    def _node_id(self, repo_id: str, label: str) -> str:
        from .store import sha256
        return sha256(repo_id + "\x00" + label.lower())[:16]

    def stats(self, repo_id: str) -> Dict[str, Any]:
        """返回图谱统计：节点数、边数、中心度 Top 节点。"""
        conn = self.store._connect(repo_id)
        n_nodes = conn.execute(
            "SELECT COUNT(*) c FROM graph_nodes WHERE repo_id=?", (repo_id,)).fetchone()["c"]
        n_edges = conn.execute(
            "SELECT COUNT(*) c FROM graph_edges WHERE repo_id=?", (repo_id,)).fetchone()["c"]
        deg_rows = conn.execute(
            "SELECT n.id AS nid, n.label AS label,"
            " (SELECT COUNT(*) FROM graph_edges e WHERE e.repo_id=n.repo_id"
            "  AND (e.source_id=n.id OR e.target_id=n.id)) AS deg"
            " FROM graph_nodes n WHERE n.repo_id=? ORDER BY deg DESC LIMIT 10",
            (repo_id,)).fetchall()
        top = [{"label": r["label"], "degree": r["deg"]} for r in deg_rows]
        return {"nodes": n_nodes, "edges": n_edges, "top_nodes": top}
