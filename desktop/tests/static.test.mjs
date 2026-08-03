import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const read = (file) => readFileSync(join(root, file), 'utf8')

test('主进程使用完整工作台窗口并保留独立设置窗口', () => {
  const source = read('src/main/main.ts')

  assert.match(source, /width:\s*1180/)
  assert.match(source, /height:\s*760/)
  assert.match(source, /minWidth:\s*960/)
  assert.match(source, /minHeight:\s*680/)
  assert.match(source, /width:\s*900/)
  assert.match(source, /titleBarOverlay/)
  assert.match(source, /--port', '0'/)
  assert.match(source, /startPromise/)
})

test('主进程提供托盘、有限通知和安全外链', () => {
  const source = read('src/main/main.ts')

  assert.match(source, /\bTray\b/)
  assert.match(source, /\bNotification\b/)
  assert.match(source, /new Notification/)
  assert.match(source, /新增待审核消息/)
  assert.match(source, /shell\.openExternal/)
  assert.match(source, /https\?:/)
  assert.match(source, /ipcMain\.handle\('app:openExternal'/)
  assert.match(source, /mainWindow\.hide\(\)/)
})

test('预加载层只暴露收窄后的桌面能力', () => {
  const source = read('src/preload/preload.ts')
  const cjsSource = read('src/preload/preload.cjs')

  for (const value of ['getReadiness', 'openExternal', 'getItems', 'publishReply', 'startVision']) {
    assert.match(source, new RegExp(`${value}:`))
    assert.match(cjsSource, new RegExp(`${value}:`))
  }
  assert.match(source, /contextBridge\.exposeInMainWorld\('desktop'/)
  assert.doesNotMatch(source, /exposeInMainWorld\('electron'/)
  assert.ok(existsSync(join(root, 'scripts/copy-preload.cjs')))
})

test('共享类型定义三种运行模式和就绪检查', () => {
  const source = read('src/shared/types.ts')

  assert.match(source, /OperationProfile/)
  assert.match(source, /'safe_review'/)
  assert.match(source, /'assisted'/)
  assert.match(source, /'automatic'/)
  assert.match(source, /interface ReadinessCheck/)
  assert.match(source, /interface ReadinessPayload/)
  assert.match(source, /getReadiness\(\)/)
  assert.match(source, /openExternal\(url: string\)/)
})

test('UX 纯函数集中处理模式、置信度、搜索和主操作', () => {
  const source = read('src/renderer/workbench-ux.ts')

  for (const name of [
    'resolveOperationProfile',
    'applyOperationProfile',
    'confidenceLevel',
    'recommendedPrimaryAction',
    'filterWorkbenchItems',
    'extractSafeSourceUrl'
  ]) {
    assert.match(source, new RegExp(`function ${name}`))
  }
  assert.match(source, /安全试运行/)
  assert.match(source, /人工辅助/)
  assert.match(source, /自动回复/)
  assert.match(source, /高/)
  assert.match(source, /中/)
  assert.match(source, /低/)
})

test('工作台提供运行检查、搜索、单主操作和折叠详情', () => {
  const app = read('src/renderer/App.tsx')
  const css = read('src/renderer/styles.css')

  assert.match(app, /运行检查/)
  assert.match(app, /开始观察|停止观察/)
  assert.match(app, /搜索消息/)
  assert.match(app, /更多操作/)
  assert.match(app, /技术详情/)
  assert.match(app, /Ctrl\+Enter/)
  assert.match(app, /busyAction/)
  assert.match(app, /aria-live="polite"/)
  assert.match(app, /openExternal/)
  assert.doesNotMatch(app, /旧规则/)
  assert.match(css, /\.readiness-card/)
  assert.match(css, /\.queue-search/)
  assert.match(css, /\.more-actions/)
  assert.match(css, /\.toast/)
})

test('工作台轮询监听消息并支持待处理和历史记录', () => {
  const app = read('src/renderer/App.tsx')

  assert.match(app, /vision\.running/)
  assert.match(app, /window\.setInterval/)
  assert.match(app, /messageScope/)
  assert.match(app, /reviewStatusFilter/)
  assert.match(app, /待处理/)
  assert.match(app, /历史记录/)
  assert.match(app, /filterWorkbenchItems/)
})

test('设置页只突出基础设置并折叠高级参数', () => {
  const app = read('src/renderer/App.tsx')
  const ux = read('src/renderer/workbench-ux.ts')
  const settingsWindow = app.slice(app.indexOf('function SettingsWindow'), app.indexOf('function WorkTracePage'))

  assert.match(app, /基础设置/)
  assert.match(app, /高级参数/)
  assert.match(app, /operationProfile/)
  assert.match(ux, /安全试运行/)
  assert.match(ux, /人工辅助/)
  assert.match(ux, /自动回复/)
  assert.match(app, /保存设置/)
  assert.doesNotMatch(settingsWindow, /show_assist_actions/)
  assert.doesNotMatch(settingsWindow, /openAdvanced\('messages'\)/)
  assert.doesNotMatch(settingsWindow, /openAdvanced\('candidates'\)/)
  assert.doesNotMatch(settingsWindow, /openAdvanced\('rag'\)/)
})

test('IPC 在窗口创建前注册并持续后台轮询', () => {
  const source = read('src/main/main.ts')
  const readyBlock = source.slice(source.indexOf('app.whenReady().then'))
  const firstHandler = readyBlock.indexOf("ipcMain.handle('settings:open'")
  const firstWindow = readyBlock.indexOf("mainWindow = createWindow('main')")

  assert.ok(firstHandler >= 0)
  assert.ok(firstWindow >= 0)
  assert.ok(firstHandler < firstWindow)
  assert.match(source, /scheduleItemPoll/)
  assert.match(source, /pollItemsInBackground/)
  assert.match(source, /private itemFetchPromise/)
})

test('工作台保留发送、转人工和完成审核的完整 IPC 链路', () => {
  const types = read('src/shared/types.ts')
  const preload = read('src/preload/preload.ts')
  const main = read('src/main/main.ts')

  for (const name of [
    'pasteReply',
    'publishReply',
    'confirmSent',
    'saveCandidate',
    'escalateMessage',
    'completeReview'
  ]) {
    assert.match(types, new RegExp(`${name}\\(`))
    assert.match(preload, new RegExp(`${name}:`))
  }
  assert.match(main, /\/api\/wechat\/publish/)
  assert.match(main, /\/api\/messages\/escalate/)
  assert.match(main, /\/api\/messages\/complete-review/)
})

test('生产构建仍使用 CommonJS 预加载文件', () => {
  const source = read('src/main/main.ts')
  const packageJson = read('package.json')

  assert.match(source, /preload\.cjs/)
  assert.match(packageJson, /copy-preload\.cjs/)
})
