import { app, BrowserWindow, ipcMain, Menu, nativeImage, Notification, shell, Tray } from 'electron'
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import type {
  ActionResult,
  AppSettingsPayload,
  AppSettingsUpdate,
  AppStatus,
  DesktopSettings,
  MessageScope,
  PasteReplyResult,
  ReadinessPayload,
  ReviewStatus,
  VisionCapturePayload,
  VisionStatus,
  WorkbenchItemPayload,
  WorkbenchItemsPayload,
  WorkTracePayload
} from '../shared/types'

const __dirname = fileURLToPath(new URL('.', import.meta.url))
const repoRoot = resolve(__dirname, '..', '..', '..')
const rendererDevUrl = process.env.ELECTRON_RENDERER_URL || 'http://127.0.0.1:5178'
const MAIN_WINDOW_OPTIONS = { width: 1180, height: 760, minWidth: 960, minHeight: 680 }
const SETTINGS_WINDOW_OPTIONS = { width: 900, height: 720, minWidth: 820, minHeight: 620 }
const WINDOW_TITLES = {
  main: '夏令营 Agent',
  settings: '设置 - 夏令营 Agent',
  advanced: '工作轨迹 - 夏令营 Agent'
}

class PythonService {
  private process: ChildProcessWithoutNullStreams | null = null
  private startPromise: Promise<void> | null = null
  private baseUrl = ''
  private status: AppStatus['engine']['status'] = 'idle'
  private logs: string[] = []
  private itemPollTimer: ReturnType<typeof setTimeout> | null = null
  private itemPollInFlight = false
  private nextItemPollDelayMs = 5_000
  private itemFetchPromise: Promise<WorkbenchItemsPayload> | null = null
  private pendingCountInitialized = false
  private lastPendingCount = 0

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
      this.stopItemPolling()
      this.status = 'idle'
      this.process = null
      this.startPromise = null
    })
    await this.waitUntilReady()
    this.scheduleItemPoll(0)
  }

  stop(): void {
    this.stopItemPolling()
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
      } catch (error) {
        this.status = 'error'
        notifyServiceError(errorMessage(error))
      }
    }
    return {
      engine: {
        status: this.status,
        listener_running: false,
        group_name: '未连接',
        send_mode: 'manual_confirm',
        poll_interval_seconds: 5,
        debug_review_mode: true
      },
      settings: defaultSettings(),
      recent_logs: this.logs.slice(-20)
    }
  }

  async startEngine(): Promise<AppStatus> {
    await this.ensureStarted()
    return this.request<AppStatus>('/api/app/start', {})
  }

  async stopEngine(): Promise<AppStatus> {
    if (this.status === 'running') await this.request<AppStatus>('/api/app/stop', {})
    return this.getStatus()
  }

  async getSettings(): Promise<AppSettingsPayload> {
    await this.ensureStarted()
    return this.request<AppSettingsPayload>('/api/app/settings')
  }

  async getReadiness(): Promise<ReadinessPayload> {
    await this.ensureStarted()
    return this.request<ReadinessPayload>('/api/app/readiness')
  }

  async saveSettings(settings: AppSettingsUpdate): Promise<AppSettingsPayload> {
    await this.ensureStarted()
    return this.request<AppSettingsPayload>('/api/app/settings', settings)
  }

  async getWorkTrace(): Promise<WorkTracePayload> {
    await this.ensureStarted()
    return this.request<WorkTracePayload>('/api/app/work-trace')
  }

  async loadDemo(): Promise<void> {
    await this.ensureStarted()
    await this.request('/api/demo')
  }

  async getItems(
    scope: MessageScope = 'pending',
    reviewStatus: ReviewStatus | '' = ''
  ): Promise<WorkbenchItemsPayload> {
    await this.ensureStarted()
    if (scope !== 'pending' || reviewStatus) {
      const query = `?scope=${encodeURIComponent(scope)}&review_status=${encodeURIComponent(reviewStatus)}`
      return this.request<WorkbenchItemsPayload>(`/api/items${query}`)
    }
    return this.fetchItems()
  }

  async ask(question: string): Promise<WorkbenchItemPayload> {
    await this.ensureStarted()
    return this.request<WorkbenchItemPayload>('/api/ask', { question })
  }

  async pasteReply(eventId: string, reply: string): Promise<PasteReplyResult> {
    await this.ensureStarted()
    return this.request<PasteReplyResult>('/api/wechat/paste', { event_id: eventId, reply })
  }

  async publishReply(eventId: string, reply: string): Promise<PasteReplyResult> {
    await this.ensureStarted()
    return this.request<PasteReplyResult>('/api/wechat/publish', { event_id: eventId, reply })
  }

  async confirmSent(eventId: string, reply: string): Promise<ActionResult> {
    await this.ensureStarted()
    return this.request<ActionResult>('/api/wechat/confirm-sent', { event_id: eventId, reply })
  }

  async saveCandidate(eventId: string, reply: string): Promise<ActionResult> {
    await this.ensureStarted()
    return this.request<ActionResult>('/api/save-candidate', { event_id: eventId, reply })
  }

  async escalateMessage(eventId: string, note: string): Promise<ActionResult> {
    await this.ensureStarted()
    return this.request<ActionResult>('/api/messages/escalate', { event_id: eventId, note })
  }

  async completeReview(eventId: string, note: string): Promise<ActionResult> {
    await this.ensureStarted()
    return this.request<ActionResult>('/api/messages/complete-review', { event_id: eventId, note })
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

  private captureOutput(text: string): void {
    for (const line of text.split(/\r?\n/)) {
      if (!line.trim()) continue
      if (line.startsWith('WORKBENCH_API_URL=')) {
        this.baseUrl = line.slice('WORKBENCH_API_URL='.length).trim()
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

  private scheduleItemPoll(delayMs = this.nextItemPollDelayMs): void {
    this.stopItemPolling()
    if (!this.process || this.status !== 'running') return
    this.itemPollTimer = setTimeout(() => {
      this.itemPollTimer = null
      void this.pollItemsInBackground()
    }, Math.max(0, delayMs))
  }

  private stopItemPolling(): void {
    if (this.itemPollTimer === null) return
    clearTimeout(this.itemPollTimer)
    this.itemPollTimer = null
  }

  private async pollItemsInBackground(): Promise<void> {
    if (this.itemPollInFlight || !this.process || this.status !== 'running') {
      this.scheduleItemPoll()
      return
    }
    this.itemPollInFlight = true
    try {
      const payload = await this.request<AppStatus>('/api/app/status')
      this.nextItemPollDelayMs = Math.max(2_000, payload.engine.poll_interval_seconds * 1000)
      if (payload.engine.listener_running) await this.fetchItems()
    } catch (error) {
      const message = errorMessage(error)
      this.pushLog(`后台监听轮询失败：${message}`)
      notifyServiceError(message)
    } finally {
      this.itemPollInFlight = false
      this.scheduleItemPoll()
    }
  }

  private async fetchItems(): Promise<WorkbenchItemsPayload> {
    if (this.itemFetchPromise) return this.itemFetchPromise
    const request = this.request<WorkbenchItemsPayload>('/api/items')
    this.itemFetchPromise = request
    try {
      const payload = await request
      const nextCount = payload.items.length
      if (this.pendingCountInitialized && nextCount > this.lastPendingCount) {
        notifyReviewNeeded(nextCount - this.lastPendingCount)
      }
      this.pendingCountInitialized = true
      this.lastPendingCount = nextCount
      return payload
    } finally {
      if (this.itemFetchPromise === request) this.itemFetchPromise = null
    }
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
    if (!response.ok) throw new Error(await response.text())
    return response.json() as Promise<T>
  }
}

const service = new PythonService()
let mainWindow: BrowserWindow | null = null
let settingsWindow: BrowserWindow | null = null
let advancedWindow: BrowserWindow | null = null
let tray: Tray | null = null
let isQuitting = false
let lastErrorNotification = { message: '', at: 0 }

function defaultSettings(): DesktopSettings {
  return {
    window: { width: 1180, height: 760, min_width: 960, min_height: 680, settings_width: 900, settings_height: 720 },
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
  const size = kind === 'main' ? MAIN_WINDOW_OPTIONS : SETTINGS_WINDOW_OPTIONS
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
  if (!app.isPackaged) win.loadURL(`${rendererDevUrl}?${query}`)
  else win.loadFile(join(__dirname, '../renderer/index.html'), { query: { window: kind, page } })
  return win
}

function showMainWindow(): void {
  if (!mainWindow || mainWindow.isDestroyed()) mainWindow = createWindow('main')
  if (mainWindow.isMinimized()) mainWindow.restore()
  mainWindow.show()
  mainWindow.focus()
}

function showSettingsWindow(): void {
  if (!settingsWindow || settingsWindow.isDestroyed()) settingsWindow = createWindow('settings')
  if (settingsWindow.isMinimized()) settingsWindow.restore()
  settingsWindow.show()
  settingsWindow.focus()
}

function createTray(): void {
  if (tray) return
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><rect width="32" height="32" rx="7" fill="#18c28b"/><path d="M8 10h16v10H14l-5 4v-4H8z" fill="#07130f"/></svg>'
  const icon = nativeImage
    .createFromDataURL(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`)
    .resize({ width: 16, height: 16 })
  tray = new Tray(icon)
  tray.setToolTip('夏令营 Agent')
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: '显示工作台', click: showMainWindow },
    { label: '打开设置', click: showSettingsWindow },
    { type: 'separator' },
    { label: '退出', click: () => { isQuitting = true; app.quit() } }
  ]))
  tray.on('double-click', showMainWindow)
}

function showNotification(title: string, body: string): void {
  if (!Notification.isSupported()) return
  new Notification({ title, body, silent: false }).show()
}

function notifyReviewNeeded(count: number): void {
  showNotification('新增待审核消息', `有 ${count} 条新消息需要你确认。`)
}

function notifyServiceError(message: string): void {
  const now = Date.now()
  if (lastErrorNotification.message === message && now - lastErrorNotification.at < 60_000) return
  lastErrorNotification = { message, at: now }
  showNotification('夏令营 Agent 服务异常', message)
}

async function openExternal(url: string): Promise<void> {
  const target = new URL(url)
  if (!/^https?:$/.test(target.protocol)) throw new Error('只允许打开 http 或 https 来源链接')
  await shell.openExternal(target.toString())
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

app.whenReady().then(() => {
  ipcMain.handle('app:getStatus', () => service.getStatus())
  ipcMain.handle('app:getReadiness', () => service.getReadiness())
  ipcMain.handle('app:start', () => service.startEngine())
  ipcMain.handle('app:stop', () => service.stopEngine())
  ipcMain.handle('app:getSettings', () => service.getSettings())
  ipcMain.handle('app:saveSettings', (_event, settings: AppSettingsUpdate) => service.saveSettings(settings))
  ipcMain.handle('app:getWorkTrace', () => service.getWorkTrace())
  ipcMain.handle('app:loadDemo', () => service.loadDemo())
  ipcMain.handle('app:openExternal', (_event, url: string) => openExternal(url))
  ipcMain.handle(
    'workbench:getItems',
    (_event, scope: MessageScope = 'pending', reviewStatus: ReviewStatus | '' = '') => service.getItems(scope, reviewStatus)
  )
  ipcMain.handle('workbench:ask', (_event, question: string) => service.ask(question))
  ipcMain.handle('workbench:pasteReply', (_event, eventId: string, reply: string) => service.pasteReply(eventId, reply))
  ipcMain.handle('workbench:publishReply', (_event, eventId: string, reply: string) => service.publishReply(eventId, reply))
  ipcMain.handle('workbench:confirmSent', (_event, eventId: string, reply: string) => service.confirmSent(eventId, reply))
  ipcMain.handle('workbench:saveCandidate', (_event, eventId: string, reply: string) => service.saveCandidate(eventId, reply))
  ipcMain.handle('workbench:escalateMessage', (_event, eventId: string, note: string) => service.escalateMessage(eventId, note))
  ipcMain.handle('workbench:completeReview', (_event, eventId: string, note: string) => service.completeReview(eventId, note))
  ipcMain.handle('vision:start', () => service.startVision())
  ipcMain.handle('vision:stop', () => service.stopVision())
  ipcMain.handle('vision:capture', () => service.captureVision())
  ipcMain.handle('vision:getStatus', () => service.getVisionStatus())
  ipcMain.handle('settings:open', showSettingsWindow)
  ipcMain.handle('advanced:open', (_event, page: string) => {
    if (!advancedWindow || advancedWindow.isDestroyed()) advancedWindow = createWindow('advanced', page)
    if (advancedWindow.isMinimized()) advancedWindow.restore()
    advancedWindow.show()
    advancedWindow.focus()
  })

  mainWindow = createWindow('main')
  mainWindow.on('close', (event) => {
    if (isQuitting) return
    event.preventDefault()
    if (mainWindow) mainWindow.hide()
  })
  createTray()
})

app.on('window-all-closed', () => {
  // 主窗口关闭后驻留系统托盘，继续监听微信。
})

app.on('activate', showMainWindow)

app.on('before-quit', () => {
  isQuitting = true
  service.stop()
})
