"""存储层：SQLite + 按仓库隔离 + 反篡改控制。

- 每个仓库（repo_id）一个独立的 SQLite 文件，记忆互不串扰。
- 每条记忆 / 知识页 / 反思均带 SHA256 完整性哈希，可校验是否被篡改。
- 所有写入追加到 audit_log 审计日志（append-only），记录操作与载荷哈希。
- 高权限写入需校验 privileged token。
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from typing import Any, Dict, Iterable, List, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id            TEXT PRIMARY KEY,
    repo_id       TEXT NOT NULL,
    content       TEXT NOT NULL,
    kind          TEXT NOT NULL DEFAULT 'episodic',
    importance    REAL NOT NULL DEFAULT 0.5,
    tags          TEXT NOT NULL DEFAULT '[]',
    source        TEXT,
    embedding     BLOB,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL,
    last_recalled_at REAL,
    recall_count  INTEGER NOT NULL DEFAULT 0,
    hash          TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'active'
);
CREATE INDEX IF NOT EXISTS idx_mem_repo ON memories(repo_id, status);
CREATE INDEX IF NOT EXISTS idx_mem_kind  ON memories(repo_id, kind);

CREATE TABLE IF NOT EXISTS knowledge_pages (
    id          TEXT PRIMARY KEY,
    repo_id     TEXT NOT NULL,
    title       TEXT NOT NULL,
    content     TEXT NOT NULL,
    summary     TEXT,
    tags        TEXT NOT NULL DEFAULT '[]',
    importance  REAL NOT NULL DEFAULT 0.5,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    hash        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_page_repo ON knowledge_pages(repo_id);

CREATE TABLE IF NOT EXISTS graph_nodes (
    id         TEXT PRIMARY KEY,
    repo_id    TEXT NOT NULL,
    label      TEXT NOT NULL,
    node_type  TEXT NOT NULL DEFAULT 'concept',
    weight     REAL NOT NULL DEFAULT 1.0,
    metadata   TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_node_repo ON graph_nodes(repo_id);

CREATE TABLE IF NOT EXISTS graph_edges (
    id         TEXT PRIMARY KEY,
    repo_id    TEXT NOT NULL,
    source_id  TEXT NOT NULL,
    target_id  TEXT NOT NULL,
    relation   TEXT NOT NULL DEFAULT 'related_to',
    weight     REAL NOT NULL DEFAULT 1.0,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_edge_repo ON graph_edges(repo_id);
CREATE INDEX IF NOT EXISTS idx_edge_src  ON graph_edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edge_tgt  ON graph_edges(target_id);

CREATE TABLE IF NOT EXISTS profile (
    repo_id    TEXT PRIMARY KEY,
    facts      TEXT NOT NULL DEFAULT '[]',
    preferences TEXT NOT NULL DEFAULT '[]',
    summary    TEXT,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS reflections (
    id         TEXT PRIMARY KEY,
    repo_id    TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at REAL NOT NULL,
    hash       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_refl_repo ON reflections(repo_id);

CREATE TABLE IF NOT EXISTS review_schedule (
    id             TEXT PRIMARY KEY,
    memory_id      TEXT NOT NULL,
    repo_id        TEXT NOT NULL,
    box            INTEGER NOT NULL DEFAULT 0,
    next_review_at REAL NOT NULL,
    last_review_at REAL,
    ease           REAL NOT NULL DEFAULT 2.5
);
CREATE INDEX IF NOT EXISTS idx_review_due ON review_schedule(repo_id, next_review_at);

CREATE TABLE IF NOT EXISTS audit_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id      TEXT NOT NULL,
    action       TEXT NOT NULL,
    entity_id    TEXT,
    payload_hash TEXT,
    created_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_repo ON audit_log(repo_id);
"""


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def now() -> float:
    return time.time()


class MemoryStore:
    """按仓库隔离的 SQLite 存储，含反篡改校验与审计日志。"""

    def __init__(self, base_dir: str, db_name: str = "memory.db",
                 privileged_token: Optional[str] = None,
                 write_protection: bool = True,
                 append_only: bool = True):
        self.base_dir = os.path.abspath(base_dir)
        self.db_name = db_name
        self.privileged_token = privileged_token
        self.write_protection = write_protection
        self.append_only = append_only
        self._lock = threading.RLock()
        self._conns: Dict[str, sqlite3.Connection] = {}
        os.makedirs(self.base_dir, exist_ok=True)

    # ------------------------------------------------------------------ 连接
    def _db_path(self, repo_id: str) -> str:
        return os.path.join(self.base_dir, repo_id, self.db_name)

    def _connect(self, repo_id: str) -> sqlite3.Connection:
        with self._lock:
            if repo_id in self._conns:
                return self._conns[repo_id]
            path = self._db_path(repo_id)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            conn = sqlite3.connect(path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
            conn.commit()
            self._conns[repo_id] = conn
            return conn

    def close(self) -> None:
        with self._lock:
            for c in self._conns.values():
                c.close()
            self._conns.clear()

    # ------------------------------------------------------------- 权限控制
    def check_privilege(self, token: Optional[str]) -> bool:
        """校验高权限写入口令。未启用写保护时始终放行。"""
        if not self.write_protection:
            return True
        if not self.privileged_token:
            return True
        return bool(token) and token == self.privileged_token

    def _audit(self, conn: sqlite3.Connection, repo_id: str, action: str,
               entity_id: Optional[str], payload: Optional[str]) -> None:
        conn.execute(
            "INSERT INTO audit_log(repo_id, action, entity_id, payload_hash, created_at)"
            " VALUES(?,?,?,?,?)",
            (repo_id, action, entity_id, sha256(payload) if payload else None, now()),
        )

    # --------------------------------------------------------------- 记忆
    def add_memory(self, repo_id: str, content: str, kind: str = "episodic",
                   importance: float = 0.5, tags: Optional[list] = None,
                   source: Optional[str] = None, embedding: Optional[bytes] = None,
                   token: Optional[str] = None) -> str:
        conn = self._connect(repo_id)
        mid = uuid.uuid4().hex
        ts = now()
        content_h = sha256(content)
        with self._lock:
            conn.execute(
                "INSERT INTO memories(id, repo_id, content, kind, importance, tags,"
                " source, embedding, created_at, updated_at, hash, status)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,'active')",
                (mid, repo_id, content, kind, importance,
                 json.dumps(tags or [], ensure_ascii=False), source,
                 embedding, ts, ts, content_h),
            )
            self._audit(conn, repo_id, "add_memory", mid, content)
            conn.commit()
        return mid

    def get_memory(self, repo_id: str, mid: str) -> Optional[Dict[str, Any]]:
        conn = self._connect(repo_id)
        row = conn.execute("SELECT * FROM memories WHERE id=? AND repo_id=?",
                           (mid, repo_id)).fetchone()
        return dict(row) if row else None

    def list_memories(self, repo_id: str, status: str = "active",
                      limit: int = 1000) -> List[Dict[str, Any]]:
        conn = self._connect(repo_id)
        rows = conn.execute(
            "SELECT * FROM memories WHERE repo_id=? AND status=? ORDER BY created_at DESC LIMIT ?",
            (repo_id, status, limit)).fetchall()
        return [dict(r) for r in rows]

    def mark_recalled(self, repo_id: str, mid: str) -> None:
        conn = self._connect(repo_id)
        with self._lock:
            conn.execute(
                "UPDATE memories SET last_recalled_at=?, recall_count=recall_count+1 WHERE id=?",
                (now(), mid))
            conn.commit()

    def archive_memory(self, repo_id: str, mid: str) -> None:
        conn = self._connect(repo_id)
        with self._lock:
            conn.execute("UPDATE memories SET status='archived' WHERE id=?", (mid,))
            self._audit(conn, repo_id, "archive_memory", mid, None)
            conn.commit()

    # ------------------------------------------------------------- 知识页
    def save_knowledge_page(self, repo_id: str, title: str, content: str,
                            summary: Optional[str] = None, tags: Optional[list] = None,
                            importance: float = 0.5) -> str:
        conn = self._connect(repo_id)
        pid = uuid.uuid4().hex
        ts = now()
        h = sha256(title + "\n" + content)
        with self._lock:
            conn.execute(
                "INSERT INTO knowledge_pages(id, repo_id, title, content, summary,"
                " tags, importance, created_at, updated_at, hash)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                (pid, repo_id, title, content, summary,
                 json.dumps(tags or [], ensure_ascii=False), importance, ts, ts, h))
            self._audit(conn, repo_id, "save_knowledge_page", pid, title)
            conn.commit()
        return pid

    def list_knowledge_pages(self, repo_id: str) -> List[Dict[str, Any]]:
        conn = self._connect(repo_id)
        rows = conn.execute(
            "SELECT * FROM knowledge_pages WHERE repo_id=? ORDER BY updated_at DESC",
            (repo_id,)).fetchall()
        return [dict(r) for r in rows]

    # --------------------------------------------------------------- 图谱
    def upsert_node(self, repo_id: str, label: str, node_type: str = "concept",
                    weight: float = 1.0, metadata: Optional[dict] = None) -> str:
        conn = self._connect(repo_id)
        key = sha256(repo_id + "\x00" + label.lower())
        nid = key[:16]
        with self._lock:
            conn.execute(
                "INSERT INTO graph_nodes(id, repo_id, label, node_type, weight, metadata, created_at)"
                " VALUES(?,?,?,?,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET weight=weight+excluded.weight,"
                " metadata=excluded.metadata",
                (nid, repo_id, label, node_type, weight,
                 json.dumps(metadata or {}, ensure_ascii=False), now()))
            conn.commit()
        return nid

    def add_edge(self, repo_id: str, source_id: str, target_id: str,
                 relation: str = "related_to", weight: float = 1.0) -> str:
        conn = self._connect(repo_id)
        key = sha256(source_id + target_id + relation)
        eid = key[:16]
        with self._lock:
            conn.execute(
                "INSERT INTO graph_edges(id, repo_id, source_id, target_id, relation, weight, created_at)"
                " VALUES(?,?,?,?,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET weight=weight+excluded.weight",
                (eid, repo_id, source_id, target_id, relation, weight, now()))
            conn.commit()
        return eid

    def link_memory_tags(self, repo_id: str, memory_id: str,
                         tags: Optional[list] = None) -> None:
        """把记忆与它的标签节点建立 has_tag 边，供图谱召回使用。"""
        for t in tags or []:
            nid = self.upsert_node(repo_id, t, node_type="tag")
            self.add_edge(repo_id, memory_id, nid, relation="has_tag")

    def _tag_nodes_of_memory(self, repo_id: str, memory_id: str) -> List[str]:
        conn = self._connect(repo_id)
        rows = conn.execute(
            "SELECT target_id FROM graph_edges WHERE repo_id=? AND source_id=? AND relation='has_tag'",
            (repo_id, memory_id)).fetchall()
        return [r["target_id"] for r in rows]

    def related_memories(self, repo_id: str, memory_id: str,
                         depth: int = 2) -> List[Dict[str, Any]]:
        """返回与某记忆共享标签节点的其它记忆（带最短距离）。

        第一跳：共享同一标签；第二跳起：标签节点之间的其它边。
        """
        conn = self._connect(repo_id)
        result: List[Dict[str, Any]] = []
        visited_mem: set = {memory_id}
        visited_node: set = set()
        frontier_nodes: List[tuple] = [
            (nid, 1) for nid in self._tag_nodes_of_memory(repo_id, memory_id)
        ]

        while frontier_nodes and depth >= 1:
            next_frontier: List[tuple] = []
            for nid, dist in frontier_nodes:
                if nid in visited_node:
                    continue
                visited_node.add(nid)
                # 共享该节点的其它记忆（距离 = dist）
                mem_rows = conn.execute(
                    "SELECT source_id FROM graph_edges WHERE repo_id=? AND target_id=? AND relation='has_tag'",
                    (repo_id, nid)).fetchall()
                for r in mem_rows:
                    other = r["source_id"]
                    if other in visited_mem or other == memory_id:
                        continue
                    visited_mem.add(other)
                    mem = self.get_memory(repo_id, other)
                    if mem:
                        result.append({"memory": mem, "distance": dist})
                    # 记忆又可继续外扩（距离 +1）
                    if dist < depth:
                        for sub_nid in self._tag_nodes_of_memory(repo_id, other):
                            next_frontier.append((sub_nid, dist + 1))
            frontier_nodes = next_frontier
        return result

    def neighbors(self, repo_id: str, node_id: str,
                  depth: int = 2) -> List[Dict[str, Any]]:
        """沿图谱做广度扩展，返回 (node, relation, weight, distance) 列表。"""
        conn = self._connect(repo_id)
        seen: Dict[str, int] = {node_id: 0}
        frontier = [node_id]
        result: List[Dict[str, Any]] = []
        for d in range(depth):
            nxt: List[str] = []
            for n in frontier:
                rows = conn.execute(
                    "SELECT source_id, target_id, relation, weight FROM graph_edges"
                    " WHERE repo_id=? AND (source_id=? OR target_id=?)",
                    (repo_id, n, n)).fetchall()
                for r in rows:
                    other = r["target_id"] if r["source_id"] == n else r["source_id"]
                    if other in seen:
                        continue
                    seen[other] = d + 1
                    nxt.append(other)
                    result.append({
                        "node_id": other,
                        "relation": r["relation"],
                        "weight": r["weight"],
                        "distance": d + 1,
                    })
            frontier = nxt
            if not frontier:
                break
        return result

    # --------------------------------------------------------------- 画像
    def get_profile(self, repo_id: str) -> Dict[str, Any]:
        conn = self._connect(repo_id)
        row = conn.execute("SELECT * FROM profile WHERE repo_id=?", (repo_id,)).fetchone()
        if not row:
            return {"facts": [], "preferences": [], "summary": None}
        d = dict(row)
        return {
            "facts": json.loads(d["facts"]),
            "preferences": json.loads(d["preferences"]),
            "summary": d["summary"],
        }

    def set_profile(self, repo_id: str, facts: Optional[list] = None,
                    preferences: Optional[list] = None,
                    summary: Optional[str] = None) -> None:
        conn = self._connect(repo_id)
        cur = self.get_profile(repo_id)
        new_facts = facts if facts is not None else cur["facts"]
        new_prefs = preferences if preferences is not None else cur["preferences"]
        new_summary = summary if summary is not None else cur["summary"]
        with self._lock:
            conn.execute(
                "INSERT INTO profile(repo_id, facts, preferences, summary, updated_at)"
                " VALUES(?,?,?,?,?)"
                " ON CONFLICT(repo_id) DO UPDATE SET facts=excluded.facts,"
                " preferences=excluded.preferences, summary=excluded.summary,"
                " updated_at=excluded.updated_at",
                (repo_id, json.dumps(new_facts, ensure_ascii=False),
                 json.dumps(new_prefs, ensure_ascii=False), new_summary, now()))
            self._audit(conn, repo_id, "set_profile", repo_id, new_summary)
            conn.commit()

    # --------------------------------------------------------------- 反思
    def add_reflection(self, repo_id: str, content: str) -> str:
        conn = self._connect(repo_id)
        rid = uuid.uuid4().hex
        with self._lock:
            conn.execute(
                "INSERT INTO reflections(id, repo_id, content, created_at, hash)"
                " VALUES(?,?,?,?,?)",
                (rid, repo_id, content, now(), sha256(content)))
            self._audit(conn, repo_id, "add_reflection", rid, content)
            conn.commit()
        return rid

    # ----------------------------------------------------------- 复习计划
    def schedule_review(self, repo_id: str, memory_id: str, box: int,
                        next_review_at: float, ease: float = 2.5) -> str:
        conn = self._connect(repo_id)
        rid = uuid.uuid4().hex
        with self._lock:
            conn.execute(
                "INSERT INTO review_schedule(id, memory_id, repo_id, box,"
                " next_review_at, ease) VALUES(?,?,?,?,?,?)",
                (rid, memory_id, repo_id, box, next_review_at, ease))
            conn.commit()
        return rid

    def due_reviews(self, repo_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        conn = self._connect(repo_id)
        rows = conn.execute(
            "SELECT * FROM review_schedule WHERE repo_id=? AND next_review_at<=?"
            " ORDER BY next_review_at ASC LIMIT ?",
            (repo_id, now(), limit)).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------- 完整性
    def verify_integrity(self, repo_id: str) -> Dict[str, Any]:
        """校验所有记忆 / 知识页 / 反思的 SHA256 哈希，返回篡改清单。"""
        conn = self._connect(repo_id)
        tampered: List[str] = []
        for mid, content, h in conn.execute(
                "SELECT id, content, hash FROM memories WHERE repo_id=?", (repo_id,)):
            if sha256(content) != h:
                tampered.append(mid)
        for pid, title, content, h in conn.execute(
                "SELECT id, title, content, hash FROM knowledge_pages WHERE repo_id=?", (repo_id,)):
            if sha256(title + "\n" + content) != h:
                tampered.append(pid)
        for rid, content, h in conn.execute(
                "SELECT id, content, hash FROM reflections WHERE repo_id=?", (repo_id,)):
            if sha256(content) != h:
                tampered.append(rid)
        return {"ok": not tampered, "tampered": tampered}

    def audit_trail(self, repo_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        conn = self._connect(repo_id)
        rows = conn.execute(
            "SELECT * FROM audit_log WHERE repo_id=? ORDER BY id DESC LIMIT ?",
            (repo_id, limit)).fetchall()
        return [dict(r) for r in rows]

    def count_memories(self, repo_id: str, status: str = "active") -> int:
        conn = self._connect(repo_id)
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM memories WHERE repo_id=? AND status=?",
            (repo_id, status)).fetchone()
        return int(row["c"]) if row else 0
