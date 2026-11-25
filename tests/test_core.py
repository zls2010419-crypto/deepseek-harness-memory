"""核心冒烟测试（纯标准库，无需额外依赖）。"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dsh_memory.forgetting import ForgettingCurve
from dsh_memory.store import MemoryStore, sha256


class ForgettingCurveTest(unittest.TestCase):
    def _cfg(self):
        class C:
            def get(self, k, d=None):
                data = {
                    "forgetting.enabled": True,
                    "forgetting.intervals": [1, 2, 4, 7, 15, 30],
                    "forgetting.decay_lambda": 0.10,
                    "forgetting.base_retention": 0.9,
                }
                return data.get(k, d)
        return C()

    def test_retention_decreases(self):
        fc = ForgettingCurve(self._cfg())
        self.assertGreater(fc.retention(0), fc.retention(10))
        self.assertGreater(fc.retention(10, importance=0.9),
                           fc.retention(10, importance=0.1))

    def test_intervals(self):
        fc = ForgettingCurve(self._cfg())
        self.assertEqual(fc.next_interval_days(0), 1)
        self.assertEqual(fc.next_interval_days(100), 30)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = MemoryStore(base_dir=self.tmp, privileged_token="secret")

    def tearDown(self):
        self.store.close()

    def test_repo_isolation(self):
        self.store.add_memory("a", "repo a 记忆")
        self.store.add_memory("b", "repo b 记忆")
        a = [m["content"] for m in self.store.list_memories("a")]
        b = [m["content"] for m in self.store.list_memories("b")]
        self.assertEqual(a, ["repo a 记忆"])
        self.assertEqual(b, ["repo b 记忆"])

    def test_integrity_detects_tamper(self):
        mid = self.store.add_memory("a", "原始内容")
        self.assertTrue(self.store.verify_integrity("a")["ok"])
        # 直接篡改数据库内容，绕过哈希
        conn = self.store._connect("a")
        conn.execute("UPDATE memories SET content='被篡改' WHERE id=?", (mid,))
        conn.commit()
        result = self.store.verify_integrity("a")
        self.assertFalse(result["ok"])
        self.assertIn(mid, result["tampered"])

    def test_audit_log(self):
        self.store.add_memory("a", "某条记忆")
        trail = self.store.audit_trail("a")
        self.assertTrue(any(r["action"] == "add_memory" for r in trail))

    def test_graph_linkage(self):
        mid = self.store.add_memory("a", "偏好深色主题", tags=["偏好"])
        self.store.link_memory_tags("a", mid, ["偏好"])
        mid2 = self.store.add_memory("a", "偏好简洁代码", tags=["偏好"])
        self.store.link_memory_tags("a", mid2, ["偏好"])
        related = self.store.related_memories("a", mid)
        self.assertTrue(any(r["memory"]["id"] == mid2 for r in related))

    def test_privilege(self):
        self.assertTrue(self.store.check_privilege("secret"))
        self.assertFalse(self.store.check_privilege("wrong"))


class HashEmbedderTest(unittest.TestCase):
    def test_cosine_similarity(self):
        from dsh_memory.embedder import HashEmbedder, cosine
        emb = HashEmbedder(dim=256)
        a = emb.embed("深色主题")
        b = emb.embed("深色主题")
        c = emb.embed("完全无关")
        self.assertGreater(cosine(a, b), cosine(a, c))


if __name__ == "__main__":
    unittest.main(verbosity=2)
