const { contextBridge, ipcRenderer } = require('electron');

function subscribe(channel, callback) {
  if (typeof callback !== 'function') {
    return () => {};
  }

  const listener = (_event, payload) => callback(payload);
  ipcRenderer.on(channel, listener);
  return () => ipcRenderer.removeListener(channel, listener);
}

contextBridge.exposeInMainWorld('electronAPI', {
  openFileDialog: () => ipcRenderer.invoke('open-file-dialog'),
  openAudioDialog: () => ipcRenderer.invoke('open-audio-dialog'),
  openScriptDialog: () => ipcRenderer.invoke('open-script-dialog'),
  openFolder: (targetPath) => ipcRenderer.send('open-folder', targetPath),
  onSelectedFile: (callback) => subscribe('selected-file', callback),
  onSelectedAudio: (callback) => subscribe('selected-audio', callback),
  onSelectedScript: (callback) => subscribe('selected-script', callback),
  sunoAuth: () => ipcRenderer.invoke('suno-auth'),
  sunoCookies: () => ipcRenderer.invoke('suno-cookies'),
});
