"""插件主入口：把各模块编排为一个统一、可插拔的记忆插件。

对外 API 覆盖 DeepSeek Harness Agent 的典型接入点：

- 写入：save_memory / save_knowledge_page / add_fact / add_preference
- 召回：recall / recall_and_inject（每条消息关键命中 → 注入）
- 反思与整理：reflect / consolidate / start_background（空闲窗口自动整理）
- 权限与完整性：verify_integrity / audit_trail（高权限写入 + 反篡改）
- 图谱与画像：graph / profile

用法::

    from dsh_memory import MemoryPlugin

    mem = MemoryPlugin(project_root=".")
    mem.save_memory("用户偏好深色主题", kind="semantic", tags=["偏好"], repo_id="my-repo")
    ctx = mem.recall_and_inject("帮我改成深色", repo_id="my-repo")
    print(ctx["system_prompt"])
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from .config import Config
from .consolidation import Consolidator
from .embedder import make_embedder, embed_to_bytes
from .graph import MemoryGraph
from .injection import InjectionBuilder
from .personality import Persona
from .profile import UserProfile
from .recall import RecallEngine, extract_key_hits
from .reflection import Reflector
from .store import MemoryStore


class MemoryPlugin:
    def __init__(self, project_root: str = ".", config: Optional[Config] = None,
                 llm_summarize: Optional[callable] = None):
        self.project_root = os.path.abspath(project_root)
        self.cfg = config or Config.load(self.project_root)

        base_dir = self.cfg.get("storage.base_dir", "./data")
        if not os.path.isabs(base_dir):
            base_dir = os.path.join(self.project_root, base_dir)

        self.store = MemoryStore(
            base_dir=base_dir,
            db_name=self.cfg.get("storage.db_name", "memory.db"),
            privileged_token=self._privileged_token(),
            write_protection=self.cfg.get("permissions.write_protection", True),
            append_only=self.cfg.get("permissions.append_only", True),
        )
        self.embedder = make_embedder(self.cfg)
        self.graph = MemoryGraph(self.store)
        self.profile = UserProfile(self.store)
        self.recall_engine = RecallEngine(self.store, self.embedder, self.cfg)
        self.reflector = Reflector(self.store, profile=self.profile, cfg=self.cfg)
        self.reflector.llm_summarize = llm_summarize

        persona = Persona(self.project_root,
                          self.cfg.get("personality.file", "persona/persona.yaml"))
        self.persona_text = persona.render() if self.cfg.get("personality.inject", True) else ""
        self.injection = InjectionBuilder(self.cfg, self.persona_text)

        self.consolidator = Consolidator(self.store, self.reflector, self.cfg,
                                         profile=self.profile)

    def _privileged_token(self) -> Optional[str]:
        tok = self.cfg.get("permissions.privileged_token")
        return os.environ.get("DSH_MEMORY_TOKEN", tok) or None

    # --------------------------------------------------------------- 写入
    def save_memory(self, content: str, repo_id: str = "default",
                    kind: str = "episodic", importance: float = 0.5,
                    tags: Optional[list] = None, source: Optional[str] = None,
                    token: Optional[str] = None) -> str:
        """保存一条记忆；``token`` 用于高权限写入校验。"""
        emb = embed_to_bytes(self.embedder, content)
        mid = self.store.add_memory(repo_id, content, kind=kind,
                                    importance=importance, tags=tags,
                                    source=source, embedding=emb, token=token)
        self.store.link_memory_tags(repo_id, mid, tags)
        self.consolidator.touch()
        return mid

    def save_knowledge_page(self, title: str, content: str, repo_id: str = "default",
                            summary: Optional[str] = None, tags: Optional[list] = None,
                            importance: float = 0.5) -> str:
        pid = self.store.save_knowledge_page(repo_id, title, content,
                                             summary=summary, tags=tags,
                                             importance=importance)
        self.consolidator.touch()
        return pid

    def add_fact(self, fact: str, repo_id: str = "default") -> None:
        self.profile.add_fact(repo_id, fact)
        self.profile.rebuild_summary(repo_id)

    def add_preference(self, pref: str, repo_id: str = "default") -> None:
        self.profile.add_preference(repo_id, pref)
        self.profile.rebuild_summary(repo_id)

    # --------------------------------------------------------------- 召回
    def recall(self, message: str, repo_id: str = "default",
               top_k: Optional[int] = None) -> List[Dict[str, Any]]:
        result = self.recall_engine.recall(repo_id, message, top_k=top_k)
        for item in result:
            self.store.mark_recalled(repo_id, item["memory"]["id"])
        return result

    def recall_and_inject(self, message: str, repo_id: str = "default",
                          top_k: Optional[int] = None) -> Dict[str, Any]:
        """一条消息的完整处理：召回关键命中 → 注入系统提示。"""
        self.consolidator.touch()
        result = self.recall(message, repo_id, top_k=top_k)
        key_hits = extract_key_hits(result)
        profile_text = self.profile.render(repo_id)
        ctx = self.injection.build(repo_id, message, key_hits, profile_text)
        ctx["hits"] = key_hits
        ctx["recalled"] = result
        return ctx

    # ----------------------------------------------------------- 反思与整理
    def reflect(self, repo_id: str = "default") -> str:
        return self.reflector.reflect(repo_id)

    def consolidate(self, repo_id: str = "default") -> Dict[str, Any]:
        return self.consolidator.consolidate(repo_id)

    def start_background(self) -> None:
        self.consolidator.start()

    def stop_background(self) -> None:
        self.consolidator.stop()

    # ----------------------------------------------------------- 权限与完整性
    def verify_integrity(self, repo_id: str = "default") -> Dict[str, Any]:
        return self.store.verify_integrity(repo_id)

    def audit_trail(self, repo_id: str = "default", limit: int = 50) -> List[Dict[str, Any]]:
        return self.store.audit_trail(repo_id, limit)

    # --------------------------------------------------------------- 统计
    def stats(self, repo_id: str = "default") -> Dict[str, Any]:
        return {
            "memories": self.store.count_memories(repo_id),
            "knowledge_pages": len(self.store.list_knowledge_pages(repo_id)),
            "graph": self.graph.stats(repo_id),
            "integrity": self.store.verify_integrity(repo_id),
        }

    def close(self) -> None:
        self.consolidator.stop()
        self.store.close()
