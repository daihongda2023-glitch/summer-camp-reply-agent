import { app, BrowserWindow, ipcMain } from 'electron'
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { AppSettingsPayload, AppStatus, DesktopSettings } from '../shared/types'

const __dirname = fileURLToPath(new URL('.', import.meta.url))
const repoRoot = resolve(__dirname, '..', '..', '..')
const rendererDevUrl = process.env.ELECTRON_RENDERER_URL || 'http://127.0.0.1:5178'
const MAIN_WINDOW_OPTIONS = { width: 380, height: 680, minWidth: 360, minHeight: 560 }
const SETTINGS_WINDOW_OPTIONS = { width: 900, height: 720, minWidth: 820, minHeight: 620 }
const WINDOW_TITLES = {
  main: '夏令营 Agent',
  settings: '设置 - 夏令营 Agent',
  advanced: '高级工作台 - 夏令营 Agent'
}

class PythonService {
  private process: ChildProcessWithoutNullStreams | null = null
  private startPromise: Promise<void> | null = null
  private baseUrl = ''
  private status: AppStatus['engine']['status'] = 'idle'
  private logs: string[] = []

  async ensureStarted(): Promise<void> {
    if (this.process && this.status === 'running') return
    if (this.startPromise) return this.startPromise
    this.startPromise = this.start()
    try {
      await this.startPromise
    } finally {
      this.startPromise = null
    }
  }

  private async start(): Promise<void> {
    this.status = 'starting'
    const python = process.env.SUMMER_CAMP_AGENT_PYTHON || 'python'
    this.process = spawn(python, ['-B', '-m', 'summer_camp_agent.workbench_server', '--port', '0'], {
      cwd: repoRoot,
      env: { ...process.env },
      windowsHide: true
    })
    this.process.stdout.on('data', (chunk) => this.captureOutput(String(chunk)))
    this.process.stderr.on('data', (chunk) => this.pushLog(String(chunk).trim()))
    this.process.on('exit', () => {
      this.status = 'idle'
      this.process = null
      this.startPromise = null
    })
    await this.waitUntilReady()
  }

  stop(): void {
    this.process?.kill()
    this.process = null
    this.status = 'idle'
    this.pushLog('Python 本地服务已停止')
  }

  async getStatus(): Promise<AppStatus> {
    if (this.status === 'running') {
      try {
        const payload = await this.request<AppStatus>('/api/app/status')
        return { ...payload, recent_logs: [...payload.recent_logs, ...this.logs].slice(-20) }
      } catch {
        this.status = 'error'
      }
    }
    return {
      engine: { status: this.status, listener_running: false, group_name: '未连接' },
      settings: defaultSettings(),
      recent_logs: this.logs.slice(-20)
    }
  }

  async startEngine(): Promise<AppStatus> {
    await this.ensureStarted()
    return this.request<AppStatus>('/api/app/start', {})
  }

  async stopEngine(): Promise<AppStatus> {
    if (this.status === 'running') {
      await this.request<AppStatus>('/api/app/stop', {})
    }
    return this.getStatus()
  }

  async getSettings(): Promise<AppSettingsPayload> {
    await this.ensureStarted()
    return this.request<AppSettingsPayload>('/api/app/settings')
  }

  async saveSettings(settings: Partial<DesktopSettings>): Promise<AppSettingsPayload> {
    await this.ensureStarted()
    return this.request<AppSettingsPayload>('/api/app/settings', settings)
  }

  private captureOutput(text: string): void {
    for (const line of text.split(/\r?\n/)) {
      if (!line.trim()) continue
      if (line.startsWith('WORKBENCH_URL=')) {
        this.baseUrl = line.slice('WORKBENCH_URL='.length).trim()
        this.status = 'running'
      }
      this.pushLog(line)
    }
  }

  private pushLog(line: string): void {
    if (!line) return
    this.logs.push(line)
    this.logs = this.logs.slice(-40)
  }

  private async waitUntilReady(): Promise<void> {
    const deadline = Date.now() + 12_000
    while (Date.now() < deadline) {
      if (this.status === 'running') return
      await new Promise((resolve) => setTimeout(resolve, 120))
    }
    this.status = 'error'
    throw new Error('Python 本地服务启动超时')
  }

  private async request<T>(path: string, body?: unknown): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method: body === undefined ? 'GET' : 'POST',
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body)
    })
    if (!response.ok) {
      throw new Error(await response.text())
    }
    return response.json() as Promise<T>
  }
}

const service = new PythonService()
let mainWindow: BrowserWindow | null = null
let settingsWindow: BrowserWindow | null = null
let advancedWindow: BrowserWindow | null = null

function defaultSettings(): DesktopSettings {
  return {
    window: { width: 380, height: 680, min_width: 360, min_height: 560, settings_width: 900, settings_height: 720 },
    main_view: {
      show_target: true,
      show_recent_logs: true,
      show_history_entry: true,
      show_status_detail: false,
      show_assist_actions: false
    },
    advanced_pages: { messages: true, candidates: true, work_trace: true, rag: false }
  }
}

function createWindow(kind: 'main' | 'settings' | 'advanced', page = ''): BrowserWindow {
  const isSettings = kind === 'settings'
  const isAdvanced = kind === 'advanced'
  const size = isSettings || isAdvanced ? SETTINGS_WINDOW_OPTIONS : MAIN_WINDOW_OPTIONS
  const win = new BrowserWindow({
    title: WINDOW_TITLES[kind],
    width: size.width,
    height: size.height,
    minWidth: size.minWidth,
    minHeight: size.minHeight,
    show: false,
    autoHideMenuBar: true,
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'hidden',
    titleBarOverlay: process.platform === 'darwin' ? undefined : { color: '#090a0f', symbolColor: '#f3f4f8', height: 42 },
    backgroundColor: '#090a0f',
    webPreferences: {
      preload: join(__dirname, '../preload/preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false
    }
  })
  win.once('ready-to-show', () => win.show())
  const query = new URLSearchParams({ window: kind, page }).toString()
  if (!app.isPackaged) {
    win.loadURL(`${rendererDevUrl}?${query}`)
  } else {
    win.loadFile(join(__dirname, '../renderer/index.html'), { query: { window: kind, page } })
  }
  return win
}

app.whenReady().then(() => {
  ipcMain.handle('app:getStatus', () => service.getStatus())
  ipcMain.handle('app:start', () => service.startEngine())
  ipcMain.handle('app:stop', () => service.stopEngine())
  ipcMain.handle('app:getSettings', () => service.getSettings())
  ipcMain.handle('app:saveSettings', (_event, settings: Partial<DesktopSettings>) => service.saveSettings(settings))
  ipcMain.handle('settings:open', () => {
    if (!settingsWindow || settingsWindow.isDestroyed()) settingsWindow = createWindow('settings')
    if (settingsWindow.isMinimized()) settingsWindow.restore()
    settingsWindow.show()
    settingsWindow.focus()
  })
  ipcMain.handle('advanced:open', (_event, page: string) => {
    if (!advancedWindow || advancedWindow.isDestroyed()) advancedWindow = createWindow('advanced', page)
    if (advancedWindow.isMinimized()) advancedWindow.restore()
    advancedWindow.show()
    advancedWindow.focus()
  })

  mainWindow = createWindow('main')
})

app.on('window-all-closed', () => {
  service.stop()
  if (process.platform !== 'darwin') app.quit()
})
