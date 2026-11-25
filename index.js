// DeepSeek Harness 记忆插件 —— Cordis 插件入口 + Python 核心桥接。
//
// 本文件是可安装 DSH bundle 的入口：导出 `name` 与 `apply(ctx)`。
// 记忆核心（召回 / 图谱 / 画像 / 遗忘曲线 / OpenVINO 向量化）由 Python 包
// `dsh_memory` 实现，这里通过 JSON-lines over stdio 子进程调用 `dsh_memory/cli.py`。
//
// 参见官方文档：https://dsh-plugin.net/guides/how-to-create-dsh-plugin

import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import readline from 'node:readline'

export const name = 'dsh-memory-plugin'

const HERE = path.dirname(fileURLToPath(import.meta.url))

/**
 * 记忆核心的 Python 桥接：JSON-lines over stdio。
 * 每个请求 `{ id, method, params }`，每个响应 `{ id, result | error }`。
 */
export class MemoryBridge {
  constructor(opts = {}) {
    this.repoId = opts.repoId || 'default'
    const python = opts.python || process.env.DSH_MEMORY_PYTHON ||
      (process.platform === 'win32' ? 'python' : 'python3')
    const cli = path.join(HERE, 'dsh_memory', 'cli.py')

    this.proc = spawn(python, [cli], { stdio: ['pipe', 'pipe', 'pipe'] })
    this._seq = 0
    this._pending = new Map()
    this._closed = false

    const rl = readline.createInterface({ input: this.proc.stdout })
    rl.on('line', (line) => {
      let msg
      try { msg = JSON.parse(line) } catch { return }
      const p = this._pending.get(msg.id)
      if (!p) return
      this._pending.delete(msg.id)
      if (msg.error) p.reject(new Error(msg.error))
      else p.resolve(msg.result)
    })
    this.proc.stderr.on('data', () => {})
    this.proc.on('exit', () => { this._closed = true })
  }

  _call(method, params = {}) {
    if (this._closed) return Promise.reject(new Error('memory bridge closed'))
    const id = ++this._seq
    this.proc.stdin.write(JSON.stringify({ id, method, params }) + '\n')
    return new Promise((resolve, reject) => this._pending.set(id, { resolve, reject }))
  }

  saveMemory(content, opts = {}) {
    return this._call('save_memory', {
      content,
      kind: opts.kind || 'episodic',
      importance: opts.importance ?? 0.5,
      tags: opts.tags || [],
      repo_id: opts.repoId || this.repoId,
    })
  }

  recall(message, opts = {}) {
    return this._call('recall', {
      message,
      top_k: opts.topK,
      repo_id: opts.repoId || this.repoId,
    })
  }

  recallAndInject(message, opts = {}) {
    return this._call('recall_and_inject', {
      message,
      top_k: opts.topK,
      repo_id: opts.repoId || this.repoId,
    })
  }

  saveKnowledgePage(title, content, opts = {}) {
    return this._call('save_knowledge_page', {
      title,
      content,
      summary: opts.summary || null,
      tags: opts.tags || [],
      repo_id: opts.repoId || this.repoId,
    })
  }

  stats(repoId = this.repoId) {
    return this._call('stats', { repo_id: repoId })
  }

  verifyIntegrity(repoId = this.repoId) {
    return this._call('verify_integrity', { repo_id: repoId })
  }

  close() {
    if (this._closed) return
    try { this.proc.stdin.end() } catch {}
    try { this.proc.kill() } catch {}
    this._closed = true
  }
}

/**
 * cordis 插件入口。Cordis 会以共享 context 调用本函数。
 *
 * @param {import('@deepseek-ai/cordis').Context} ctx
 * @param {object} config
 */
export function apply(ctx, config = {}) {
  const bridge = new MemoryBridge(config)

  // 提供服务：按 cordis service 约定挂载，供 agent 消息流 / 其它插件消费。
  if (typeof ctx.provide === 'function') ctx.provide('memory', bridge)
  else ctx.memory = bridge

  // 可逆副作用：卸载时释放 Python 子进程。
  if (typeof ctx.on === 'function') ctx.on('dispose', () => bridge.close())

  console.log('[dsh-memory-plugin] loaded')
  return () => bridge.close()
}
