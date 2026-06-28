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
  assert.match(css, /--accent:\s*#18c28b/)
  assert.match(css, /\.controller-shell/)
  assert.match(css, /width:\s*100vw/)
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
