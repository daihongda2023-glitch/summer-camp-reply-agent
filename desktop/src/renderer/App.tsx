import { useEffect, useMemo, useState } from 'react'
import type { AppSettingsPayload, AppStatus, DesktopSettings } from '../shared/types'

const fallbackSettings: DesktopSettings = {
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

const fallbackStatus: AppStatus = {
  engine: { status: 'idle', listener_running: false, group_name: '未连接' },
  settings: fallbackSettings,
  recent_logs: ['引擎尚未启动']
}

function App() {
  const params = new URLSearchParams(window.location.search)
  const windowKind = params.get('window') || 'main'
  const page = params.get('page') || 'messages'
  const [status, setStatus] = useState<AppStatus>(fallbackStatus)

  useEffect(() => {
    document.title = {
      main: '夏令营 Agent',
      settings: '设置 - 夏令营 Agent',
      advanced: '高级工作台 - 夏令营 Agent'
    }[windowKind] ?? '夏令营 Agent'
  }, [windowKind])

  useEffect(() => {
    void refresh()
    const timer = window.setInterval(refresh, 3000)
    return () => window.clearInterval(timer)
  }, [])

  async function refresh() {
    try {
      setStatus(await window.desktop.getStatus())
    } catch {
      setStatus((current) => ({ ...current, engine: { ...current.engine, status: 'error' } }))
    }
  }

  if (windowKind === 'settings') return <SettingsWindow />
  if (windowKind === 'advanced') return <AdvancedWindow page={page} />
  return <Controller status={status} onRefresh={refresh} />
}

function Controller({ status, onRefresh }: { status: AppStatus; onRefresh: () => Promise<void> }) {
  const running = status.engine.status === 'running'
  const view = status.settings.main_view

  async function toggleEngine() {
    if (running) {
      await window.desktop.stop()
    } else {
      await window.desktop.start()
    }
    await onRefresh()
  }

  return (
    <main className="controller-shell">
      <header className="brand-row">
        <div className="brand-mark" aria-hidden="true" />
        <strong>夏令营 Agent</strong>
      </header>

      <section className="status-card" aria-live="polite">
        <span className={`status-dot status-${status.engine.status}`} />
        <div>
          <h1>{status.engine.status === 'running' ? '运行中' : status.engine.status === 'error' ? '异常' : '待命'}</h1>
          {view.show_status_detail && <p>{status.engine.listener_running ? '微信监听已开启' : '监听未开启'}</p>}
        </div>
      </section>

      {view.show_target && (
        <section className="panel">
          <h2>目标群聊</h2>
          <div className="select-like">{status.engine.group_name || '未连接'}</div>
          <p className="hint"><span />WeFlow 本地服务</p>
        </section>
      )}

      {view.show_recent_logs && (
        <section className="panel log-panel">
          <h2>运行日志</h2>
          <div className="log-box">
            {status.recent_logs.length ? status.recent_logs.slice(-6).map((line, index) => <p key={`${line}-${index}`}>{line}</p>) : <em>引擎尚未启动</em>}
          </div>
        </section>
      )}

      <footer className="bottom-bar">
        <button className="primary-action" onClick={toggleEngine}>
          <span aria-hidden="true">{running ? '■' : '▶'}</span>
          {running ? '停止引擎' : '启动引擎'}
        </button>
        {view.show_history_entry && <IconButton label="历史" onClick={() => window.desktop.openAdvanced('work_trace')}>↺</IconButton>}
        <IconButton label="配置" onClick={() => window.desktop.openSettings()}>⚙</IconButton>
      </footer>
    </main>
  )
}

function SettingsWindow() {
  const [payload, setPayload] = useState<AppSettingsPayload | null>(null)
  const settings = payload?.settings ?? fallbackSettings

  useEffect(() => {
    void window.desktop.getSettings().then(setPayload)
  }, [])

  async function save(next: Partial<DesktopSettings>) {
    const merged = { ...settings, ...next }
    setPayload(await window.desktop.saveSettings(merged))
  }

  return (
    <main className="settings-shell">
      <header>
        <h1>配置</h1>
        <p>控制主页面展示、回复模式和高级页面入口。</p>
      </header>
      <section className="settings-grid">
        <SettingsPanel title="主页面展示">
          <Toggle label="目标群聊" checked={settings.main_view.show_target} onChange={(value) => save({ main_view: { ...settings.main_view, show_target: value } })} />
          <Toggle label="最近日志" checked={settings.main_view.show_recent_logs} onChange={(value) => save({ main_view: { ...settings.main_view, show_recent_logs: value } })} />
          <Toggle label="历史入口" checked={settings.main_view.show_history_entry} onChange={(value) => save({ main_view: { ...settings.main_view, show_history_entry: value } })} />
          <Toggle label="状态详情" checked={settings.main_view.show_status_detail} onChange={(value) => save({ main_view: { ...settings.main_view, show_status_detail: value } })} />
        </SettingsPanel>
        <SettingsPanel title="高级页面">
          <Toggle label="消息处理" checked={settings.advanced_pages.messages} onChange={(value) => save({ advanced_pages: { ...settings.advanced_pages, messages: value } })} />
          <Toggle label="候选库" checked={settings.advanced_pages.candidates} onChange={(value) => save({ advanced_pages: { ...settings.advanced_pages, candidates: value } })} />
          <Toggle label="工作轨迹" checked={settings.advanced_pages.work_trace} onChange={(value) => save({ advanced_pages: { ...settings.advanced_pages, work_trace: value } })} />
          <Toggle label="RAG 维护" checked={settings.advanced_pages.rag} onChange={(value) => save({ advanced_pages: { ...settings.advanced_pages, rag: value } })} />
        </SettingsPanel>
        <SettingsPanel title="微信桥接">
          <ReadOnlyLine label="群聊" value={String(payload?.wechat.group_name ?? '未连接')} />
          <ReadOnlyLine label="接口" value={String(payload?.wechat.base_url ?? 'http://127.0.0.1:5031')} />
          <ReadOnlyLine label="轮询" value={`${payload?.wechat.poll_interval_seconds ?? 5} 秒`} />
        </SettingsPanel>
        <SettingsPanel title="回复模式">
          <ReadOnlyLine label="模式" value={String(payload?.reply.mode ?? 'semi_auto')} />
          <ReadOnlyLine label="每日上限" value={String(payload?.reply.daily_auto_reply_limit ?? 50)} />
        </SettingsPanel>
      </section>
    </main>
  )
}

function AdvancedWindow({ page }: { page: string }) {
  const title = useMemo(() => {
    return ({ messages: '消息处理', candidates: '候选库', work_trace: '工作轨迹', rag: 'RAG 维护' } as Record<string, string>)[page] ?? '消息处理'
  }, [page])
  return (
    <main className="advanced-shell">
      <header>
        <h1>{title}</h1>
        <p>高级工作台页面会承接旧浏览器工作台能力，并逐步拆分为独立模块。</p>
      </header>
      <section className="empty-state">
        <strong>{title}</strong>
        <span>页面骨架已就绪，后续接入消息列表、候选审核和轨迹回放。</span>
      </section>
    </main>
  )
}

function SettingsPanel({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="settings-panel"><h2>{title}</h2>{children}</section>
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return <label className="toggle-row"><span>{label}</span><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} /></label>
}

function ReadOnlyLine({ label, value }: { label: string; value: string }) {
  return <div className="readonly-line"><span>{label}</span><strong>{value}</strong></div>
}

function IconButton({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return <button className="icon-button" aria-label={label} title={label} onClick={onClick}>{children}</button>
}

export default App
