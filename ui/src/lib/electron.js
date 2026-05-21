const fallback = {
  isElectron: false,
  openFileDialog: async () => {
    throw new Error('Electron preload API is unavailable');
  },
  openAudioDialog: async () => {
    throw new Error('Electron preload API is unavailable');
  },
  openScriptDialog: async () => {
    throw new Error('Electron preload API is unavailable');
  },
  openFolder: () => {},
  onSelectedFile: () => () => {},
  onSelectedAudio: () => () => {},
  onSelectedScript: () => () => {},
  sunoAuth: async () => null,
  sunoCookies: async () => null,
};

export const electronAPI = globalThis.window?.electronAPI
  ? { isElectron: true, ...globalThis.window.electronAPI }
  : fallback;
