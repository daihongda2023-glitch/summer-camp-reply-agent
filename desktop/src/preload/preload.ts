import { contextBridge, ipcRenderer } from 'electron'
import type { AppSettingsUpdate, DesktopApi, MessageScope, ReviewStatus } from '../shared/types'

const desktopApi: DesktopApi = {
  getStatus: () => ipcRenderer.invoke('app:getStatus'),
  getReadiness: () => ipcRenderer.invoke('app:getReadiness'),
  start: () => ipcRenderer.invoke('app:start'),
  stop: () => ipcRenderer.invoke('app:stop'),
  getSettings: () => ipcRenderer.invoke('app:getSettings'),
  saveSettings: (settings: AppSettingsUpdate) => ipcRenderer.invoke('app:saveSettings', settings),
  getWorkTrace: () => ipcRenderer.invoke('app:getWorkTrace'),
  loadDemo: () => ipcRenderer.invoke('app:loadDemo'),
  getItems: (scope: MessageScope = 'pending', reviewStatus: ReviewStatus | '' = '') =>
    ipcRenderer.invoke('workbench:getItems', scope, reviewStatus),
  ask: (question: string) => ipcRenderer.invoke('workbench:ask', question),
  pasteReply: (eventId: string, reply: string) => ipcRenderer.invoke('workbench:pasteReply', eventId, reply),
  publishReply: (eventId: string, reply: string) => ipcRenderer.invoke('workbench:publishReply', eventId, reply),
  confirmSent: (eventId: string, reply: string) => ipcRenderer.invoke('workbench:confirmSent', eventId, reply),
  saveCandidate: (eventId: string, reply: string) => ipcRenderer.invoke('workbench:saveCandidate', eventId, reply),
  escalateMessage: (eventId: string, note: string) => ipcRenderer.invoke('workbench:escalateMessage', eventId, note),
  completeReview: (eventId: string, note: string) => ipcRenderer.invoke('workbench:completeReview', eventId, note),
  startVision: () => ipcRenderer.invoke('vision:start'),
  stopVision: () => ipcRenderer.invoke('vision:stop'),
  captureVision: () => ipcRenderer.invoke('vision:capture'),
  getVisionStatus: () => ipcRenderer.invoke('vision:getStatus'),
  openSettings: () => ipcRenderer.invoke('settings:open'),
  openAdvanced: (page: string) => ipcRenderer.invoke('advanced:open', page),
  openExternal: (url: string) => ipcRenderer.invoke('app:openExternal', url)
}

contextBridge.exposeInMainWorld('desktop', desktopApi)
