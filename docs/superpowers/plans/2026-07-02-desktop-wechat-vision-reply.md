# Desktop WeChat Vision Reply Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将桌面版升级为唯一工作台入口，并为微信 PC 客户端加入半自动视觉回复能力：自动识别、生成草稿、填入输入框，最终由人工发送。

**Architecture:** 先把原网页版工作台能力通过 Electron IPC 暴露到桌面版主窗口，再在 Python 本地服务中新增微信 PC 视觉观察器的可测试接口。视觉能力第一版采用可替换识别器和模拟识别路径，窗口粘贴必须做微信前台校验，且任何路径都不自动发送。

**Tech Stack:** Electron、React、TypeScript、Vite、Python 标准库、`unittest`、Node `node:test`、JSONL 本地存储、现有 `WorkbenchWebState`/`WorkbenchSession`/`AssistedPasteAdapter`。

---

## 文件结构

- 修改 `summer_camp_agent/workbench_web.py`：把原网页工作台已有能力稳定为桌面 API，新增视觉观察器 API。
- 新建 `summer_camp_agent/wechat_window.py`：封装 Windows 前台窗口标题检测和微信窗口判断。
- 修改 `summer_camp_agent/wechat_assisted_paste.py`：增加微信窗口校验后的安全粘贴方法。
- 新建 `summer_camp_agent/wechat_vision.py`：定义 `VisionMessage`、视觉识别器接口、模拟识别器、截图结果归一化和去重。
- 新建 `tests/test_wechat_window.py`：覆盖微信窗口判断。
- 新建 `tests/test_wechat_vision.py`：覆盖视觉消息转 `ChatEvent`、去重、低置信拦截。
- 修改 `tests/test_wechat_assisted_paste.py`：覆盖非微信窗口降级复制、不按回车、不点击。
- 修改 `tests/test_workbench_web.py`：覆盖 `/api/vision/*` 状态、捕获、轮询结果入消息流。
- 修改 `desktop/src/shared/types.ts`：补齐桌面工作台、消息、视觉状态、操作结果类型。
- 修改 `desktop/src/preload/preload.ts` 和 `desktop/src/preload/preload.cjs`：暴露消息流、草稿、候选、粘贴、确认、视觉观察 IPC。
- 修改 `desktop/src/main/main.ts`：增加对应 IPC handler，转发到 Python API。
- 修改 `desktop/src/renderer/App.tsx`：把主窗口从轻量控制器改为完整工作台。
- 修改 `desktop/src/renderer/styles.css`：实现工作台布局。
- 修改 `desktop/tests/static.test.mjs`：用静态测试锁定桌面工作台入口和视觉按钮。
- 修改 `scripts/start_desktop_app.ps1` 和 `docs/README.md`：将桌面版写为唯一用户入口，网页版仅作为内部兼容层。

## 安全边界

- 不自动点击微信发送按钮。
- 不按回车。
- 不注入微信进程。
- 不读取微信数据库。
- 当前前台窗口不是微信时，只复制到剪贴板。
- 视觉识别置信度低时不填入，只展示识别结果。
- 视觉截图默认不落盘。

## 任务 1：补齐桌面 API 合约

**Files:**
- Modify: `desktop/src/shared/types.ts`
- Modify: `desktop/src/preload/preload.ts`
- Modify: `desktop/src/preload/preload.cjs`
- Modify: `desktop/src/main/main.ts`
- Test: `desktop/tests/static.test.mjs`

- [ ] **Step 1: Write the failing static test**

Append this test to `desktop/tests/static.test.mjs`:

```js
test('desktop api exposes workbench and vision operations', () => {
  const types = read('src/shared/types.ts')
  const preload = read('src/preload/preload.ts')
  const main = read('src/main/main.ts')

  for (const name of [
    'getItems',
    'ask',
    'pasteReply',
    'confirmSent',
    'saveCandidate',
    'startVision',
    'stopVision',
    'captureVision',
    'getVisionStatus'
  ]) {
    assert.match(types, new RegExp(`${name}\\\\(`))
    assert.match(preload, new RegExp(`${name}:`))
  }

  assert.match(main, /ipcMain\.handle\('workbench:getItems'/)
  assert.match(main, /ipcMain\.handle\('vision:capture'/)
  assert.match(main, /\/api\/items/)
  assert.match(main, /\/api\/vision\/capture/)
})
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```text
npm.cmd --prefix desktop test
```

Expected: FAIL because `getItems`, `startVision`, and related IPC handlers are not defined.

- [ ] **Step 3: Add shared TypeScript types**

Modify `desktop/src/shared/types.ts` by adding these interfaces before `export interface DesktopApi`:

```ts
export interface WorkbenchItem {
  event_id: string
  group_name: string
  sender: string
  message_time: string
  question: string
  source: string
  summary: string
  status: string
  mode: string
  reply: string
  trigger_reasons: string[]
  matched_keywords: string[]
  recommendation: string
  engine_action: string
  intent: string
  answer_source: string
  confidence: number
  reason: string
}

export interface WorkbenchItemsPayload {
  items: WorkbenchItem[]
}

export interface WorkbenchItemPayload extends WorkbenchItemsPayload {
  item: WorkbenchItem
}

export interface ActionResult {
  status: string
  message: string
}

export interface PasteReplyResult extends ActionResult {
  paste_action: string
  foreground_window_title: string
}

export interface VisionStatus {
  running: boolean
  window_title: string
  last_message: string
  last_error: string
}

export interface VisionCapturePayload extends WorkbenchItemsPayload {
  status: string
  message: string
  vision: VisionStatus
}
```

Then extend `DesktopApi` with:

```ts
  getItems(): Promise<WorkbenchItemsPayload>
  ask(question: string): Promise<WorkbenchItemPayload>
  pasteReply(eventId: string, reply: string): Promise<PasteReplyResult>
  confirmSent(eventId: string, reply: string): Promise<ActionResult>
  saveCandidate(eventId: string, reply: string): Promise<ActionResult>
  startVision(): Promise<VisionCapturePayload>
  stopVision(): Promise<VisionCapturePayload>
  captureVision(): Promise<VisionCapturePayload>
  getVisionStatus(): Promise<VisionStatus>
```

- [ ] **Step 4: Add preload methods**

Modify `desktop/src/preload/preload.ts` inside `desktopApi`:

```ts
  getItems: () => ipcRenderer.invoke('workbench:getItems'),
  ask: (question: string) => ipcRenderer.invoke('workbench:ask', question),
  pasteReply: (eventId: string, reply: string) => ipcRenderer.invoke('workbench:pasteReply', eventId, reply),
  confirmSent: (eventId: string, reply: string) => ipcRenderer.invoke('workbench:confirmSent', eventId, reply),
  saveCandidate: (eventId: string, reply: string) => ipcRenderer.invoke('workbench:saveCandidate', eventId, reply),
  startVision: () => ipcRenderer.invoke('vision:start'),
  stopVision: () => ipcRenderer.invoke('vision:stop'),
  captureVision: () => ipcRenderer.invoke('vision:capture'),
  getVisionStatus: () => ipcRenderer.invoke('vision:getStatus'),
```

Run:

```text
npm.cmd --prefix desktop run build:main
```

Expected: PASS and `desktop/src/preload/preload.cjs` is regenerated with the same method names.

- [ ] **Step 5: Add main process forwarding handlers**

Modify `desktop/src/main/main.ts`:

1. Extend the import from `../shared/types` with `ActionResult`, `PasteReplyResult`, `VisionCapturePayload`, `VisionStatus`, `WorkbenchItemPayload`, `WorkbenchItemsPayload`.
2. Add these methods to `PythonService`:

```ts
  async getItems(): Promise<WorkbenchItemsPayload> {
    await this.ensureStarted()
    return this.request<WorkbenchItemsPayload>('/api/items')
  }

  async ask(question: string): Promise<WorkbenchItemPayload> {
    await this.ensureStarted()
    return this.request<WorkbenchItemPayload>('/api/ask', { question })
  }

  async pasteReply(eventId: string, reply: string): Promise<PasteReplyResult> {
    await this.ensureStarted()
    return this.request<PasteReplyResult>('/api/wechat/paste', { event_id: eventId, reply })
  }

  async confirmSent(eventId: string, reply: string): Promise<ActionResult> {
    await this.ensureStarted()
    return this.request<ActionResult>('/api/wechat/confirm-sent', { event_id: eventId, reply })
  }

  async saveCandidate(eventId: string, reply: string): Promise<ActionResult> {
    await this.ensureStarted()
    return this.request<ActionResult>('/api/save-candidate', { event_id: eventId, reply })
  }

  async startVision(): Promise<VisionCapturePayload> {
    await this.ensureStarted()
    return this.request<VisionCapturePayload>('/api/vision/start', {})
  }

  async stopVision(): Promise<VisionCapturePayload> {
    await this.ensureStarted()
    return this.request<VisionCapturePayload>('/api/vision/stop', {})
  }

  async captureVision(): Promise<VisionCapturePayload> {
    await this.ensureStarted()
    return this.request<VisionCapturePayload>('/api/vision/capture', {})
  }

  async getVisionStatus(): Promise<VisionStatus> {
    await this.ensureStarted()
    return this.request<VisionStatus>('/api/vision/status')
  }
```

3. Register handlers inside `app.whenReady().then()` before `mainWindow = createWindow('main')`:

```ts
  ipcMain.handle('workbench:getItems', () => service.getItems())
  ipcMain.handle('workbench:ask', (_event, question: string) => service.ask(question))
  ipcMain.handle('workbench:pasteReply', (_event, eventId: string, reply: string) => service.pasteReply(eventId, reply))
  ipcMain.handle('workbench:confirmSent', (_event, eventId: string, reply: string) => service.confirmSent(eventId, reply))
  ipcMain.handle('workbench:saveCandidate', (_event, eventId: string, reply: string) => service.saveCandidate(eventId, reply))
  ipcMain.handle('vision:start', () => service.startVision())
  ipcMain.handle('vision:stop', () => service.stopVision())
  ipcMain.handle('vision:capture', () => service.captureVision())
  ipcMain.handle('vision:getStatus', () => service.getVisionStatus())
```

- [ ] **Step 6: Verify and commit**

Run:

```text
npm.cmd --prefix desktop test
npm.cmd --prefix desktop run typecheck
```

Expected: both PASS.

Commit:

```text
git add desktop/src/shared/types.ts desktop/src/preload/preload.ts desktop/src/preload/preload.cjs desktop/src/main/main.ts desktop/tests/static.test.mjs
git commit -m "feat: expose desktop workbench api"
```

## 任务 2：桌面主窗口合并网页版工作台

**Files:**
- Modify: `desktop/src/renderer/App.tsx`
- Modify: `desktop/src/renderer/styles.css`
- Test: `desktop/tests/static.test.mjs`

- [ ] **Step 1: Write the failing static test**

Append this test to `desktop/tests/static.test.mjs`:

```js
test('renderer main window contains the unified desktop workbench', () => {
  const app = read('src/renderer/App.tsx')
  const css = read('src/renderer/styles.css')

  assert.match(app, /DesktopWorkbench/)
  assert.match(app, /消息流/)
  assert.match(app, /决策面板/)
  assert.match(app, /回复草稿/)
  assert.match(app, /填入微信/)
  assert.match(app, /我已发送/)
  assert.match(app, /保存候选/)
  assert.match(app, /启动视觉观察/)
  assert.match(app, /captureVision/)
  assert.match(css, /\.workbench-shell/)
  assert.match(css, /grid-template-columns:\s*240px minmax\(0,\s*1fr\) 340px/)
  assert.doesNotMatch(app, /openAdvanced\('messages'\)/)
})
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```text
npm.cmd --prefix desktop test
```

Expected: FAIL because `DesktopWorkbench` does not exist.

- [ ] **Step 3: Replace the main controller with `DesktopWorkbench`**

In `desktop/src/renderer/App.tsx`:

1. Keep `SettingsWindow`, `WorkTracePage`, `AdvancedWindow`, helpers, and fallback settings.
2. Replace `return <Controller status={status} onRefresh={refresh} />` with:

```tsx
  return <DesktopWorkbench status={status} onRefresh={refresh} />
```

3. Add local state in a new `DesktopWorkbench` component:

```tsx
function DesktopWorkbench({ status, onRefresh }: { status: AppStatus; onRefresh: () => Promise<void> }) {
  const [itemsPayload, setItemsPayload] = useState<WorkbenchItemsPayload>({ items: [] })
  const [selectedId, setSelectedId] = useState('')
  const [replyDraft, setReplyDraft] = useState('')
  const [manualQuestion, setManualQuestion] = useState('')
  const [message, setMessage] = useState('桌面工作台已就绪')
  const [vision, setVision] = useState<VisionStatus>({ running: false, window_title: '', last_message: '', last_error: '' })
  const selected = itemsPayload.items.find((item) => item.event_id === selectedId) ?? itemsPayload.items[0]

  useEffect(() => {
    void refreshItems()
    void refreshVision()
  }, [])

  useEffect(() => {
    if (selected) setReplyDraft(selected.reply || '')
  }, [selected?.event_id])

  async function refreshItems() {
    const payload = await window.desktop.getItems()
    setItemsPayload(payload)
    setSelectedId((current) => current && payload.items.some((item) => item.event_id === current) ? current : payload.items[0]?.event_id ?? '')
  }

  async function refreshVision() {
    try {
      setVision(await window.desktop.getVisionStatus())
    } catch {
      setVision((current) => ({ ...current, last_error: '视觉观察器尚未启动' }))
    }
  }
```

4. Add action methods inside the same component:

```tsx
  async function generateDraft() {
    const question = manualQuestion.trim()
    if (!question) {
      setMessage('请先输入学生问题')
      return
    }
    const payload = await window.desktop.ask(question)
    setItemsPayload({ items: payload.items })
    setSelectedId(payload.item.event_id)
    setManualQuestion('')
    setMessage('已生成回复草稿')
  }

  async function pasteReply() {
    if (!selected) {
      setMessage('请先选择一条消息')
      return
    }
    const result = await window.desktop.pasteReply(selected.event_id, replyDraft)
    setMessage(result.message)
  }

  async function confirmSent() {
    if (!selected) {
      setMessage('请先选择一条消息')
      return
    }
    const result = await window.desktop.confirmSent(selected.event_id, replyDraft)
    setMessage(result.message)
  }

  async function saveCandidate() {
    if (!selected) {
      setMessage('请先选择一条消息')
      return
    }
    const result = await window.desktop.saveCandidate(selected.event_id, replyDraft)
    setMessage(result.message)
  }

  async function startVision() {
    const payload = await window.desktop.startVision()
    setItemsPayload({ items: payload.items })
    setVision(payload.vision)
    setMessage(payload.message)
  }

  async function captureVision() {
    const payload = await window.desktop.captureVision()
    setItemsPayload({ items: payload.items })
    setVision(payload.vision)
    setMessage(payload.message)
  }

  async function stopVision() {
    const payload = await window.desktop.stopVision()
    setVision(payload.vision)
    setMessage(payload.message)
  }
```

5. Add JSX layout:

```tsx
  return (
    <main className="workbench-shell">
      <aside className="workbench-sidebar">
        <header className="brand-row">
          <div className="brand-mark" aria-hidden="true" />
          <strong>夏令营 Agent</strong>
        </header>
        <section className="sidebar-section">
          <h2>微信 PC</h2>
          <p>{vision.running ? '观察中' : '未观察'}</p>
          <small>{vision.window_title || status.engine.group_name || '未连接窗口'}</small>
          <button className="secondary-action" type="button" onClick={startVision}>启动视觉观察</button>
          <button className="ghost-action" type="button" onClick={captureVision}>识别当前窗口</button>
          <button className="ghost-action" type="button" onClick={stopVision}>停止观察</button>
        </section>
        <section className="sidebar-section">
          <h2>手动生成</h2>
          <textarea value={manualQuestion} onChange={(event) => setManualQuestion(event.target.value)} />
          <button className="secondary-action" type="button" onClick={generateDraft}>生成草稿</button>
        </section>
        <button className="ghost-action" type="button" onClick={() => window.desktop.openSettings()}>配置</button>
        <button className="ghost-action" type="button" onClick={() => window.desktop.openAdvanced('work_trace')}>工作轨迹</button>
      </aside>
      <section className="message-stream">
        <header><h1>消息流</h1><button type="button" onClick={refreshItems}>刷新</button></header>
        <div className="message-list">
          {itemsPayload.items.map((item) => (
            <button key={item.event_id} className={`message-row ${selected?.event_id === item.event_id ? 'selected' : ''}`} type="button" onClick={() => setSelectedId(item.event_id)}>
              <span>{item.status}</span>
              <strong>{item.question}</strong>
              <small>{item.sender} · {item.source}</small>
            </button>
          ))}
        </div>
      </section>
      <aside className="decision-panel">
        <h2>决策面板</h2>
        {selected ? <DecisionSummary item={selected} /> : <p>暂无消息</p>}
      </aside>
      <section className="reply-composer">
        <label htmlFor="replyDraft">回复草稿</label>
        <textarea id="replyDraft" value={replyDraft} onChange={(event) => setReplyDraft(event.target.value)} />
        <div className="reply-actions">
          <button className="primary-action compact" type="button" onClick={pasteReply}>填入微信</button>
          <button className="secondary-action compact" type="button" onClick={confirmSent}>我已发送</button>
          <button className="ghost-action compact" type="button" onClick={saveCandidate}>保存候选</button>
        </div>
        <p role="status">{message}</p>
      </section>
    </main>
  )
}
```

6. Add `DecisionSummary`:

```tsx
function DecisionSummary({ item }: { item: WorkbenchItem }) {
  return (
    <dl className="decision-grid">
      <DetailRow label="触发原因" value={item.trigger_reasons.join(', ') || '未触发'} />
      <DetailRow label="命中关键词" value={item.matched_keywords.join(', ') || '无'} />
      <DetailRow label="建议动作" value={item.recommendation || '无'} />
      <DetailRow label="处理模式" value={item.mode || '无'} />
      <DetailRow label="来源" value={item.answer_source || '无'} />
      <DetailRow label="置信度" value={Number(item.confidence || 0).toFixed(2)} />
      <DetailRow label="原因" value={item.reason || '无'} />
    </dl>
  )
}
```

- [ ] **Step 4: Add workbench CSS**

Append to `desktop/src/renderer/styles.css`:

```css
.workbench-shell {
  width: 100vw;
  height: 100vh;
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr) 340px;
  grid-template-rows: minmax(0, 1fr) 210px;
  background: var(--bg);
  color: var(--text);
}

.workbench-sidebar,
.message-stream,
.decision-panel,
.reply-composer {
  min-width: 0;
  min-height: 0;
  border-color: var(--line);
}

.workbench-sidebar {
  grid-row: 1 / 3;
  padding: 16px;
  border-right: 1px solid var(--line);
  overflow: auto;
}

.sidebar-section {
  display: grid;
  gap: 10px;
  margin-top: 16px;
}

.message-stream {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  padding: 16px;
  overflow: hidden;
}

.message-stream header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.message-list {
  overflow: auto;
  border: 1px solid var(--line);
}

.message-row {
  width: 100%;
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  gap: 6px 10px;
  text-align: left;
  border: 0;
  border-bottom: 1px solid var(--line);
  background: var(--panel);
  color: var(--text);
  padding: 10px;
}

.message-row.selected {
  background: rgba(24, 194, 139, 0.14);
}

.message-row strong,
.message-row small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.decision-panel {
  padding: 16px;
  border-left: 1px solid var(--line);
  overflow: auto;
}

.decision-grid {
  display: grid;
  grid-template-columns: 86px minmax(0, 1fr);
  gap: 10px;
}

.reply-composer {
  grid-column: 2 / 4;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto auto;
  gap: 8px;
  padding: 14px 16px;
  border-top: 1px solid var(--line);
}

.reply-composer textarea,
.sidebar-section textarea {
  width: 100%;
  min-height: 84px;
  resize: none;
}

.reply-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}

.compact {
  min-height: 34px;
}
```

- [ ] **Step 5: Verify and commit**

Run:

```text
npm.cmd --prefix desktop test
npm.cmd --prefix desktop run typecheck
```

Expected: both PASS.

Commit:

```text
git add desktop/src/renderer/App.tsx desktop/src/renderer/styles.css desktop/tests/static.test.mjs
git commit -m "feat: merge workbench into desktop window"
```

## 任务 3：微信窗口安全粘贴

**Files:**
- Create: `summer_camp_agent/wechat_window.py`
- Modify: `summer_camp_agent/wechat_assisted_paste.py`
- Test: `tests/test_wechat_window.py`
- Test: `tests/test_wechat_assisted_paste.py`

- [ ] **Step 1: Write failing window tests**

Create `tests/test_wechat_window.py`:

```python
import unittest

from summer_camp_agent.wechat_window import is_wechat_window_title


class WeChatWindowTest(unittest.TestCase):
    def test_accepts_wechat_titles(self):
        self.assertTrue(is_wechat_window_title("微信"))
        self.assertTrue(is_wechat_window_title("文件传输助手 - 微信"))
        self.assertTrue(is_wechat_window_title("沐曦开源英才夏令营咨询群 - 微信"))

    def test_rejects_non_wechat_titles(self):
        self.assertFalse(is_wechat_window_title(""))
        self.assertFalse(is_wechat_window_title("Visual Studio Code"))
        self.assertFalse(is_wechat_window_title("企业微信"))


if __name__ == "__main__":
    unittest.main()
```

Append to `tests/test_wechat_assisted_paste.py`:

```python
class NonWechatBackend(FakeBackend):
    def foreground_window_title(self):
        return "Visual Studio Code"


class WechatCheckedPasteTest(unittest.TestCase):
    def test_checked_paste_downgrades_when_foreground_is_not_wechat(self):
        backend = NonWechatBackend()

        result = AssistedPasteAdapter(backend).paste_to_wechat_foreground("同学你好")

        self.assertEqual(result.action, "copied")
        self.assertEqual(backend.clipboard_text, "同学你好")
        self.assertEqual(backend.shortcuts, [])
        self.assertIn("请切回微信", result.message)

    def test_checked_paste_allows_wechat_foreground(self):
        backend = FakeBackend()

        result = AssistedPasteAdapter(backend).paste_to_wechat_foreground("同学你好")

        self.assertEqual(result.action, "pasted")
        self.assertEqual(backend.shortcuts, ["CTRL+V"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```text
python -B -m unittest tests.test_wechat_window tests.test_wechat_assisted_paste
```

Expected: FAIL because `wechat_window` and `paste_to_wechat_foreground` do not exist.

- [ ] **Step 3: Implement window title helper**

Create `summer_camp_agent/wechat_window.py`:

```python
from __future__ import annotations


def is_wechat_window_title(title: str) -> bool:
    value = title.strip()
    if not value:
        return False
    if "企业微信" in value:
        return False
    return value == "微信" or value.endswith(" - 微信") or value.endswith("- 微信")
```

- [ ] **Step 4: Implement checked paste**

Modify `summer_camp_agent/wechat_assisted_paste.py`:

1. Add import:

```python
from .wechat_window import is_wechat_window_title
```

2. Add this method to `AssistedPasteAdapter`:

```python
    def paste_to_wechat_foreground(self, text: str) -> PasteResult:
        copied = self.copy_only(text)
        if copied.action != "copied":
            return copied
        title = ""
        try:
            title = self.backend.foreground_window_title()
            if not is_wechat_window_title(title):
                return PasteResult("copied", "已复制到剪贴板。请切回微信 PC 输入框后手动粘贴。", title)
            self.backend.send_ctrl_v()
            return PasteResult("pasted", "已填入微信 PC 当前输入框，请确认后手动发送。", title)
        except Exception:
            return PasteResult("copied", "已复制到剪贴板，但未能自动粘贴。请手动粘贴到微信输入框。", title)
```

- [ ] **Step 5: Verify and commit**

Run:

```text
python -B -m unittest tests.test_wechat_window tests.test_wechat_assisted_paste
```

Expected: PASS.

Commit:

```text
git add summer_camp_agent/wechat_window.py summer_camp_agent/wechat_assisted_paste.py tests/test_wechat_window.py tests/test_wechat_assisted_paste.py
git commit -m "feat: guard wechat foreground paste"
```

## 任务 4：微信视觉观察器核心模型

**Files:**
- Create: `summer_camp_agent/wechat_vision.py`
- Test: `tests/test_wechat_vision.py`

- [ ] **Step 1: Write failing vision tests**

Create `tests/test_wechat_vision.py`:

```python
import unittest

from summer_camp_agent.wechat_vision import (
    VisionMessage,
    VisionState,
    WeChatVisionObserver,
)
from summer_camp_agent.wechat_bridge_config import DEFAULT_GROUP_NAME


class FakeRecognizer:
    def __init__(self, messages):
        self.messages = messages

    def recognize(self, screenshot):
        return self.messages


class WeChatVisionTest(unittest.TestCase):
    def test_capture_turns_high_confidence_message_into_chat_event(self):
        observer = WeChatVisionObserver(
            recognizer=FakeRecognizer([
                VisionMessage(
                    message_id="m1",
                    sender_alias="成员001",
                    content="报名入口在哪里？",
                    message_time="2026-07-02 20:00:00",
                    region={"x": 10, "y": 20, "width": 120, "height": 40},
                    confidence=0.92,
                )
            ])
        )

        result = observer.capture_once(b"fake", window_title="微信群 - 微信", group_name=DEFAULT_GROUP_NAME)

        self.assertEqual(result.status, "ok")
        self.assertEqual(len(result.events), 1)
        self.assertEqual(result.events[0].content, "报名入口在哪里？")
        self.assertEqual(result.events[0].source, "wechat_pc_vision")

    def test_capture_deduplicates_seen_messages(self):
        message = VisionMessage(
            message_id="m1",
            sender_alias="成员001",
            content="报名入口在哪里？",
            message_time="2026-07-02 20:00:00",
            region={"x": 10, "y": 20, "width": 120, "height": 40},
            confidence=0.92,
        )
        observer = WeChatVisionObserver(recognizer=FakeRecognizer([message]))

        first = observer.capture_once(b"fake", window_title="微信群 - 微信", group_name=DEFAULT_GROUP_NAME)
        second = observer.capture_once(b"fake", window_title="微信群 - 微信", group_name=DEFAULT_GROUP_NAME)

        self.assertEqual(len(first.events), 1)
        self.assertEqual(len(second.events), 0)
        self.assertEqual(second.message, "未识别到新的高置信消息")

    def test_low_confidence_message_is_blocked(self):
        observer = WeChatVisionObserver(
            recognizer=FakeRecognizer([
                VisionMessage(
                    message_id="m2",
                    sender_alias="成员002",
                    content="住宿怎么安排？",
                    message_time="2026-07-02 20:01:00",
                    region={"x": 10, "y": 90, "width": 120, "height": 40},
                    confidence=0.41,
                )
            ])
        )

        result = observer.capture_once(b"fake", window_title="微信群 - 微信", group_name=DEFAULT_GROUP_NAME)

        self.assertEqual(result.status, "low_confidence")
        self.assertEqual(result.events, [])
        self.assertIsInstance(result.vision, VisionState)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```text
python -B -m unittest tests.test_wechat_vision
```

Expected: FAIL because `summer_camp_agent.wechat_vision` does not exist.

- [ ] **Step 3: Implement the vision model and observer**

Create `summer_camp_agent/wechat_vision.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from .chat_log_sanitizer import hash_identifier
from .workbench_models import ChatEvent


@dataclass(frozen=True)
class VisionMessage:
    message_id: str
    sender_alias: str
    content: str
    message_time: str
    region: dict[str, int]
    confidence: float
    source: str = "wechat_pc_vision"


@dataclass(frozen=True)
class VisionState:
    running: bool = False
    window_title: str = ""
    last_message: str = ""
    last_error: str = ""


@dataclass(frozen=True)
class VisionCaptureResult:
    status: str
    message: str
    events: list[ChatEvent]
    vision: VisionState


class StaticVisionRecognizer:
    def recognize(self, screenshot: bytes) -> list[VisionMessage]:
        return []


class WeChatVisionObserver:
    def __init__(self, recognizer=None, min_confidence: float = 0.75):
        self.recognizer = recognizer or StaticVisionRecognizer()
        self.min_confidence = min_confidence
        self.seen_message_ids: set[str] = set()
        self.state = VisionState()

    def start(self) -> VisionState:
        self.state = VisionState(running=True, window_title=self.state.window_title)
        return self.state

    def stop(self) -> VisionState:
        self.state = VisionState(running=False, window_title=self.state.window_title)
        return self.state

    def capture_once(self, screenshot: bytes, *, window_title: str, group_name: str) -> VisionCaptureResult:
        messages = self.recognizer.recognize(screenshot)
        high_confidence = [message for message in messages if message.confidence >= self.min_confidence]
        if not high_confidence and messages:
            self.state = VisionState(
                running=self.state.running,
                window_title=window_title,
                last_message=messages[0].content,
                last_error="识别置信度过低",
            )
            return VisionCaptureResult("low_confidence", "识别置信度过低，已拦截自动填入。", [], self.state)

        events: list[ChatEvent] = []
        for message in high_confidence:
            event_id = self._event_id(window_title, message)
            if event_id in self.seen_message_ids:
                continue
            self.seen_message_ids.add(event_id)
            events.append(self._to_event(event_id, window_title, group_name, message))

        last_message = high_confidence[0].content if high_confidence else ""
        self.state = VisionState(running=self.state.running, window_title=window_title, last_message=last_message)
        if events:
            return VisionCaptureResult("ok", f"已识别 {len(events)} 条新消息", events, self.state)
        return VisionCaptureResult("ok", "未识别到新的高置信消息", [], self.state)

    def _event_id(self, window_title: str, message: VisionMessage) -> str:
        region = ",".join(f"{key}:{message.region.get(key, 0)}" for key in sorted(message.region))
        return hash_identifier(f"{window_title}:{message.message_id}:{message.content}:{message.message_time}:{region}")

    def _to_event(self, event_id: str, window_title: str, group_name: str, message: VisionMessage) -> ChatEvent:
        return ChatEvent(
            event_id=event_id,
            group_id_hash=hash_identifier(window_title),
            group_name=group_name,
            sender_alias=message.sender_alias,
            sender_role="student",
            message_time=message.message_time,
            content=message.content,
            raw_type="text",
            source=message.source,
        )
```

- [ ] **Step 4: Verify and commit**

Run:

```text
python -B -m unittest tests.test_wechat_vision
```

Expected: PASS.

Commit:

```text
git add summer_camp_agent/wechat_vision.py tests/test_wechat_vision.py
git commit -m "feat: add wechat vision observer model"
```

## 任务 5：将视觉观察器接入本地服务

**Files:**
- Modify: `summer_camp_agent/workbench_web.py`
- Modify: `tests/test_workbench_web.py`

- [ ] **Step 1: Write failing service tests**

Append to `tests/test_workbench_web.py`:

```python
class FakeVisionObserver:
    def __init__(self):
        from summer_camp_agent.wechat_vision import VisionState

        self.state = VisionState(running=False, window_title="微信群 - 微信")

    def start(self):
        from summer_camp_agent.wechat_vision import VisionState

        self.state = VisionState(running=True, window_title="微信群 - 微信")
        return self.state

    def stop(self):
        from summer_camp_agent.wechat_vision import VisionState

        self.state = VisionState(running=False, window_title="微信群 - 微信")
        return self.state

    def capture_once(self, screenshot, *, window_title, group_name):
        from summer_camp_agent.wechat_vision import VisionCaptureResult, VisionState
        from summer_camp_agent.workbench_models import ChatEvent

        event = ChatEvent(
            "vision-evt-1",
            "sha256:vision-group",
            group_name,
            "成员001",
            "student",
            "2026-07-02 20:00:00",
            "报名入口在哪里？",
            "text",
            "wechat_pc_vision",
        )
        self.state = VisionState(running=True, window_title=window_title, last_message=event.content)
        return VisionCaptureResult("ok", "已识别 1 条新消息", [event], self.state)


class WorkbenchVisionApiTest(unittest.TestCase):
    def test_vision_capture_processes_events_into_items(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchWebState(candidate_path=root / "candidates.jsonl", log_path=root / "logs.jsonl")
            state.vision_observer = FakeVisionObserver()

            payload = state.capture_vision_once()

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["items"][0]["source"], "wechat_pc_vision")
        self.assertEqual(payload["items"][0]["question"], "报名入口在哪里？")
        self.assertEqual(payload["vision"]["last_message"], "报名入口在哪里？")

    def test_vision_start_and_stop_return_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = WorkbenchWebState(candidate_path=root / "candidates.jsonl", log_path=root / "logs.jsonl")
            state.vision_observer = FakeVisionObserver()

            started = state.start_vision()
            stopped = state.stop_vision()

        self.assertTrue(started["vision"]["running"])
        self.assertFalse(stopped["vision"]["running"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```text
python -B -m unittest tests.test_workbench_web.WorkbenchVisionApiTest
```

Expected: FAIL because `capture_vision_once`, `start_vision`, and `stop_vision` do not exist.

- [ ] **Step 3: Add observer state to `WorkbenchWebState`**

Modify imports in `summer_camp_agent/workbench_web.py`:

```python
from .wechat_vision import VisionState, WeChatVisionObserver
```

Inside `WorkbenchWebState.__init__`, add:

```python
        self.vision_observer = WeChatVisionObserver()
        self.vision_window_title = "微信"
```

Add serializer helper near `serialize_item`:

```python
def serialize_vision_state(state: VisionState) -> dict[str, Any]:
    return {
        "running": state.running,
        "window_title": state.window_title,
        "last_message": state.last_message,
        "last_error": state.last_error,
    }
```

- [ ] **Step 4: Add state methods**

Add methods to `WorkbenchWebState`:

```python
    def get_vision_status(self) -> dict[str, Any]:
        return serialize_vision_state(self.vision_observer.state)

    def start_vision(self) -> dict[str, Any]:
        vision = self.vision_observer.start()
        self.recent_logs.append("微信视觉观察器已启动")
        captured = self.capture_vision_once()
        captured["vision"] = serialize_vision_state(vision if not captured.get("vision") else self.vision_observer.state)
        return captured

    def stop_vision(self) -> dict[str, Any]:
        vision = self.vision_observer.stop()
        self.recent_logs.append("微信视觉观察器已停止")
        return {
            "status": "ok",
            "message": "微信视觉观察器已停止",
            "items": [serialize_item(item) for item in self.items],
            "vision": serialize_vision_state(vision),
        }

    def capture_vision_once(self) -> dict[str, Any]:
        result = self.vision_observer.capture_once(
            b"",
            window_title=self.vision_window_title,
            group_name=self.group_config.group_name,
        )
        for event in result.events:
            self.items.append(self.session.process_event(event))
        self.recent_logs.append(result.message)
        return {
            "status": result.status,
            "message": result.message,
            "items": [serialize_item(item) for item in self.items],
            "vision": serialize_vision_state(result.vision),
        }
```

- [ ] **Step 5: Add HTTP routes**

In `create_handler(state).do_GET`, add:

```python
            if path == "/api/vision/status":
                self._send_json(state.get_vision_status())
                return
```

In `do_POST`, add:

```python
                if path == "/api/vision/start":
                    self._send_json(state.start_vision())
                    return
                if path == "/api/vision/stop":
                    self._send_json(state.stop_vision())
                    return
                if path == "/api/vision/capture":
                    self._send_json(state.capture_vision_once())
                    return
```

- [ ] **Step 6: Verify and commit**

Run:

```text
python -B -m unittest tests.test_workbench_web.WorkbenchVisionApiTest
python -B -m unittest tests.test_workbench_web
```

Expected: both PASS.

Commit:

```text
git add summer_camp_agent/workbench_web.py tests/test_workbench_web.py
git commit -m "feat: expose wechat vision api"
```

## 任务 6：桌面端接入真实工作台 API 并验证

**Files:**
- Modify: `desktop/src/renderer/App.tsx`
- Modify: `desktop/tests/static.test.mjs`
- Modify: `scripts/start_desktop_app.ps1`
- Modify: `docs/README.md`

- [ ] **Step 1: Write failing entrypoint/documentation tests**

Append to `desktop/tests/static.test.mjs`:

```js
test('desktop product no longer presents the browser workbench as the user entry', () => {
  const app = read('src/renderer/App.tsx')

  assert.match(app, /启动视觉观察/)
  assert.match(app, /识别当前窗口/)
  assert.match(app, /工作轨迹/)
  assert.doesNotMatch(app, /高级工作台页面会承接旧浏览器工作台能力/)
})
```

- [ ] **Step 2: Run desktop tests**

Run:

```text
npm.cmd --prefix desktop test
```

Expected: PASS if Task 2 already removed the old placeholder; otherwise FAIL and point to remaining placeholder text.

- [ ] **Step 3: Update launcher comments and README**

Modify `docs/README.md` to include this Chinese section:

```markdown
## 桌面版入口

当前产品以 Electron 桌面版作为唯一用户入口。桌面版包含消息流、决策面板、回复草稿、候选库、工作轨迹和微信 PC 半自动辅助回复能力。

本地网页服务仅作为 Electron 后端兼容层，不再作为日常使用入口。启动方式：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/start_desktop_app.ps1
```

微信 PC 半自动模式只会识别消息、生成草稿并填入输入框，不会自动发送。用户需要在微信中检查并手动发送，然后回到桌面版点击“我已发送”记录结果。
```

Modify `scripts/start_desktop_app.ps1` only if it still prints or comments that point users to the browser workbench. Keep the Electron startup behavior unchanged.

- [ ] **Step 4: Run full verification**

Run:

```text
python -B -m unittest tests.test_wechat_window tests.test_wechat_assisted_paste tests.test_wechat_vision tests.test_workbench_web
npm.cmd --prefix desktop test
npm.cmd --prefix desktop run typecheck
```

Expected: all PASS.

- [ ] **Step 5: Manual smoke test**

Run:

```text
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/start_desktop_app.ps1
```

Expected:

- Electron desktop window opens.
- Main window shows the unified workbench.
- “启动视觉观察” does not crash.
- “生成草稿” can generate a reply for `报名入口在哪里？`.
- “填入微信” never sends the message automatically.

- [ ] **Step 6: Commit**

```text
git add desktop/src/renderer/App.tsx desktop/tests/static.test.mjs scripts/start_desktop_app.ps1 docs/README.md
git commit -m "docs: make desktop the product entry"
```

## 自检清单

- [ ] 设计文档中的“桌面版合并网页版能力”由任务 1、2、6 覆盖。
- [ ] “微信 PC 半自动增强”由任务 3、4、5 覆盖。
- [ ] “不自动发送”由任务 3 的测试和安全边界覆盖。
- [ ] “视觉识别去重”由任务 4 覆盖。
- [ ] “工作轨迹、候选库、日志”通过复用 `WorkbenchSession` 和任务 5 的事件入流覆盖。
- [ ] 没有要求第一版选择具体视觉模型供应商。
- [ ] 没有引入微信 hook、数据库读取或进程注入。
