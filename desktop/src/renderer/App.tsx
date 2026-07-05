import { useEffect, useMemo, useState } from 'react'
import type {
  AppSettingsPayload,
  AppSettingsUpdate,
  AppStatus,
  DesktopApi,
  DesktopSettings,
  VisionStatus,
  WeChatBridgeSettings,
  WorkbenchItem,
  WorkbenchItemsPayload,
  WorkTraceEntry,
  WorkTracePayload
} from '../shared/types'

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

const fallbackWechatSettings: WeChatBridgeSettings = {
  base_url: 'http://127.0.0.1:5031',
  token_env: 'WEFLOW_API_TOKEN',
  group_name: '沐曦开源英才夏令营咨询群',
  session_id: '',
  keywords: ['报名', '报到', '住宿', '交通', '作业', '面试', 'GPU', '算子'],
  poll_interval_seconds: 5,
  enabled: true,
  show_debug_config: false
}

type WechatForm = {
  group_name: string
  keywordsText: string
  poll_interval_seconds: number
}

function toWechatForm(wechat?: WeChatBridgeSettings): WechatForm {
  const current = wechat ?? fallbackWechatSettings
  return {
    group_name: current.group_name,
    keywordsText: current.keywords.join(', '),
    poll_interval_seconds: current.poll_interval_seconds
  }
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
  return <DesktopWorkbench status={status} onRefresh={refresh} />
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

function DesktopWorkbench({ status }: { status: AppStatus; onRefresh: () => Promise<void> }) {
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
    try {
      const getItems = getDesktopMethod('getItems')
      const payload = await getItems()
      setItemsPayload(payload)
      setSelectedId((current) => current && payload.items.some((item) => item.event_id === current) ? current : payload.items[0]?.event_id ?? '')
    } catch (error) {
      setMessage(errorMessage(error))
    }
  }

  async function refreshVision() {
    try {
      const getVisionStatus = getDesktopMethod('getVisionStatus')
      setVision(await getVisionStatus())
    } catch (error) {
      setVision((current) => ({ ...current, last_error: errorMessage(error) }))
    }
  }

  async function generateDraft() {
    await runAction('正在生成草稿...', async () => {
      const question = manualQuestion.trim()
      if (!question) {
        setMessage('请先输入学生问题')
        return
      }
      const ask = getDesktopMethod('ask')
      const payload = await ask(question)
      setItemsPayload({ items: payload.items })
      setSelectedId(payload.item.event_id)
      setManualQuestion('')
      setMessage('已生成回复草稿')
    })
  }

  async function pasteReply() {
    await runAction('正在填入微信...', async () => {
      if (!selected) {
        setMessage('请先选择一条消息')
        return
      }
      const pasteReply = getDesktopMethod('pasteReply')
      const result = await pasteReply(selected.event_id, replyDraft)
      setMessage(result.message)
    })
  }

  async function confirmSent() {
    await runAction('正在记录已发送...', async () => {
      if (!selected) {
        setMessage('请先选择一条消息')
        return
      }
      const confirmSent = getDesktopMethod('confirmSent')
      const result = await confirmSent(selected.event_id, replyDraft)
      setMessage(result.message)
    })
  }

  async function saveCandidate() {
    await runAction('正在保存候选...', async () => {
      if (!selected) {
        setMessage('请先选择一条消息')
        return
      }
      const saveCandidate = getDesktopMethod('saveCandidate')
      const result = await saveCandidate(selected.event_id, replyDraft)
      setMessage(result.message)
    })
  }

  async function startVision() {
    await runAction('正在启动视觉观察...', async () => {
      const startVision = getDesktopMethod('startVision')
      const payload = await startVision()
      setItemsPayload({ items: payload.items })
      setVision(payload.vision)
      setMessage(payload.message)
    })
  }

  async function captureVision() {
    await runAction('正在识别当前窗口...', async () => {
      const captureVision = getDesktopMethod('captureVision')
      const payload = await captureVision()
      setItemsPayload({ items: payload.items })
      setVision(payload.vision)
      setMessage(payload.message)
    })
  }

  async function stopVision() {
    await runAction('正在停止观察...', async () => {
      const stopVision = getDesktopMethod('stopVision')
      const payload = await stopVision()
      setVision(payload.vision)
      setMessage(payload.message)
    })
  }

  async function runAction(pendingMessage: string, action: () => Promise<void>) {
    setMessage(pendingMessage)
    try {
      await action()
    } catch (error) {
      setMessage(errorMessage(error))
    }
  }

  return (
    <main className="workbench-shell">
      <aside className="workbench-sidebar">
        <header className="brand-row">
          <div className="brand-mark" aria-hidden="true" />
          <div>
            <strong>夏令营 Agent</strong>
            <span>微信回复助手</span>
          </div>
        </header>
        <section className="sidebar-status" aria-label="微信观察状态">
          <span className={`status-dot ${vision.running ? 'status-running' : 'status-idle'}`} />
          <div>
            <strong>{vision.running ? '正在观察微信' : '等待观察'}</strong>
            <small>{vision.window_title || status.engine.group_name || '尚未连接窗口'}</small>
          </div>
        </section>
        <section className="sidebar-guide" aria-label="处理流程">
          <h2>处理流程</h2>
          <ol>
            <li><span>1</span>观察微信消息</li>
            <li><span>2</span>选择待回复问题</li>
            <li><span>3</span>确认草稿并发送</li>
          </ol>
        </section>
        <nav className="sidebar-links" aria-label="辅助入口">
          <button className="ghost-action" type="button" onClick={() => window.desktop.openSettings()}>配置</button>
          <button className="ghost-action" type="button" onClick={() => window.desktop.openAdvanced('work_trace')}>工作轨迹</button>
        </nav>
      </aside>

      <section className="workflow-panel">
        <header className="workflow-header">
          <div>
            <span className="eyebrow">第 1 步</span>
            <h1>观察并获取待回复消息</h1>
            <p>{vision.last_error || vision.last_message || message}</p>
          </div>
          <div className="workflow-actions">
            <button className="primary-action compact" type="button" onClick={startVision}>启动观察</button>
            <button className="ghost-action compact" type="button" onClick={captureVision}>识别当前窗口</button>
            <button className="ghost-action compact" type="button" onClick={refreshItems}>刷新</button>
            {vision.running && <button className="ghost-action compact" type="button" onClick={stopVision}>停止</button>}
          </div>
        </header>

        <section className="manual-entry" aria-label="手动生成回复">
          <input
            value={manualQuestion}
            onChange={(event) => setManualQuestion(event.target.value)}
            placeholder="也可以手动输入学生问题，生成一条回复草稿"
          />
          <button className="secondary-action compact" type="button" onClick={generateDraft}>生成草稿</button>
        </section>

        <section className="message-stream" aria-label="待处理消息">
          <header>
            <div>
              <span className="eyebrow">第 2 步</span>
              <h2>选择待处理消息</h2>
            </div>
            <strong>{itemsPayload.items.length} 条</strong>
          </header>
          <div className="message-list">
            {itemsPayload.items.length ? (
              itemsPayload.items.map((item) => (
                <button key={item.event_id} className={`message-row ${selected?.event_id === item.event_id ? 'selected' : ''}`} type="button" onClick={() => setSelectedId(item.event_id)}>
                  <span>{item.status}</span>
                  <strong>{item.question}</strong>
                  <small>{item.sender} · {item.source}</small>
                </button>
              ))
            ) : (
              <div className="empty-message-state" role="status">
                <strong>暂无待处理消息</strong>
                <span>点击“启动观察”监听微信，或在上方手动输入问题生成草稿。</span>
              </div>
            )}
          </div>
        </section>

        <section className="reply-composer" aria-label="回复草稿">
          <div className="composer-head">
            <div>
              <span className="eyebrow">第 3 步</span>
              <label htmlFor="replyDraft">确认回复草稿</label>
            </div>
            <p role="status">{message}</p>
          </div>
          <textarea id="replyDraft" value={replyDraft} onChange={(event) => setReplyDraft(event.target.value)} />
          <div className="reply-actions">
            <button className="primary-action compact" type="button" onClick={pasteReply}>填入微信</button>
            <button className="secondary-action compact" type="button" onClick={confirmSent}>我已发送</button>
            <button className="ghost-action compact" type="button" onClick={saveCandidate}>保存候选</button>
          </div>
        </section>
      </section>

      <aside className="decision-panel">
        <header>
          <span className="eyebrow">辅助判断</span>
          <h2>选中消息详情</h2>
        </header>
        {selected ? <DecisionSummary item={selected} /> : <p>选择一条消息后，这里会显示触发原因、建议动作和置信度。</p>}
      </aside>
    </main>
  )
}

function getDesktopMethod<K extends keyof DesktopApi>(name: K): DesktopApi[K] {
  const api = window.desktop as Partial<DesktopApi> | undefined
  const method = api?.[name]
  if (typeof method !== 'function') {
    throw new Error(`桌面主进程尚未加载 ${String(name)} 接口，请完全退出并重新启动桌面版。`)
  }
  return method.bind(api) as DesktopApi[K]
}

function errorMessage(error: unknown) {
  if (error instanceof Error) return error.message
  if (typeof error === 'string') return error
  return '操作失败，请查看本地服务日志。'
}

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

function SettingsWindow() {
  const [payload, setPayload] = useState<AppSettingsPayload | null>(null)
  const [wechatForm, setWechatForm] = useState<WechatForm>(() => toWechatForm())
  const [wechatMessage, setWechatMessage] = useState('')
  const settings = payload?.settings ?? fallbackSettings
  const wechat = payload?.wechat ?? fallbackWechatSettings

  useEffect(() => {
    void window.desktop.getSettings().then((nextPayload) => {
      setPayload(nextPayload)
      setWechatForm(toWechatForm(nextPayload.wechat))
    })
  }, [])

  async function save(next: AppSettingsUpdate) {
    const merged = { ...settings, ...next }
    setPayload(await window.desktop.saveSettings(merged))
  }

  async function saveWechatSettings() {
    const groupName = wechatForm.group_name.trim()
    const keywords = wechatForm.keywordsText.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean)
    const pollSeconds = Math.min(60, Math.max(2, Number(wechatForm.poll_interval_seconds) || 5))
    if (!groupName) {
      setWechatMessage('请填写群聊名称')
      return
    }
    const nextPayload = await window.desktop.saveSettings({
      ...settings,
      wechat: {
        ...wechat,
        group_name: groupName,
        keywords,
        poll_interval_seconds: pollSeconds
      }
    })
    setPayload(nextPayload)
    setWechatForm(toWechatForm(nextPayload.wechat))
    setWechatMessage('微信桥接配置已保存')
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
          <Field label="群聊" htmlFor="wechatGroupName">
            <input
              id="wechatGroupName"
              value={wechatForm.group_name}
              onChange={(event) => setWechatForm((current) => ({ ...current, group_name: event.target.value }))}
            />
          </Field>
          <Field label="监听关键字" htmlFor="wechatKeywords">
            <textarea
              id="wechatKeywords"
              rows={3}
              value={wechatForm.keywordsText}
              onChange={(event) => setWechatForm((current) => ({ ...current, keywordsText: event.target.value }))}
            />
          </Field>
          <Field label="轮询时间" htmlFor="wechatPollSeconds">
            <div className="input-with-unit">
              <input
                id="wechatPollSeconds"
                type="number"
                min={2}
                max={60}
                value={wechatForm.poll_interval_seconds}
                onChange={(event) => setWechatForm((current) => ({ ...current, poll_interval_seconds: Number(event.target.value) }))}
              />
              <span>秒</span>
            </div>
          </Field>
          <ReadOnlyLine label="接口" value={String(payload?.wechat.base_url ?? 'http://127.0.0.1:5031')} />
          <button className="secondary-action" type="button" onClick={saveWechatSettings}>保存微信桥接</button>
          {wechatMessage && <p className="save-message" role="status">{wechatMessage}</p>}
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
  if (page === 'work_trace') return <WorkTracePage title={title} />
  return (
    <main className="advanced-shell">
      <header>
        <h1>{title}</h1>
        <p>高级页面用于查看候选审核、资料维护和轨迹回放等辅助模块。</p>
      </header>
      <section className="empty-state">
        <strong>{title}</strong>
        <span>页面骨架已就绪，后续接入消息列表、候选审核和轨迹回放。</span>
      </section>
    </main>
  )
}

function WorkTracePage({ title }: { title: string }) {
  const [payload, setPayload] = useState<WorkTracePayload | null>(null)
  const [selectedId, setSelectedId] = useState('')
  const [message, setMessage] = useState('正在读取工作轨迹...')
  const trace = payload?.trace ?? []
  const selected = trace.find((entry) => entry.trace_id === selectedId) ?? trace[0]

  useEffect(() => {
    void refreshTrace()
    const timer = window.setInterval(refreshTrace, 4000)
    return () => window.clearInterval(timer)
  }, [])

  async function refreshTrace() {
    try {
      const next = await window.desktop.getWorkTrace()
      setPayload(next)
      setSelectedId((current) => current && next.trace.some((entry) => entry.trace_id === current) ? current : next.trace[0]?.trace_id ?? '')
      setMessage(next.trace.length ? '轨迹已同步' : '暂无轨迹，载入演示或启动引擎后会在这里记录处理过程')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '读取工作轨迹失败')
    }
  }

  async function loadDemoTrace() {
    try {
      setMessage('正在载入演示轨迹...')
      await window.desktop.loadDemo()
      await refreshTrace()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '载入演示失败')
    }
  }

  return (
    <main className="advanced-shell work-trace-shell">
      <header className="advanced-header">
        <div>
          <h1>{title}</h1>
          <p>记录从消息观察、候选生成到人工动作确认的完整链路。</p>
        </div>
        <div className="advanced-actions">
          <button className="ghost-action" type="button" onClick={refreshTrace}>刷新</button>
          <button className="secondary-action compact" type="button" onClick={loadDemoTrace}>载入演示</button>
        </div>
      </header>

      <section className="trace-summary" aria-label="工作轨迹统计">
        <Metric label="全部步骤" value={payload?.summary.total ?? 0} />
        <Metric label="观察" value={payload?.summary.observed ?? 0} />
        <Metric label="思考" value={payload?.summary.thought ?? 0} />
        <Metric label="行动" value={payload?.summary.acted ?? 0} />
      </section>

      <section className="trace-workspace">
        <div className="trace-list" aria-label="工作轨迹列表">
          {trace.length ? trace.map((entry) => (
            <button
              key={entry.trace_id}
              className={`trace-row ${selected?.trace_id === entry.trace_id ? 'selected' : ''}`}
              type="button"
              onClick={() => setSelectedId(entry.trace_id)}
            >
              <span className={`phase-pill phase-${entry.phase}`}>{phaseLabel(entry.phase)}</span>
              <strong>{entry.summary}</strong>
              <small>{entry.group_name} · {formatTime(entry.created_at)}</small>
            </button>
          )) : (
            <div className="trace-empty" role="status">
              <strong>暂无工作轨迹</strong>
              <span>{message}</span>
            </div>
          )}
        </div>

        <aside className="trace-detail" aria-label="轨迹详情">
          {selected ? <TraceDetail entry={selected} /> : <p>{message}</p>}
        </aside>
      </section>
    </main>
  )
}

function Metric({ label, value }: { label: string; value: number }) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong></div>
}

function TraceDetail({ entry }: { entry: WorkTraceEntry }) {
  return (
    <>
      <div className="detail-head">
        <span className={`phase-pill phase-${entry.phase}`}>{phaseLabel(entry.phase)}</span>
        <h2>{entry.summary}</h2>
      </div>
      <dl className="detail-grid">
        <DetailRow label="群聊" value={entry.group_name} />
        <DetailRow label="时间" value={formatTime(entry.created_at)} />
        <DetailRow label="执行者" value={actorLabel(entry.actor)} />
        <DetailRow label="动作" value={entry.action || '无'} />
        <DetailRow label="结果" value={entry.outcome || '无'} />
        <DetailRow label="原因" value={entry.reasoning || '无'} />
      </dl>
      <div className="detail-json">
        <span>结构化详情</span>
        <pre>{JSON.stringify(entry.details ?? {}, null, 2)}</pre>
      </div>
    </>
  )
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return <><dt>{label}</dt><dd>{value}</dd></>
}

function phaseLabel(phase: string) {
  return ({ observe: '观察', think: '思考', act: '行动' } as Record<string, string>)[phase] ?? phase
}

function actorLabel(actor: string) {
  return ({ agent: 'Agent', human: '人工' } as Record<string, string>)[actor] ?? actor
}

function formatTime(raw: string) {
  const time = new Date(raw)
  if (Number.isNaN(time.getTime())) return raw
  return time.toLocaleString('zh-CN', { hour12: false })
}

function SettingsPanel({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="settings-panel"><h2>{title}</h2>{children}</section>
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return <label className="toggle-row"><span>{label}</span><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} /></label>
}

function Field({ label, htmlFor, children }: { label: string; htmlFor: string; children: React.ReactNode }) {
  return <label className="field-row" htmlFor={htmlFor}><span>{label}</span>{children}</label>
}

function ReadOnlyLine({ label, value }: { label: string; value: string }) {
  return <div className="readonly-line"><span>{label}</span><strong>{value}</strong></div>
}

function IconButton({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return <button className="icon-button" aria-label={label} title={label} onClick={onClick}>{children}</button>
}

export default App
