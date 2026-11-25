"""空闲窗口自动整理：后台线程在空闲时触发深度反思 + 合并 + 修剪 + 画像更新。

- 空闲 ``idle_seconds`` 无新消息即触发一轮整理。
- 深度反思：把近期记忆提炼为高层结论。
- 修剪：归档低重要度且久未命中的记忆。
- 画像：把偏好/事实记忆蒸馏进用户画像。
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from .reflection import Reflector
from .store import MemoryStore


class Consolidator:
    def __init__(self, store: MemoryStore, reflector: Reflector, cfg,
                 profile=None):
        self.store = store
        self.reflector = reflector
        self.profile = profile
        self.cfg = cfg
        self.idle_seconds = float(cfg.get("consolidation.idle_seconds", 60))
        self._last_activity = time.time()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def touch(self) -> None:
        """外部在每条消息处理时调用，刷新活动时间戳。"""
        self._last_activity = time.time()

    def start(self) -> None:
        if not self.cfg.get("consolidation.enabled", True):
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(self.idle_seconds)
            if self._stop.is_set():
                break
            idle = time.time() - self._last_activity
            if idle >= self.idle_seconds:
                try:
                    self.consolidate_all()
                except Exception:
                    pass
                self._last_activity = time.time()

    def consolidate_all(self) -> Dict[str, Any]:
        """对所有已知仓库执行一轮整理。"""
        from .store import sha256  # noqa
        results: Dict[str, Any] = {}
        repos = self._list_repos()
        for repo_id in repos:
            results[repo_id] = self.consolidate(repo_id)
        return results

    def _list_repos(self) -> List[str]:
        import os
        base = self.store.base_dir
        if not os.path.isdir(base):
            return []
        return [d for d in os.listdir(base)
                if os.path.isdir(os.path.join(base, d))]

    def consolidate(self, repo_id: str) -> Dict[str, Any]:
        report: Dict[str, Any] = {"reflection": "", "pruned": 0, "profile_updates": 0}

        recent = self.store.list_memories(repo_id, limit=200)
        min_recent = int(self.cfg.get("consolidation.min_recent_for_reflection", 5))
        if len(recent) >= min_recent:
            report["reflection"] = self.reflector.reflect(repo_id, recent)

        if self.profile is not None:
            report["profile_updates"] = self.reflector.distill_to_profile(repo_id)

        report["pruned"] = self._prune(repo_id)
        return report

    def _prune(self, repo_id: str) -> int:
        """归档低重要度且久未命中的记忆，控制记忆总量。"""
        threshold = float(self.cfg.get("consolidation.prune_below_importance", 0.05))
        max_mem = int(self.cfg.get("consolidation.max_memories_per_repo", 5000))
        now_ts = time.time()
        pruned = 0
        for m in self.store.list_memories(repo_id):
            imp = float(m.get("importance") or 0.5)
            last_recall = m.get("last_recalled_at")
            recalled = last_recall is not None
            # 低重要度 + 从未被召回 + 已存在超 7 天 → 归档
            if imp < threshold and not recalled:
                age = now_ts - float(m.get("created_at") or now_ts)
                if age > 7 * 86400:
                    self.store.archive_memory(repo_id, m["id"])
                    pruned += 1
        # 超出上限时按重要度从低到高归档
        active = self.store.count_memories(repo_id)
        if active > max_mem:
            all_mem = sorted(self.store.list_memories(repo_id),
                             key=lambda x: float(x.get("importance") or 0.5))
            for m in all_mem[: active - max_mem]:
                self.store.archive_memory(repo_id, m["id"])
                pruned += 1
        return pruned
