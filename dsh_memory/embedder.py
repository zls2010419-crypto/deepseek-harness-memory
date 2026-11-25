"""向量嵌入：对接 OpenVINO 服务端 + 本地运行时，哈希嵌入兜底。

策略：
1. ``provider=openvino`` 且配置了 server_url → 调用 OpenVINO Model Server (OVMS)
   的 REST 推理接口 ``/v2/models/{model}/infer`` 取文本向量。
2. 若配置了本地 IR ``model_path`` → 用 openvino 运行时加载推理。
3. 上述均不可用（未安装 openvino / 服务不可达）→ 回退到确定性哈希嵌入，
   保证插件在无 GPU / 无服务环境下依然可跑通（用于语义召回演示）。
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import List, Optional


def _tokenize(text: str) -> List[str]:
    """轻量分词：CJK 单字 + 二元组，ASCII 小写词。"""
    text = text.lower()
    tokens: List[str] = []
    # ASCII 词
    for w in re.findall(r"[a-z0-9_]+", text):
        tokens.append(w)
    # CJK 连续段
    for seg in re.findall(r"[\u4e00-\u9fff]+", text):
        chars = list(seg)
        tokens.extend(chars)
        tokens.extend(seg[i:i + 2] for i in range(len(chars) - 1))
    return tokens


class HashEmbedder:
    """确定性哈希嵌入：把 token 映射到 signed 单位向量。

    基于 feature hashing，相同文本得到相同向量，可用于余弦相似度近似语义召回。
    """

    def __init__(self, dim: int = 1024):
        self.dim = dim

    def embed(self, text: str) -> List[float]:
        vec = [0.0] * self.dim
        for tok in _tokenize(text):
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
            idx = h % self.dim
            sign = 1.0 if (h >> 8) & 1 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    def embed_bytes(self, text: str) -> bytes:
        import struct
        vec = self.embed(text)
        return struct.pack(f"<{len(vec)}d", *vec)


class OpenVINOEmbedder:
    """OpenVINO 服务端 / 本地运行时嵌入。

    - 服务端：POST {server_url}/v2/models/{model}/infer，输入 key 默认为 "input_ids"。
    - 本地：加载 OpenVINO IR 模型（含 tokenizer 可选，需自行分词）。
    """

    def __init__(self, server_url: Optional[str] = None, model_name: str = "bge-m3",
                 model_path: Optional[str] = None, dim: int = 1024, timeout: int = 5):
        self.server_url = server_url
        self.model_name = model_name
        self.model_path = model_path
        self.dim = dim
        self.timeout = timeout
        self._local = None

    def _embed_server(self, text: str) -> List[float]:
        import json
        import urllib.request

        payload = json.dumps({"inputs": [{"name": "input", "shape": [1, 1],
                                          "datatype": "BYTES",
                                          "data": [text]}]})
        req = urllib.request.Request(
            f"{self.server_url.rstrip('/')}/v2/models/{self.model_name}/infer",
            data=payload.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        # 取第一个输出张量的数据，做均值池化得到句子向量
        outputs = data.get("outputs", [])
        if not outputs:
            raise RuntimeError("OVMS 返回无输出")
        arr = outputs[0].get("data", [])
        return _mean_pool(arr, self.dim)

    def _embed_local(self, text: str) -> List[float]:
        if self._local is None:
            from openvino import Core  # type: ignore
            core = Core()
            self._local = core.compile_model(self.model_path, "CPU")
        # 注意：此处为简化实现，实际需按模型输入签名处理 token 化。
        # 服务端路径为推荐用法；本地路径留给接入方扩展。
        raise NotImplementedError("本地 IR 推理需按模型签名实现，推荐使用服务端或哈希回退")

    def embed(self, text: str) -> List[float]:
        try:
            if self.server_url:
                return self._embed_server(text)
            if self.model_path:
                return self._embed_local(text)
            raise RuntimeError("未配置 OpenVINO 服务端或本地模型")
        except Exception:
            raise


def _mean_pool(arr: List[float], dim: int) -> List[float]:
    n = len(arr) // dim if arr and dim else 0
    if n <= 1:
        return arr[:dim] if len(arr) >= dim else arr
    pooled = [0.0] * dim
    for i in range(n):
        for d in range(dim):
            pooled[d] += arr[i * dim + d]
    norm = math.sqrt(sum(x * x for x in pooled)) or 1.0
    return [x / norm for x in pooled]


def cosine(a: List[float], b: List[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    dot = sum(a[i] * b[i] for i in range(n))
    return float(dot)  # 向量已归一化时点积即余弦


def make_embedder(cfg) -> object:
    """按配置构造嵌入器；OpenVINO 不可用时自动回退哈希嵌入。"""
    provider = cfg.get("embedding.provider", "hash")
    dim = int(cfg.get("embedding.dimension", 1024))
    if provider == "openvino":
        emb = OpenVINOEmbedder(
            server_url=cfg.get("embedding.server_url"),
            model_name=cfg.get("embedding.model_name", "bge-m3"),
            model_path=cfg.get("embedding.model_path") or None,
            dim=dim,
            timeout=int(cfg.get("embedding.timeout", 5)),
        )
        # 探测一次，失败则回退
        try:
            emb.embed("健康检查")
            return emb
        except Exception:
            pass
    return HashEmbedder(dim=dim)


def embed_to_bytes(embedder, text: str) -> bytes:
    """把文本嵌入为 float64 字节序列，供 SQLite BLOB 存储。"""
    if hasattr(embedder, "embed_bytes"):
        return embedder.embed_bytes(text)
    import struct
    vec = embedder.embed(text)
    return struct.pack(f"<{len(vec)}d", *vec)


def bytes_to_vec(blob: bytes) -> List[float]:
    import struct
    n = len(blob) // 8
    return list(struct.unpack(f"<{n}d", blob))
