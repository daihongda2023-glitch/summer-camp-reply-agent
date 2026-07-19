import { contextBridge, ipcRenderer } from 'electron'
import type { AppSettingsUpdate, DesktopApi } from '../shared/types'

const desktopApi: DesktopApi = {
  getStatus: () => ipcRenderer.invoke('app:getStatus'),
  start: () => ipcRenderer.invoke('app:start'),
  stop: () => ipcRenderer.invoke('app:stop'),
  getSettings: () => ipcRenderer.invoke('app:getSettings'),
  saveSettings: (settings: AppSettingsUpdate) => ipcRenderer.invoke('app:saveSettings', settings),
  getWorkTrace: () => ipcRenderer.invoke('app:getWorkTrace'),
  loadDemo: () => ipcRenderer.invoke('app:loadDemo'),
  getItems: () => ipcRenderer.invoke('workbench:getItems'),
  ask: (question: string) => ipcRenderer.invoke('workbench:ask', question),
  pasteReply: (eventId: string, reply: string) => ipcRenderer.invoke('workbench:pasteReply', eventId, reply),
  publishReply: (eventId: string, reply: string) => ipcRenderer.invoke('workbench:publishReply', eventId, reply),
  confirmSent: (eventId: string, reply: string) => ipcRenderer.invoke('workbench:confirmSent', eventId, reply),
  saveCandidate: (eventId: string, reply: string) => ipcRenderer.invoke('workbench:saveCandidate', eventId, reply),
  startVision: () => ipcRenderer.invoke('vision:start'),
  stopVision: () => ipcRenderer.invoke('vision:stop'),
  captureVision: () => ipcRenderer.invoke('vision:capture'),
  getVisionStatus: () => ipcRenderer.invoke('vision:getStatus'),
  openSettings: () => ipcRenderer.invoke('settings:open'),
  openAdvanced: (page: string) => ipcRenderer.invoke('advanced:open', page)
}

contextBridge.exposeInMainWorld('desktop', desktopApi)
