import { contextBridge, ipcRenderer } from 'electron'
import type { DesktopApi, DesktopSettings } from '../shared/types'

const desktopApi: DesktopApi = {
  getStatus: () => ipcRenderer.invoke('app:getStatus'),
  start: () => ipcRenderer.invoke('app:start'),
  stop: () => ipcRenderer.invoke('app:stop'),
  getSettings: () => ipcRenderer.invoke('app:getSettings'),
  saveSettings: (settings: Partial<DesktopSettings>) => ipcRenderer.invoke('app:saveSettings', settings),
  openSettings: () => ipcRenderer.invoke('settings:open'),
  openAdvanced: (page: string) => ipcRenderer.invoke('advanced:open', page)
}

contextBridge.exposeInMainWorld('desktop', desktopApi)
