"""端到端演示：从零跑通记忆插件的核心链路。

运行方式（在项目根目录）：:

    python demo.py
"""
from __future__ import annotations

import json

from dsh_memory import MemoryPlugin


def hr(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def main() -> None:
    mem = MemoryPlugin(project_root=".", config=None)

    # 1. 写入记忆（带标签，自动建立图谱）
    hr("1. 写入记忆")
    mem.save_memory("用户偏好深色主题", repo_id="demo", kind="semantic",
                    importance=0.9, tags=["偏好", "主题"])
    mem.save_memory("项目使用 FastAPI 作为后端框架", repo_id="demo",
                    kind="semantic", importance=0.8, tags=["技术栈", "FastAPI"])
    mem.save_memory("用户是前端工程师，常用 React", repo_id="demo",
                    kind="semantic", importance=0.85, tags=["身份", "React"])
    mem.save_memory("上周讨论了登录模块的鉴权方案", repo_id="demo",
                    kind="episodic", importance=0.6, tags=["会议"])
    print("已写入 4 条记忆")

    # 2. 知识页
    hr("2. 保存知识页")
    mem.save_knowledge_page(
        "项目架构", "后端 FastAPI + 前端 React，数据层 PostgreSQL",
        repo_id="demo", summary="三层架构", tags=["架构"],
    )
    print("知识页已保存")

    # 3. 用户画像
    hr("3. 用户画像")
    mem.add_fact("前端工程师", repo_id="demo")
    mem.add_preference("代码风格偏简洁", repo_id="demo")
    print("画像摘要:", mem.profile.render("demo"))

    # 4. 自动召回 + 缓存友好注入
    hr("4. 自动召回与缓存友好注入")
    ctx = mem.recall_and_inject("帮我推荐一个前端框架", repo_id="demo")
    print("--- 关键命中 ---")
    for h in ctx["hits"]:
        print("  *", h)
    print("\n--- 注入的系统提示 ---")
    print(ctx["system_prompt"])

    # 5. 深度反思 + 空闲整理
    hr("5. 深度反思与空闲整理")
    report = mem.consolidate("demo")
    print("反思内容:")
    print(report.get("reflection") or "(无)")

    # 6. 记忆图谱
    hr("6. 记忆图谱统计")
    print(json.dumps(mem.graph.stats("demo"), ensure_ascii=False, indent=2))

    # 7. 反篡改校验 + 审计日志
    hr("7. 反篡改校验与审计日志")
    print("完整性校验:", mem.verify_integrity("demo"))
    print("\n最近审计记录:")
    for row in mem.audit_trail("demo", limit=5):
        print("  ", row["action"], row["entity_id"], f"(hash={row['payload_hash'][:12]}...)")

    # 8. 按仓库隔离演示
    hr("8. 仓库隔离")
    mem.save_memory("另一个仓库的记忆", repo_id="other-repo", tags=["隔离"])
    r1 = mem.recall("前端框架", repo_id="demo")
    r2 = mem.recall("另一个仓库", repo_id="other-repo")
    print("demo 仓库召回", len(r1), "条；other-repo 召回", len(r2), "条（互不串扰）")

    print("\n全部链路跑通 ✓")


if __name__ == "__main__":
    main()
