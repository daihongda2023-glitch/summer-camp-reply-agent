const { contextBridge, ipcRenderer } = require('electron')

const desktopApi = {
  getStatus: () => ipcRenderer.invoke('app:getStatus'),
  start: () => ipcRenderer.invoke('app:start'),
  stop: () => ipcRenderer.invoke('app:stop'),
  getSettings: () => ipcRenderer.invoke('app:getSettings'),
  saveSettings: (settings) => ipcRenderer.invoke('app:saveSettings', settings),
  openSettings: () => ipcRenderer.invoke('settings:open'),
  openAdvanced: (page) => ipcRenderer.invoke('advanced:open', page)
}

contextBridge.exposeInMainWorld('desktop', desktopApi)
