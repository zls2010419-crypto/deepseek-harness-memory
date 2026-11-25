"""DeepSeek Harness 长期记忆插件。

一个面向 DeepSeek Harness Agent 的可插拔长期记忆系统，核心能力：

- 长期记忆存储（按仓库隔离）
- 自动召回（向量 + 关键词 + 图谱扩展）
- 知识页保存
- 深度反思（空闲窗口自动整理）
- 记忆图谱
- 用户画像注入
- 艾宾浩斯遗忘曲线（间隔复习）
- 高权限写入 / 反篡改控制
- 缓存友好注入（每条消息关键命中）
- OpenVINO 服务端向量化对接
- 人格文件

用法示例::

    from dsh_memory import MemoryPlugin

    mem = MemoryPlugin(project_root=".")
    mem.save_memory("用户偏好深色主题", kind="semantic", repo_id="my-repo")
    ctx = mem.recall_and_inject("帮我改一下主题", repo_id="my-repo")
"""

from .plugin import MemoryPlugin

__all__ = ["MemoryPlugin"]
__version__ = "1.0.0"
