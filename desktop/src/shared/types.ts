export type EngineStatus = 'idle' | 'starting' | 'running' | 'error'

export interface DesktopSettings {
  window: Record<string, number>
  main_view: {
    show_target: boolean
    show_recent_logs: boolean
    show_history_entry: boolean
    show_status_detail: boolean
    show_assist_actions: boolean
  }
  advanced_pages: {
    messages: boolean
    candidates: boolean
    work_trace: boolean
    rag: boolean
  }
}

export interface WeChatBridgeSettings {
  use_weflow: boolean
  base_url: string
  token_env: string
  group_name: string
  session_id: string
  keywords: string[]
  poll_interval_seconds: number
  enabled: boolean
  show_debug_config: boolean
  send_mode: string
}

export interface ReplySettings {
  mode: string
  auto_reply_intents: string[]
  daily_auto_reply_limit: number
}

export interface AppStatus {
  engine: {
    status: EngineStatus
    listener_running: boolean
    use_weflow: boolean
    group_name: string
    send_mode: string
    poll_interval_seconds: number
  }
  settings: DesktopSettings
  recent_logs: string[]
}

export interface AppSettingsPayload {
  settings: DesktopSettings
  wechat: WeChatBridgeSettings
  reply: ReplySettings
}

export interface WorkTraceEntry {
  trace_id: string
  created_at: string
  event_id: string
  group_name: string
  phase: 'observe' | 'think' | 'act' | string
  summary: string
  actor: string
  action: string
  outcome: string
  reasoning: string
  details: Record<string, unknown>
}

export interface WorkTracePayload {
  trace: WorkTraceEntry[]
  summary: {
    total: number
    observed: number
    thought: number
    acted: number
  }
}

export type AppSettingsUpdate = Partial<DesktopSettings> & {
  wechat?: Partial<WeChatBridgeSettings>
  reply?: Partial<ReplySettings>
}

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
  target_status: string
  input_status: string
  verification_status: string
  fallback_reason: string
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

export interface DesktopApi {
  getStatus(): Promise<AppStatus>
  start(): Promise<AppStatus>
  stop(): Promise<AppStatus>
  getSettings(): Promise<AppSettingsPayload>
  saveSettings(settings: AppSettingsUpdate): Promise<AppSettingsPayload>
  getWorkTrace(): Promise<WorkTracePayload>
  loadDemo(): Promise<void>
  getItems(): Promise<WorkbenchItemsPayload>
  ask(question: string): Promise<WorkbenchItemPayload>
  pasteReply(eventId: string, reply: string): Promise<PasteReplyResult>
  publishReply(eventId: string, reply: string): Promise<PasteReplyResult>
  confirmSent(eventId: string, reply: string): Promise<ActionResult>
  saveCandidate(eventId: string, reply: string): Promise<ActionResult>
  startVision(): Promise<VisionCapturePayload>
  stopVision(): Promise<VisionCapturePayload>
  captureVision(): Promise<VisionCapturePayload>
  getVisionStatus(): Promise<VisionStatus>
  openSettings(): Promise<void>
  openAdvanced(page: string): Promise<void>
}
