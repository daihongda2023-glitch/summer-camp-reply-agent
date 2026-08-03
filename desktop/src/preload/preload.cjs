const { contextBridge, ipcRenderer } = require('electron')

const desktopApi = {
  getStatus: () => ipcRenderer.invoke('app:getStatus'),
  start: () => ipcRenderer.invoke('app:start'),
  stop: () => ipcRenderer.invoke('app:stop'),
  getSettings: () => ipcRenderer.invoke('app:getSettings'),
  saveSettings: (settings) => ipcRenderer.invoke('app:saveSettings', settings),
  getWorkTrace: () => ipcRenderer.invoke('app:getWorkTrace'),
  loadDemo: () => ipcRenderer.invoke('app:loadDemo'),
  getItems: (scope = 'pending', reviewStatus = '') => ipcRenderer.invoke('workbench:getItems', scope, reviewStatus),
  ask: (question) => ipcRenderer.invoke('workbench:ask', question),
  pasteReply: (eventId, reply) => ipcRenderer.invoke('workbench:pasteReply', eventId, reply),
  publishReply: (eventId, reply) => ipcRenderer.invoke('workbench:publishReply', eventId, reply),
  confirmSent: (eventId, reply) => ipcRenderer.invoke('workbench:confirmSent', eventId, reply),
  saveCandidate: (eventId, reply) => ipcRenderer.invoke('workbench:saveCandidate', eventId, reply),
  escalateMessage: (eventId, note) => ipcRenderer.invoke('workbench:escalateMessage', eventId, note),
  completeReview: (eventId, note) => ipcRenderer.invoke('workbench:completeReview', eventId, note),
  startVision: () => ipcRenderer.invoke('vision:start'),
  stopVision: () => ipcRenderer.invoke('vision:stop'),
  captureVision: () => ipcRenderer.invoke('vision:capture'),
  getVisionStatus: () => ipcRenderer.invoke('vision:getStatus'),
  openSettings: () => ipcRenderer.invoke('settings:open'),
  openAdvanced: (page) => ipcRenderer.invoke('advanced:open', page)
}

contextBridge.exposeInMainWorld('desktop', desktopApi)
