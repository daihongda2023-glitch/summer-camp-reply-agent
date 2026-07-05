import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const read = (file) => readFileSync(join(root, file), 'utf8')

test('main process defines narrow controller and independent settings window', () => {
  const source = read('src/main/main.ts')

  assert.match(source, /width:\s*380/)
  assert.match(source, /height:\s*680/)
  assert.match(source, /minWidth:\s*360/)
  assert.match(source, /width:\s*900/)
  assert.match(source, /height:\s*720/)
  assert.match(source, /titleBarOverlay/)
  assert.match(source, /设置 - 夏令营 Agent/)
  assert.match(source, /--port', '0'/)
  assert.match(source, /startPromise/)
  assert.match(source, /ipcMain\.handle\('settings:open'/)
  assert.match(source, /ipcMain\.handle\('app:getWorkTrace'/)
  assert.match(source, /\/api\/app\/work-trace/)
})

test('preload exposes a narrow desktop api instead of raw ipc', () => {
  const source = read('src/preload/preload.ts')
  const cjsSource = read('src/preload/preload.cjs')
  const packageJson = read('package.json')

  assert.match(source, /contextBridge\.exposeInMainWorld\('desktop'/)
  assert.match(cjsSource, /contextBridge\.exposeInMainWorld\('desktop'/)
  assert.match(cjsSource, /require\('electron'\)/)
  assert.match(packageJson, /copy-preload\.cjs/)
  assert.match(source, /getStatus/)
  assert.match(source, /getSettings/)
  assert.match(source, /saveSettings/)
  assert.match(source, /getWorkTrace/)
  assert.match(source, /loadDemo/)
  assert.doesNotMatch(source, /exposeInMainWorld\('electron'/)
})

test('main process loads the commonjs preload bundle', () => {
  const source = read('src/main/main.ts')

  assert.match(source, /preload\.cjs/)
  assert.ok(existsSync(join(root, 'scripts/copy-preload.cjs')))
})

test('renderer contains controller, settings, and advanced page surfaces', () => {
  const app = read('src/renderer/App.tsx')
  const css = read('src/renderer/styles.css')

  assert.match(app, /夏令营 Agent/)
  assert.match(app, /document\.title/)
  assert.match(app, /设置 - 夏令营 Agent/)
  assert.match(app, /启动引擎/)
  assert.match(app, /配置/)
  assert.match(app, /消息处理/)
  assert.match(app, /候选库/)
  assert.match(app, /工作轨迹/)
  assert.match(app, /WorkTracePage/)
  assert.match(app, /getWorkTrace/)
  assert.match(app, /载入演示/)
  assert.match(app, /结构化详情/)
  assert.match(css, /--accent:\s*#18c28b/)
  assert.match(css, /\.controller-shell/)
  assert.match(css, /width:\s*100vw/)
  assert.match(css, /\.trace-workspace/)
  assert.match(css, /\.phase-pill/)
})

test('settings page edits wechat bridge group keywords and polling interval', () => {
  const app = read('src/renderer/App.tsx')
  const types = read('src/shared/types.ts')

  assert.match(types, /interface WeChatBridgeSettings/)
  assert.match(types, /saveSettings\(settings: AppSettingsUpdate\)/)
  assert.match(app, /value=\{wechatForm\.group_name\}/)
  assert.match(app, /value=\{wechatForm\.keywordsText\}/)
  assert.match(app, /value=\{wechatForm\.poll_interval_seconds\}/)
  assert.match(app, /saveWechatSettings/)
  assert.match(app, /wechat:\s*\{/)
  assert.match(app, /监听关键字/)
  assert.match(app, /保存微信桥接/)
})

test('controller layout is constrained for a narrow desktop window', () => {
  const css = read('src/renderer/styles.css')

  assert.match(css, /\.controller-shell\s*{[^}]*display:\s*flex/s)
  assert.match(css, /\.controller-shell\s*{[^}]*min-width:\s*0/s)
  assert.match(css, /\.panel\s*{[^}]*min-width:\s*0/s)
  assert.match(css, /\.log-panel\s*{[^}]*flex:\s*1/s)
  assert.match(css, /\.bottom-bar\s*{[^}]*flex-shrink:\s*0/s)
  assert.match(css, /-webkit-app-region:\s*drag/)
})

test('ipc handlers are registered before the renderer window is created', () => {
  const source = read('src/main/main.ts')
  const readyBlock = source.slice(source.indexOf('app.whenReady().then'))
  const firstHandler = readyBlock.indexOf("ipcMain.handle('settings:open'")
  const firstWindow = readyBlock.indexOf("mainWindow = createWindow('main')")

  assert.ok(firstHandler >= 0)
  assert.ok(firstWindow >= 0)
  assert.ok(firstHandler < firstWindow)
})

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
    assert.match(types, new RegExp(`${name}\\(`))
    assert.match(preload, new RegExp(`${name}:`))
  }

  assert.match(main, /ipcMain\.handle\('workbench:getItems'/)
  assert.match(main, /ipcMain\.handle\('vision:capture'/)
  assert.match(main, /\/api\/items/)
  assert.match(main, /\/api\/vision\/capture/)
})

test('renderer main window contains the unified desktop workbench', () => {
  const app = read('src/renderer/App.tsx')
  const css = read('src/renderer/styles.css')

  assert.match(app, /DesktopWorkbench/)
  assert.match(app, /处理流程/)
  assert.match(app, /观察并获取待回复消息/)
  assert.match(app, /选择待处理消息/)
  assert.match(app, /确认回复草稿/)
  assert.match(app, /选中消息详情/)
  assert.match(app, /填入微信/)
  assert.match(app, /我已发送/)
  assert.match(app, /保存候选/)
  assert.match(app, /启动观察/)
  assert.match(app, /captureVision/)
  assert.match(css, /\.workbench-shell/)
  assert.match(css, /grid-template-columns:\s*232px minmax\(520px,\s*1fr\) 320px/)
  assert.match(css, /\.workflow-panel/)
  assert.doesNotMatch(app, /openAdvanced\('messages'\)/)
})

test('desktop product no longer presents the browser workbench as the user entry', () => {
  const app = read('src/renderer/App.tsx')

  assert.match(app, /启动视觉观察/)
  assert.match(app, /识别当前窗口/)
  assert.match(app, /工作轨迹/)
  assert.doesNotMatch(app, /高级工作台页面会承接旧浏览器工作台能力/)
})

test('workbench layout has responsive narrow and wide viewport rules', () => {
  const app = read('src/renderer/App.tsx')
  const css = read('src/renderer/styles.css')

  assert.match(app, /empty-message-state/)
  assert.match(css, /grid-template-columns:\s*232px minmax\(520px,\s*1fr\) 320px/)
  assert.match(css, /grid-template-rows:\s*auto auto minmax\(0,\s*1fr\) minmax\(180px,\s*24vh\)/)
  assert.match(css, /\.primary-action\.compact\s*{[^}]*flex:\s*0 0 auto/s)
  assert.match(css, /@media \(max-width:\s*1180px\)/)
  assert.match(css, /@media \(max-width:\s*960px\)/)
  assert.match(css, /grid-template-columns:\s*1fr/)
  assert.match(css, /\.workflow-panel\s*{[^}]*overflow:\s*visible/s)
  assert.match(css, /\.workbench-shell\s*{[^}]*overflow:\s*auto/s)
})

test('workbench button actions surface missing ipc and service errors', () => {
  const app = read('src/renderer/App.tsx')

  assert.match(app, /getDesktopMethod/)
  assert.match(app, /runAction\('正在启动视觉观察\.\.\.'/)
  assert.match(app, /runAction\('正在识别当前窗口\.\.\.'/)
  assert.match(app, /runAction\('正在停止观察\.\.\.'/)
  assert.match(app, /桌面主进程尚未加载/)
  assert.match(app, /请完全退出并重新启动桌面版/)
  assert.match(app, /errorMessage\(error\)/)
})
