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

export interface AppStatus {
  engine: {
    status: EngineStatus
    listener_running: boolean
    group_name: string
  }
  settings: DesktopSettings
  recent_logs: string[]
}

export interface AppSettingsPayload {
  settings: DesktopSettings
  wechat: Record<string, unknown>
  reply: Record<string, unknown>
}

export interface DesktopApi {
  getStatus(): Promise<AppStatus>
  start(): Promise<AppStatus>
  stop(): Promise<AppStatus>
  getSettings(): Promise<AppSettingsPayload>
  saveSettings(settings: Partial<DesktopSettings>): Promise<AppSettingsPayload>
  openSettings(): Promise<void>
  openAdvanced(page: string): Promise<void>
}
