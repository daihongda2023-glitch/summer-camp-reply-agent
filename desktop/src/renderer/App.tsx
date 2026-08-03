import { useEffect, useMemo, useState } from 'react'
import type {
  AppSettingsPayload,
  AppStatus,
  DesktopSettings,
  MessageScope,
  OperationProfile,
  PasteReplyResult,
  ReadinessPayload,
  ReviewStatus,
  VisionStatus,
  WeChatBridgeSettings,
  WorkbenchItem,
  WorkbenchItemsPayload,
  WorkTraceEntry,
  WorkTracePayload
} from '../shared/types'
import {
  OPERATION_PROFILE_OPTIONS,
  answerSourceLabel,
  applyOperationProfile,
  confidenceLabel,
  confidenceLevel,
  decisionSummary,
  extractSafeSourceUrl,
  filterWorkbenchItems,
  operationProfileLabel,
  recommendedPrimaryAction,
  resolveOperationProfile
} from './workbench-ux'

const fallbackSettings: DesktopSettings = {
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

const fallbackStatus: AppStatus = {
  engine: {
    status: 'idle',
    listener_running: false,
    group_name: '未连接',
    send_mode: 'manual_confirm',
    poll_interval_seconds: 5,
    debug_review_mode: true
  },
  settings: fallbackSettings,
  recent_logs: []
}

const fallbackWechatSettings: WeChatBridgeSettings = {
  base_url: 'http://127.0.0.1:5031',
  token_env: 'WEFLOW_API_TOKEN',
  group_name: '沐曦开源英才夏令营咨询群',
  session_id: '',
  keywords: ['报名', '报到', '住宿', '交通', '作业', '面试', 'GPU', '算子'],
  poll_interval_seconds: 5,
  enabled: true,
  show_debug_config: false,
  send_mode: 'manual_confirm',
  debug_review_mode: true
}

const emptyReadiness: ReadinessPayload = {
  ready: false,
  operation_profile: 'safe_review',
  checks: [
    { key: 'engine', label: '本地服务', ready: false, detail: '正在检查' },
    { key: 'group', label: '目标群聊', ready: false, detail: '正在检查' },
    { key: 'ai', label: 'AI 配置', ready: false, detail: '正在检查' },
    { key: 'wechat', label: '微信监听', ready: false, detail: '正在检查' }
  ]
}

function App() {
  const params = new URLSearchParams(window.location.search)
  const windowKind = params.get('window') || 'main'
  const [status, setStatus] = useState<AppStatus>(fallbackStatus)

  useEffect(() => {
    document.title = windowKind === 'settings'
      ? '设置 - 夏令营 Agent'
      : windowKind === 'advanced'
        ? '工作轨迹 - 夏令营 Agent'
        : '夏令营 Agent'
  }, [windowKind])

  useEffect(() => {
    if (windowKind !== 'main') return
    void refreshStatus()
    const timer = window.setInterval(refreshStatus, 3000)
    return () => window.clearInterval(timer)
  }, [windowKind])

  async function refreshStatus() {
    try {
      setStatus(await window.desktop.getStatus())
    } catch {
      setStatus((current) => ({ ...current, engine: { ...current.engine, status: 'error' } }))
    }
  }

  if (windowKind === 'settings') return <SettingsWindow />
  if (windowKind === 'advanced') return <WorkTracePage />
  return <DesktopWorkbench status={status} onRefreshStatus={refreshStatus} />
}

function DesktopWorkbench({ status, onRefreshStatus }: { status: AppStatus; onRefreshStatus: () => Promise<void> }) {
  const [itemsPayload, setItemsPayload] = useState<WorkbenchItemsPayload>({ items: [] })
  const [selectedId, setSelectedId] = useState('')
  const [replyDraft, setReplyDraft] = useState('')
  const [reviewNote, setReviewNote] = useState('')
  const [manualQuestion, setManualQuestion] = useState('')
  const [messageScope, setMessageScope] = useState<MessageScope>('pending')
  const [reviewStatusFilter, setReviewStatusFilter] = useState<ReviewStatus | ''>('')
  const [queueSearch, setQueueSearch] = useState('')
  const [vision, setVision] = useState<VisionStatus>({ running: false, window_title: '', last_message: '', last_error: '' })
  const [readiness, setReadiness] = useState<ReadinessPayload>(emptyReadiness)
  const [busyAction, setBusyAction] = useState('')
  const [toast, setToast] = useState({ kind: 'info', text: '正在准备工作台…' })
  const [pastedMessageId, setPastedMessageId] = useState('')

  const visibleItems = useMemo(
    () => filterWorkbenchItems(itemsPayload.items, queueSearch),
    [itemsPayload.items, queueSearch]
  )
  const selected = visibleItems.find((item) => item.message_id === selectedId) ?? visibleItems[0]
  const operationProfile = readiness.operation_profile || resolveOperationProfile({
    send_mode: status.engine.send_mode,
    debug_review_mode: status.engine.debug_review_mode
  })
  const primaryAction = recommendedPrimaryAction(operationProfile, selected, pastedMessageId === selected?.message_id)
  const sourceUrl = selected ? extractSafeSourceUrl(selected.answer_source) : ''

  useEffect(() => {
    void initialize()
  }, [])

  useEffect(() => {
    if (!selected) return
    setSelectedId(selected.message_id)
    setReplyDraft(selected.reply || '')
    setReviewNote(selected.review_note || '')
    setPastedMessageId('')
  }, [selected?.message_id])

  useEffect(() => {
    if (!vision.running) return
    const timer = window.setInterval(
      () => void refreshItems(),
      Math.max(2000, status.engine.poll_interval_seconds * 1000)
    )
    return () => window.clearInterval(timer)
  }, [vision.running, status.engine.poll_interval_seconds, messageScope, reviewStatusFilter])

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
        event.preventDefault()
        if (!busyAction) void runPrimaryAction()
      }
      if (event.altKey && event.key === 'ArrowDown' && visibleItems.length) {
        event.preventDefault()
        const currentIndex = Math.max(0, visibleItems.findIndex((item) => item.message_id === selected?.message_id))
        setSelectedId(visibleItems[(currentIndex + 1) % visibleItems.length].message_id)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [busyAction, primaryAction, selected?.message_id, replyDraft, reviewNote, visibleItems])

  async function initialize() {
    try {
      await window.desktop.start()
      const [items, nextVision, nextReadiness] = await Promise.all([
        window.desktop.getItems('pending', ''),
        window.desktop.getVisionStatus(),
        window.desktop.getReadiness()
      ])
      setItemsPayload(items)
      setSelectedId(items.items[0]?.message_id ?? '')
      setVision(nextVision)
      setReadiness(nextReadiness)
      setToast({ kind: 'success', text: items.items.length ? `有 ${items.items.length} 条消息待处理` : '工作台已就绪' })
      await onRefreshStatus()
    } catch (error) {
      setToast({ kind: 'error', text: errorMessage(error) })
    }
  }

  async function refreshReadiness() {
    try {
      setReadiness(await window.desktop.getReadiness())
    } catch (error) {
      setToast({ kind: 'error', text: errorMessage(error) })
    }
  }

  async function refreshItems(
    nextScope: MessageScope = messageScope,
    nextReviewStatus: ReviewStatus | '' = reviewStatusFilter
  ) {
    const payload = await window.desktop.getItems(nextScope, nextReviewStatus)
    setItemsPayload(payload)
    setSelectedId((current) => current && payload.items.some((item) => item.message_id === current)
      ? current
      : payload.items[0]?.message_id ?? '')
    return payload
  }

  async function runAction(key: string, pendingText: string, action: () => Promise<string>) {
    if (busyAction) return
    setBusyAction(key)
    setToast({ kind: 'info', text: pendingText })
    try {
      const result = await action()
      setToast({ kind: 'success', text: result })
    } catch (error) {
      setToast({ kind: 'error', text: errorMessage(error) })
    } finally {
      setBusyAction('')
    }
  }

  async function changeQueue(nextScope: MessageScope) {
    setMessageScope(nextScope)
    const statusFilter = nextScope === 'all' ? reviewStatusFilter : ''
    if (nextScope === 'pending') setReviewStatusFilter('')
    await runAction('queue', '正在读取消息…', async () => {
      const payload = await refreshItems(nextScope, statusFilter)
      return payload.items.length ? `已载入 ${payload.items.length} 条消息` : '当前没有符合条件的消息'
    })
  }

  async function changeReviewStatus(nextStatus: ReviewStatus | '') {
    setReviewStatusFilter(nextStatus)
    await runAction('filter', '正在筛选历史记录…', async () => {
      const payload = await refreshItems('all', nextStatus)
      return payload.items.length ? `找到 ${payload.items.length} 条记录` : '没有符合条件的历史记录'
    })
  }

  async function toggleObservation() {
    await runAction('observation', vision.running ? '正在停止观察…' : '正在连接微信…', async () => {
      const result = vision.running ? await window.desktop.stopVision() : await window.desktop.startVision()
      setVision(result.vision)
      setItemsPayload({ items: result.items })
      setSelectedId(result.items[0]?.message_id ?? '')
      await refreshReadiness()
      await onRefreshStatus()
      return result.message
    })
  }

  async function syncNow() {
    await runAction('sync', '正在同步当前窗口…', async () => {
      const result = await window.desktop.captureVision()
      setVision(result.vision)
      setItemsPayload({ items: result.items })
      setSelectedId(result.items[0]?.message_id ?? '')
      return result.message
    })
  }

  async function generateDraft() {
    const question = manualQuestion.trim()
    if (!question) {
      setToast({ kind: 'error', text: '请先输入学生问题' })
      return
    }
    await runAction('generate', '正在结合 FAQ 和 RAG 生成草稿…', async () => {
      const payload = await window.desktop.ask(question)
      setMessageScope('pending')
      setReviewStatusFilter('')
      setItemsPayload({ items: payload.items })
      setSelectedId(payload.item.message_id)
      setManualQuestion('')
      return '草稿已生成并加入待处理队列'
    })
  }

  async function pasteReply() {
    if (!selected) return
    await runAction('paste', '正在填入微信…', async () => {
      const result = await window.desktop.pasteReply(selected.event_id, replyDraft)
      setPastedMessageId(selected.message_id)
      return pasteStatusMessage(result)
    })
  }

  async function publishReply() {
    if (!selected) return
    await runAction('publish', '正在发送回复…', async () => {
      const result = await window.desktop.publishReply(selected.event_id, replyDraft)
      await refreshItems()
      return pasteStatusMessage(result)
    })
  }

  async function confirmSent() {
    if (!selected) return
    await runAction('confirm', '正在记录发送结果…', async () => {
      const result = await window.desktop.confirmSent(selected.event_id, replyDraft)
      await refreshItems()
      return replyDraft.trim() !== selected.reply.trim()
        ? `${result.message}；修改后的回复已沉淀为候选`
        : result.message
    })
  }

  async function saveCandidate() {
    if (!selected) return
    await runAction('candidate', '正在保存候选…', async () => {
      const result = await window.desktop.saveCandidate(selected.event_id, replyDraft)
      await refreshItems()
      return result.message
    })
  }

  async function escalateMessage() {
    if (!selected) return
    await runAction('escalate', '正在转人工处理…', async () => {
      const result = await window.desktop.escalateMessage(selected.event_id, reviewNote)
      await refreshItems()
      return result.message
    })
  }

  async function completeReview() {
    if (!selected) return
    await runAction('complete', '正在完成审核…', async () => {
      const result = await window.desktop.completeReview(selected.event_id, reviewNote)
      await refreshItems()
      return result.message
    })
  }

  async function runPrimaryAction() {
    if (primaryAction === 'paste') await pasteReply()
    else if (primaryAction === 'confirm_sent') await confirmSent()
    else if (primaryAction === 'escalate') await escalateMessage()
  }

  const primaryLabel = primaryAction === 'paste'
    ? operationProfile === 'safe_review' ? '确认回复并填入微信' : '填入微信'
    : primaryAction === 'confirm_sent'
      ? '我已发送'
      : primaryAction === 'escalate'
        ? '转人工处理'
        : '请选择待处理消息'

  return (
    <main className="workbench-shell">
      <aside className="workbench-sidebar">
        <header className="brand-row">
          <span className="brand-mark" aria-hidden="true">夏</span>
          <div><strong>夏令营 Agent</strong><small>微信回复工作台</small></div>
        </header>

        <section className="sidebar-status">
          <span className={`status-dot ${vision.running ? 'status-running' : 'status-idle'}`} />
          <div>
            <strong>{vision.running ? '正在观察微信' : '尚未观察微信'}</strong>
            <small>{vision.window_title || status.engine.group_name || '等待连接窗口'}</small>
          </div>
        </section>

        <ReadinessCard readiness={readiness} onRefresh={() => void refreshReadiness()} />

        <section className="mode-summary">
          <span>运行模式</span>
          <strong>{operationProfileLabel(operationProfile)}</strong>
          <small>{OPERATION_PROFILE_OPTIONS.find((option) => option.value === operationProfile)?.description}</small>
        </section>

        <nav className="sidebar-links" aria-label="辅助入口">
          <button className="ghost-action" type="button" onClick={() => window.desktop.openSettings()}>设置</button>
          <button className="ghost-action" type="button" onClick={() => window.desktop.openAdvanced('work_trace')}>工作轨迹</button>
        </nav>
      </aside>

      <section className="workflow-panel">
        <header className="workflow-header">
          <div>
            <span className="eyebrow">消息处理</span>
            <h1>{vision.running ? '正在接收微信消息' : '连接微信后开始处理'}</h1>
            <p>{vision.last_error || vision.last_message || '命中 FAQ 或 RAG 的消息将按当前模式处理。'}</p>
          </div>
          <div className="workflow-actions">
            <button className={vision.running ? 'danger-action' : 'primary-action compact'} type="button" disabled={Boolean(busyAction)} onClick={() => void toggleObservation()}>
              {busyAction === 'observation' ? '处理中…' : vision.running ? '停止观察' : '开始观察'}
            </button>
            <details className="header-more">
              <summary aria-label="观察更多操作">•••</summary>
              <button type="button" disabled={Boolean(busyAction)} onClick={() => void syncNow()}>立即同步</button>
            </details>
          </div>
        </header>

        <div className={`toast toast-${toast.kind}`} role="status" aria-live="polite">{toast.text}</div>

        <details className="manual-tools">
          <summary>手动测试一个问题</summary>
          <div className="manual-entry">
            <input value={manualQuestion} onChange={(event) => setManualQuestion(event.target.value)} placeholder="输入学生问题，验证 FAQ、RAG 与 AI 回复" />
            <button className="secondary-action compact" type="button" disabled={Boolean(busyAction)} onClick={() => void generateDraft()}>生成草稿</button>
          </div>
        </details>

        <section className="message-stream">
          <header className="message-stream-head">
            <div className="queue-title"><h2>{messageScope === 'pending' ? '待处理' : '历史记录'}</h2><span>{visibleItems.length}</span></div>
            <div className="queue-tabs" role="tablist" aria-label="消息范围">
              <button className={messageScope === 'pending' ? 'active' : ''} type="button" onClick={() => void changeQueue('pending')}>待处理</button>
              <button className={messageScope === 'all' ? 'active' : ''} type="button" onClick={() => void changeQueue('all')}>历史记录</button>
            </div>
          </header>
          <div className="queue-toolbar">
            <input className="queue-search" type="search" value={queueSearch} onChange={(event) => setQueueSearch(event.target.value)} placeholder="搜索消息、发送人或回复" aria-label="搜索消息" />
            {messageScope === 'all' && (
              <select value={reviewStatusFilter} onChange={(event) => void changeReviewStatus(event.target.value as ReviewStatus | '')} aria-label="历史状态">
                <option value="">全部状态</option>
                <option value="sent">已发送</option>
                <option value="escalated">已转人工</option>
                <option value="candidate_saved">已存候选</option>
                <option value="review_completed">审核完成</option>
              </select>
            )}
          </div>
          <div className="message-list" role="list">
            {visibleItems.length ? visibleItems.map((item) => (
              <button className={`message-row ${selected?.message_id === item.message_id ? 'selected' : ''}`} type="button" role="listitem" key={item.message_id} onClick={() => setSelectedId(item.message_id)}>
                <div className="message-row-top">
                  <strong>{item.sender}</strong>
                  <time>{formatDate(item.message_time || item.created_at)}</time>
                </div>
                <span className="message-question">{item.question}</span>
                <div className="message-meta">
                  <span>{item.review_status_label}</span>
                  <span>{answerSourceLabel(item)}</span>
                  <span className={`confidence confidence-${confidenceLevel(item.confidence)}`}>置信度 {confidenceLabel(item.confidence)}</span>
                </div>
              </button>
            )) : (
              <div className="empty-message-state" role="status">
                <strong>{queueSearch ? '没有搜索结果' : messageScope === 'pending' ? '暂无待处理消息' : '暂无历史记录'}</strong>
                <span>{queueSearch ? '换一个关键词试试。' : vision.running ? '新消息到达后会自动出现在这里。' : '开始观察微信，或使用上方手动测试。'}</span>
              </div>
            )}
          </div>
        </section>

        <section className="reply-composer">
          <header className="composer-head">
            <div><span className="eyebrow">回复草稿</span><h2>{selected ? selected.question : '请选择一条消息'}</h2></div>
            <small>Ctrl+Enter 执行推荐操作 · Alt+↓ 下一条</small>
          </header>
          <textarea value={replyDraft} onChange={(event) => setReplyDraft(event.target.value)} disabled={!selected || selected.review_status !== 'pending_review'} placeholder="系统生成的回复会显示在这里" aria-label="回复草稿" />
          {selected?.review_status === 'pending_review' && (
            <label className="review-note"><span>处理备注</span><input value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} placeholder="可选，例如：需要老师确认录取结果" /></label>
          )}
          <div className="reply-actions">
            <button className="primary-action compact" type="button" disabled={Boolean(busyAction) || primaryAction === 'none' || !replyDraft.trim()} onClick={() => void runPrimaryAction()}>
              {busyAction && ['paste', 'confirm', 'escalate'].includes(busyAction) ? '处理中…' : primaryLabel}
            </button>
            {selected?.review_status === 'pending_review' && (
              <details className="more-actions">
                <summary>更多操作</summary>
                <div>
                  {operationProfile === 'automatic' && <button type="button" onClick={() => void publishReply()}>直接发送</button>}
                  <button type="button" onClick={() => void saveCandidate()}>保存为候选</button>
                  {primaryAction !== 'escalate' && <button type="button" onClick={() => void escalateMessage()}>转人工处理</button>}
                  <button type="button" onClick={() => void completeReview()}>无需回复，完成审核</button>
                </div>
              </details>
            )}
          </div>
        </section>
      </section>

      <aside className="decision-panel">
        <header><span className="eyebrow">回复依据</span><h2>{selected ? '系统为什么这样建议' : '选择消息查看依据'}</h2></header>
        {selected ? (
          <>
            <section className="decision-summary">
              <DecisionLine label="建议" value={selected.recommendation || '人工检查回复'} />
              <DecisionLine label="来源" value={answerSourceLabel(selected)} />
              <DecisionLine label="置信度" value={`${confidenceLabel(selected.confidence)}（${selected.confidence.toFixed(2)}）`} />
              <p>{decisionSummary(selected)}</p>
            </section>
            <section className="source-preview">
              <span>资料来源</span>
              <p>{selected.answer_source || '未找到明确资料来源'}</p>
              {sourceUrl && <button type="button" onClick={() => window.desktop.openExternal(sourceUrl)}>打开来源</button>}
            </section>
            {selected.match_status === 'unmatched' && selected.unmatched_reason_labels.length > 0 && (
              <section className="trigger-note"><strong>触发检查</strong><p>{selected.unmatched_reason_labels.join('、')}</p></section>
            )}
            <details className="technical-details">
              <summary>技术详情</summary>
              <dl className="decision-grid">
                <DecisionLine label="综合" value={selected.confidence.toFixed(2)} />
                <DecisionLine label="语义" value={selected.semantic_confidence.toFixed(2)} />
                <DecisionLine label="FAQ" value={selected.faq_confidence.toFixed(2)} />
                <DecisionLine label="RAG" value={selected.rag_confidence.toFixed(2)} />
                <DecisionLine label="生成方式" value={selected.generation_mode || '规则回复'} />
                <DecisionLine label="生成模型" value={selected.generation_model || '未使用模型'} />
                <DecisionLine label="原因" value={selected.reason || '无'} />
                {selected.generation_error && <DecisionLine label="降级信息" value={selected.generation_error} />}
              </dl>
            </details>
          </>
        ) : <p className="decision-empty">从中间队列中选择一条消息。</p>}
      </aside>
    </main>
  )
}

function ReadinessCard({ readiness, onRefresh }: { readiness: ReadinessPayload; onRefresh: () => void }) {
  return (
    <section className="readiness-card">
      <header><h2>运行检查</h2><button type="button" onClick={onRefresh}>刷新</button></header>
      <ul>
        {readiness.checks.map((check) => (
          <li key={check.key}>
            <span className={`check-mark ${check.ready ? 'ready' : ''}`}>{check.ready ? '✓' : '!'}</span>
            <div><strong>{check.label}</strong><small>{check.detail}</small></div>
          </li>
        ))}
      </ul>
    </section>
  )
}

function SettingsWindow() {
  const [payload, setPayload] = useState<AppSettingsPayload | null>(null)
  const [wechat, setWechat] = useState<WeChatBridgeSettings>(fallbackWechatSettings)
  const [operationProfile, setOperationProfile] = useState<OperationProfile>('safe_review')
  const [keywordsText, setKeywordsText] = useState(fallbackWechatSettings.keywords.join('、'))
  const [readiness, setReadiness] = useState<ReadinessPayload>(emptyReadiness)
  const [message, setMessage] = useState('正在读取设置…')
  const [saving, setSaving] = useState(false)

  useEffect(() => { void load() }, [])

  async function load() {
    try {
      const [settings, checks] = await Promise.all([window.desktop.getSettings(), window.desktop.getReadiness()])
      setPayload(settings)
      setWechat(settings.wechat)
      setOperationProfile(resolveOperationProfile(settings.wechat))
      setKeywordsText(settings.wechat.keywords.join('、'))
      setReadiness(checks)
      setMessage('设置已载入')
    } catch (error) {
      setMessage(errorMessage(error))
    }
  }

  async function saveSettings() {
    if (!payload || saving) return
    setSaving(true)
    setMessage('正在保存设置…')
    try {
      const profiled = applyOperationProfile(wechat, operationProfile)
      const saved = await window.desktop.saveSettings({
        wechat: {
          ...profiled,
          group_name: wechat.group_name.trim(),
          keywords: keywordsText.split(/[，,、\n]/).map((value) => value.trim()).filter(Boolean),
          poll_interval_seconds: Math.max(2, Number(wechat.poll_interval_seconds) || 5)
        }
      })
      setPayload(saved)
      setWechat(saved.wechat)
      setOperationProfile(resolveOperationProfile(saved.wechat))
      setReadiness(await window.desktop.getReadiness())
      setMessage('设置已保存，新模式已生效')
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setSaving(false)
    }
  }

  return (
    <main className="settings-shell">
      <header className="settings-header"><div><span className="eyebrow">配置</span><h1>设置</h1><p>选择目标群和运行模式即可开始；低频参数放在高级区域。</p></div></header>
      <div className="settings-grid simplified-settings">
        <section className="settings-panel">
          <h2>基础设置</h2>
          <label className="field-stack"><span>目标微信群</span><input value={wechat.group_name} onChange={(event) => setWechat({ ...wechat, group_name: event.target.value })} placeholder="输入完整群聊名称" /></label>
          <fieldset className="profile-options">
            <legend>运行模式</legend>
            {OPERATION_PROFILE_OPTIONS.map((option) => (
              <label className={operationProfile === option.value ? 'selected' : ''} key={option.value}>
                <input type="radio" name="operationProfile" value={option.value} checked={operationProfile === option.value} onChange={() => setOperationProfile(option.value)} />
                <span><strong>{option.label}</strong><small>{option.description}</small></span>
              </label>
            ))}
          </fieldset>
          <button className="primary-action settings-save" type="button" disabled={saving || !payload} onClick={() => void saveSettings()}>{saving ? '保存中…' : '保存设置'}</button>
          <p className="save-message" aria-live="polite">{message}</p>
        </section>

        <div className="settings-side">
          <ReadinessCard readiness={readiness} onRefresh={() => void load()} />
          <details className="settings-panel advanced-settings">
            <summary>高级参数</summary>
            <label className="field-stack"><span>监听关键词</span><textarea value={keywordsText} onChange={(event) => setKeywordsText(event.target.value)} rows={4} /></label>
            <label className="field-stack"><span>轮询间隔（秒）</span><input type="number" min="2" value={wechat.poll_interval_seconds} onChange={(event) => setWechat({ ...wechat, poll_interval_seconds: Number(event.target.value) })} /></label>
            <div className="readonly-line"><span>WeFlow 地址</span><strong>{wechat.base_url}</strong></div>
            <div className="readonly-line"><span>回复策略</span><strong>FAQ 或 RAG 任一命中即可回复</strong></div>
          </details>
        </div>
      </div>
    </main>
  )
}

function WorkTracePage() {
  const [payload, setPayload] = useState<WorkTracePayload | null>(null)
  const [selectedId, setSelectedId] = useState('')
  const [message, setMessage] = useState('正在读取工作轨迹…')
  const selected = payload?.trace.find((entry) => entry.trace_id === selectedId) ?? payload?.trace[0]

  useEffect(() => { void refresh() }, [])

  async function refresh() {
    try {
      const next = await window.desktop.getWorkTrace()
      setPayload(next)
      setSelectedId((current) => current || next.trace[0]?.trace_id || '')
      setMessage(next.trace.length ? '工作轨迹已更新' : '暂无工作轨迹')
    } catch (error) {
      setMessage(errorMessage(error))
    }
  }

  return (
    <main className="advanced-shell work-trace-shell">
      <header className="advanced-header"><div><span className="eyebrow">诊断</span><h1>工作轨迹</h1><p>查看从消息观察、资料检索到人工动作的完整链路。</p></div><button className="ghost-action" type="button" onClick={() => void refresh()}>刷新</button></header>
      <section className="trace-summary">
        <Metric label="全部步骤" value={payload?.summary.total ?? 0} />
        <Metric label="观察" value={payload?.summary.observed ?? 0} />
        <Metric label="判断" value={payload?.summary.thought ?? 0} />
        <Metric label="动作" value={payload?.summary.acted ?? 0} />
      </section>
      <section className="trace-workspace">
        <div className="trace-list">
          {payload?.trace.length ? payload.trace.map((entry) => (
            <button className={`trace-row ${selected?.trace_id === entry.trace_id ? 'selected' : ''}`} type="button" key={entry.trace_id} onClick={() => setSelectedId(entry.trace_id)}>
              <span className={`phase-pill phase-${entry.phase}`}>{phaseLabel(entry.phase)}</span>
              <strong>{entry.summary}</strong>
              <small>{entry.group_name} · {formatDate(entry.created_at)}</small>
            </button>
          )) : <div className="trace-empty"><strong>暂无工作轨迹</strong><span>{message}</span></div>}
        </div>
        <aside className="trace-detail">{selected ? <TraceDetail entry={selected} /> : <p>{message}</p>}</aside>
      </section>
    </main>
  )
}

function TraceDetail({ entry }: { entry: WorkTraceEntry }) {
  return <><span className={`phase-pill phase-${entry.phase}`}>{phaseLabel(entry.phase)}</span><h2>{entry.summary}</h2><dl className="detail-grid"><DecisionLine label="群聊" value={entry.group_name} /><DecisionLine label="时间" value={formatDate(entry.created_at)} /><DecisionLine label="执行者" value={entry.actor === 'human' ? '人工' : 'Agent'} /><DecisionLine label="动作" value={entry.action || '无'} /><DecisionLine label="结果" value={entry.outcome || '无'} /><DecisionLine label="原因" value={entry.reasoning || '无'} /></dl><details className="technical-details"><summary>结构化详情</summary><pre>{JSON.stringify(entry.details ?? {}, null, 2)}</pre></details></>
}

function DecisionLine({ label, value }: { label: string; value: string }) {
  return <><dt>{label}</dt><dd>{value}</dd></>
}

function Metric({ label, value }: { label: string; value: number }) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong></div>
}

function phaseLabel(phase: string): string {
  return { observe: '观察', think: '判断', act: '动作' }[phase] ?? phase
}

function pasteStatusMessage(result: PasteReplyResult): string {
  if (result.paste_action === 'sent_verified') return '已自动发送到微信，消息状态已更新为已发送'
  if (result.paste_action === 'filled_verified') return '已填入微信并校验，请检查后发送'
  if (result.paste_action === 'filled_unverified') return '已填入微信，但需要你检查内容'
  if (result.paste_action === 'target_not_found') return '未找到目标微信群，回复已复制到剪贴板'
  if (result.paste_action === 'input_not_empty') return '微信输入框已有内容，为避免覆盖，本次未填入'
  return result.message
}

function formatDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

export default App
