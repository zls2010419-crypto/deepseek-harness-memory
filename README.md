# DeepSeek Harness 记忆插件（dsh-memory-plugin）

一个面向 **DeepSeek Harness (dsh)** 的可插拔长期记忆系统，也是可被 `dsh plugin add` 安装的 **DSH bundle**。让 Agent 具备「记、忆、思、理」的能力：记住对话与知识、在恰当时机自动召回、空闲时深度反思与整理、按仓库隔离互不串扰。

> 架构：`index.js`（Cordis 插件入口）通过 stdio 桥接调用 Python 核心 `dsh_memory`（召回 / 图谱 / 画像 / 遗忘曲线 / OpenVINO 向量化均由 Python 实现）。

## 核心能力

| 能力 | 说明 | 对应模块 |
| --- | --- | --- |
| 长期记忆存储 | SQLite 持久化，记忆 / 知识页 / 反思 / 画像分层存储 | `dsh_memory/store.py` |
| 按仓库隔离 | 每个 `repo_id` 独立数据库文件，记忆互不串扰 | `dsh_memory/store.py` |
| 自动召回 | 向量语义 + 关键词 + 图谱扩展三路召回，加权打分 | `dsh_memory/recall.py` |
| 知识页保存 | 结构化保存长知识（标题/正文/摘要/标签） | `dsh_memory/store.py` |
| 深度反思 | 空闲时把近期记忆提炼为高层结论 | `dsh_memory/reflection.py` |
| 记忆图谱 | 概念/标签节点 + 关系边，邻居扩散与中心度统计 | `dsh_memory/graph.py` |
| 用户画像注入 | 沉淀事实与偏好，注入系统提示 | `dsh_memory/profile.py` |
| 艾宾浩斯遗忘曲线 | 指数衰减模型 + 间隔复习 [1,2,4,7,15,30] 天 | `dsh_memory/forgetting.py` |
| 高权限写入 / 反篡改 | SHA256 完整性校验 + 追加式审计日志 + 写入口令 | `dsh_memory/store.py` |
| 缓存友好注入 | 人格 + 画像为稳定前缀，关键命中按稳定顺序放末尾 | `dsh_memory/injection.py` |
| 空闲自动整理 | 后台线程空闲窗口触发反思 + 合并 + 修剪 | `dsh_memory/consolidation.py` |
| OpenVINO 对接 | OpenVINO Model Server / 本地运行时向量化，哈希兜底 | `dsh_memory/embedder.py` |
| 人格文件 | `persona/persona.yaml` 作为稳定人格前缀 | `dsh_memory/personality.py` |

## 目录结构

```
deepseek-harness-memory/
├── package.json                # 声明 dsh.bundle（可安装为 DSH 插件）
├── cordis.patch.yml            # bundle 配置层：insert 插件行
├── index.js                    # Cordis 插件入口 + Python 桥接
├── config/config.yaml          # 插件配置
├── persona/persona.yaml        # 人格文件
├── assets/icon-180.png         # 市场卡片图标（180×180）
├── scripts/gen_icon.py         # 图标生成脚本（纯标准库）
├── dsh_memory/                 # Python 核心
│   ├── plugin.py               # 统一入口
│   ├── cli.py                  # stdio JSON-lines 桥接（供 index.js 调用）
│   ├── store.py                # 存储 + 反篡改
│   ├── embedder.py             # OpenVINO 向量化 + 哈希兜底
│   ├── recall.py               # 自动召回
│   ├── graph.py                # 记忆图谱
│   ├── profile.py              # 用户画像
│   ├── forgetting.py           # 遗忘曲线
│   ├── reflection.py           # 深度反思
│   ├── consolidation.py        # 空闲整理
│   ├── injection.py            # 缓存友好注入
│   ├── personality.py          # 人格文件
│   └── config.py               # 配置加载
├── tests/test_core.py          # 冒烟测试
├── demo.py                     # 端到端演示（Python）
├── requirements.txt
├── pyproject.toml
├── LICENSE                     # MIT
└── .gitignore
```

## 快速开始

```bash
cd deepseek-harness-memory
python demo.py                                # Python 端到端演示
python -m unittest tests.test_core.py -v      # 8 项冒烟测试
npm test                                      # 同等于上面的单测
```

## 作为 DSH 插件安装

本项目是一个标准 DSH bundle（`package.json` 里声明了 `dsh.bundle`，`files` 含 `cordis.patch.yml`），可直接安装到隔离 profile：

```bash
# 从本地目录安装（开发调试）
dsh plugin --profile demo add ./deepseek-harness-memory

# 校验配置层是否挂上（应看到 # == dsh-memory-plugin layer）
dsh --profile demo --dump-config

# 启动
dsh --profile demo
```

发布到 npm 后，用户可直接按包名安装：`dsh plugin add dsh-memory-plugin`。

## 接入 DeepSeek Harness

### 方式一：JS（Cordis 插件，`index.js`）

```js
import { MemoryBridge } from './index.js'

const mem = new MemoryBridge({ repoId: 'my-repo' })
await mem.saveMemory('用户偏好深色主题', { kind: 'semantic', importance: 0.9, tags: ['偏好'] })
const ctx = await mem.recallAndInject('帮我改成深色')   // { system_prompt, hits }
mem.close()
```

### 方式二：Python（直接调用核心）

```python
from dsh_memory import MemoryPlugin

mem = MemoryPlugin(project_root=".")
mem.save_memory("用户偏好深色主题", repo_id="my-repo", kind="semantic",
                importance=0.9, tags=["偏好"])
ctx = mem.recall_and_inject(user_message, repo_id="my-repo")
system_prompt = ctx["system_prompt"]   # 稳定前缀 + 关键命中
mem.start_background()                  # 空闲窗口自动整理
```

### 建议的 harness 集成点

- **消息前**：`recall_and_inject()` 拿到 `system_prompt`，作为 system 消息前缀。
- **消息后 / 沉淀**：把重要结论 `save_memory()` 或 `save_knowledge_page()`。
- **会话空闲**：`start_background()` 让后台线程自动整理。
- **权限**：高价值写入传 `token`，配合环境变量 `DSH_MEMORY_TOKEN`。

## OpenVINO 服务端对接

默认优先走 OpenVINO Model Server（OVMS）REST 接口做向量化，配置见
`config/config.yaml` 的 `embedding` 段：

```yaml
embedding:
  provider: "openvino"
  server_url: "http://127.0.0.1:9001"
  model_name: "bge-m3"
  dimension: 1024
```

若服务不可达或未安装 `openvino`，自动回退到**确定性哈希嵌入**，
插件在无 GPU / 无服务环境下依然可跑通（语义召回精度略降）。

## 反篡改与权限模型

- 每条记忆 / 知识页 / 反思均带 **SHA256 哈希**，`verify_integrity()` 可检出篡改。
- 所有写操作写入**追加式审计日志**（`audit_log` 表），不可覆盖。
- 高权限写入需校验口令：配置文件 `permissions.privileged_token`
  或环境变量 `DSH_MEMORY_TOKEN`；`MemoryStore.check_privilege(token)` 校验。

## 艾宾浩斯遗忘曲线

保持率 `R(t) = 0.9 · exp(−λ·t)`，重要度越高遗忘越慢（λ 打折），
复习间隔按 [1, 2, 4, 7, 15, 30] 天逐级晋升。召回打分会乘以 `R(t)`，
久未复习的记忆自然衰减。


## 依赖

- 核心运行仅需 Python 3.9+ 标准库 + Node.js ≥ 18（`index.js` 桥接）。
- 可选：`PyYAML`（YAML 解析）、`openvino` + `numpy`（OpenVINO 向量化）。

## License

MIT
