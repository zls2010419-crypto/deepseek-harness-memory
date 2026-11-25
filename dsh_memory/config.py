"""配置加载与最小 YAML 解析器。

优先使用 PyYAML；若未安装则回退到内置的最小 YAML 解析器，
足以处理本插件 config.yaml / persona.yaml 的嵌套结构。
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict


def _parse_scalar(text: str) -> Any:
    """把 YAML 标量字符串解析为 Python 基础类型。"""
    text = text.strip()
    if text == "":
        return ""
    if text.lower() in ("true", "yes", "on"):
        return True
    if text.lower() in ("false", "no", "off"):
        return False
    if text.lower() in ("null", "none", "~"):
        return None
    # 行内列表 [a, b, c]
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if inner == "":
            return []
        return [_parse_scalar(x) for x in _split_inline(inner)]
    # 引号字符串
    if len(text) >= 2 and text[0] in "\"'" and text[-1] == text[0]:
        return text[1:-1]
    # 整数
    if re.fullmatch(r"[-+]?\d+", text):
        return int(text)
    # 浮点数
    if re.fullmatch(r"[-+]?\d*\.\d+", text):
        return float(text)
    return text


def _split_inline(inner: str) -> list[str]:
    """按逗号拆分行内列表（忽略引号内逗号）。"""
    parts, buf, quote = [], "", None
    for ch in inner:
        if quote:
            buf += ch
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            buf += ch
        elif ch == ",":
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    if buf.strip():
        parts.append(buf)
    return parts


def _strip_comment(line: str) -> str:
    """剥离行内注释（忽略引号内的 #）。"""
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            return line[:i]
    return line


def _load_yaml_mini(text: str) -> Dict[str, Any]:
    """解析缩进式 YAML 子集：嵌套映射、行内列表、块列表（标量项）。"""
    root: Dict[str, Any] = {}
    # 每个栈帧：{indent, container, parent, key, is_list}
    # 空值 key 会推入一个「待定型」帧，遇块列表项时把 parent[key] 从 dict 换成 list。
    stack: list[dict] = [{
        "indent": -1, "container": root, "parent": None,
        "key": None, "is_list": False,
    }]

    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        raw = _strip_comment(raw)
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()

        # 弹掉比当前行更深/同级的栈帧
        while len(stack) > 1 and stack[-1]["indent"] >= indent:
            stack.pop()
        frame = stack[-1]

        if line.startswith("- "):  # 块列表项
            item = _parse_scalar(line[2:].strip())
            if not frame["is_list"]:
                lst: list = []
                frame["parent"][frame["key"]] = lst
                frame["container"] = lst
                frame["is_list"] = True
            frame["container"].append(item)
            continue

        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip().strip("\"'")
        val = val.strip()
        if val == "":
            child: Dict[str, Any] = {}
            frame["container"][key] = child
            stack.append({
                "indent": indent, "container": child, "parent": frame["container"],
                "key": key, "is_list": False,
            })
        else:
            frame["container"][key] = _parse_scalar(val)
    return root


def load_yaml(path: str) -> Dict[str, Any]:
    """加载 YAML 文件，优先 PyYAML，回退内置解析器。"""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text)
        return data or {}
    except Exception:
        return _load_yaml_mini(text)


class Config:
    """配置访问器：点路径取值（如 cfg.get("recall.top_k")）。"""

    def __init__(self, data: Dict[str, Any]):
        self._data = data or {}

    @classmethod
    def load(cls, project_root: str) -> "Config":
        path = os.path.join(project_root, "config", "config.yaml")
        data = load_yaml(path) if os.path.exists(path) else {}
        return cls(data)

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in dotted.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return default
        return node

    def section(self, name: str) -> Dict[str, Any]:
        v = self._data.get(name, {})
        return v if isinstance(v, dict) else {}
