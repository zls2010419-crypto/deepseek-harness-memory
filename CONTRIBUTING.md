# 申请收录到 awesome-dsh-plugin 的操作指南

本项目已满足 [awesome-dsh-plugin](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin)
的收录硬性要求。下面是如何把它提交上去的完整步骤。

## 已满足的要求（核对清单）

- [x] `package.json` 声明了 **`dsh.bundle`**（`"bundle": { "patch": "./cordis.patch.yml" }`）
- [x] 根目录有 **`cordis.patch.yml`**，且 `files` 字段包含它
- [x] 仓库有**真实可运行代码**（Python 核心 + JS 桥接 + 8 项单测 + 端到端 demo）
- [x] **MIT 许可**（`LICENSE`）
- [x] **图标**（`assets/icon-180.png`，180×180）
- [ ] **`dsh-plugin` topic**（需在 GitHub 仓库设置，见下）
- [ ] **仓库创建满 1 天**（CI 自动检查，见下）

## 第 1 步：把代码推到一个 GitHub 公共仓库

1. 在 GitHub 新建公共仓库（例如 `deepseek-harness-memory`）。
2. 把本目录推上去（`.gitignore` 已排除 `data/`、`__pycache__` 等运行时文件）：

   ```bash
   cd "C:\Users\Administrator\Desktop\deepseek-harness-memory"
   git init
   git add .
   git commit -m "DeepSeek Harness memory plugin: initial release"
   git branch -M main
   git remote add origin https://github.com/<你的用户名>/deepseek-harness-memory.git
   git push -u origin main
   ```

3. 在仓库页 **About 区域**（右侧齿轮）的 Topics 里添加 **`dsh-plugin`**。
   这是自动检查项之一。

> **仓库满 1 天**：CI 会校验仓库创建时间。若刚建好就提交 PR，会因「未满 1 天」被
> 暂时拦下——这**不是拒绝**，把功能做完（或等一天）后无需重新提交，CI 会自动重跑通过。

## 第 2 步（可选但推荐）：发布到 npm

发布后插件能进入 dsh 的 Discover 市场索引（需要包名 + 版本 + 发布时间）：

```bash
npm publish --access public
```

- 若包名 `dsh-memory-plugin` 已被占用，先在 `package.json` 里换一个可用名（
  `cordis.patch.yml` 里的 `name` 也要同步改）。
- 国内镜像可能有延迟：`latest` 若停留在 `-stage` 占位版，用
  `curl -X PUT https://registry.npmmirror.com/dsh-memory-plugin/sync` 触发重新抓取。

## 第 3 步：Fork 并添加投稿文件

1. 打开 <https://github.com/awesome-dsh-plugin/awesome-dsh-plugin> → **Fork**。
2. 在 fork 里新建**一个**文件 `data/plugins/<owner>__<repo>.yml`
   （`<owner>__<repo>` 用你的 GitHub 用户名和仓库名替换，双下划线连接）。
3. 文件内容照抄 `awesome-submission.example.yml`，替换三处占位符：

   ```yaml
   url: https://github.com/<owner>/<repo>
   name: <owner>/<repo>
   category: memory
   description:
     en: Long-term memory plugin with auto-recall, per-repo isolation, a memory graph, user-profile injection, an Ebbinghaus forgetting curve, and OpenVINO embeddings.
     zh: 长期记忆插件：自动召回、按仓库隔离、记忆图谱、用户画像注入、艾宾浩斯遗忘曲线与 OpenVINO 向量化。
   icon: https://raw.githubusercontent.com/<owner>/<repo>/main/assets/icon-180.png
   ```

   **这一个文件就是全部投稿。** 不要手工编辑 `README.md` / `README.zh.md`——它们由
   `data/plugins/*.yml` 脚本生成，手工改会被打回。

## 第 4 步：发 PR

- 目标分支 `main`，标题建议 `Add <owner>/<repo>`。
- PR 描述用下面的 checklist：

  ```markdown
  - [x] Added `data/plugins/<owner>__<repo>.yml` — that single file is the whole submission.
  - [x] My repo's `package.json` declares `dsh.bundle` (`dsh.bundle.patch: ./cordis.patch.yml`).
  - [x] My repo is at least 1 day old.
  - [x] `category: memory` — it is a long-term memory plugin.
  - [x] Description states what the plugin does, no superlatives, and matches the code.
  - [x] My repo has the `dsh-plugin` topic.
  ```

## 第 5 步：等 CI + 人工评审

CI 依次检查：① 每条 PR 最多 3 条 ② `dsh.bundle` 存在 ③ 仓库满 1 天 ④ awesome-lint 与站点构建。

- CI 失败会**明确指出要改什么**，在同一分支 push 修复即可，无需重开 PR。
- CI 通过只是前置条件，**维护者会读源码**，核对描述是否属实、分类是否贴切、是否与已有条目重复。
- 需修改时维护者会打 **`held: author`** 标签——这不是拒绝，改好后会被重新读过。
- 合并后网站自动重建，无需再做任何事。

## 注意事项（来自官方 contributing 指南）

- **描述必须属实**：描述会被当作对插件的声明并与代码核对，夸大是被打回的首要原因。
  本插件的 `en` 描述逐项对应：auto-recall（`recall.py`）、per-repo isolation（`store.py`）、
  memory graph（`graph.py`）、user-profile injection（`profile.py`）、Ebbinghaus forgetting
  curve（`forgetting.py`）、OpenVINO embeddings（`embedder.py`）。
- **描述含 `: `（ASCII 冒号+空格）必须加引号**，否则 YAML 会把它当嵌套键解析。
- **选贴合功能的分类**：本插件是 `memory`（分类列表含 `memory`）。
- **一个 PR 最多 3 条**。
