import { app, BrowserWindow, ipcMain, dialog, shell } from 'electron';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

let mainWindow;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    backgroundColor: '#09090b',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      nodeIntegration: false,
      contextIsolation: true,
      webSecurity: true
    },
    title: "Sculptor Pro",
  });

  const startUrl = process.env.ELECTRON_START_URL || 'http://localhost:5173';
  mainWindow.loadURL(startUrl);

  mainWindow.on('closed', function () {
    mainWindow = null;
  });
}

app.on('ready', createWindow);

app.on('window-all-closed', function () {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', function () {
  if (mainWindow === null) {
    createWindow();
  }
});

async function chooseFile(filters) {
  if (!mainWindow) {
    throw new Error('Main window is not available');
  }

  mainWindow.show();
  mainWindow.focus();

  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openFile'],
    filters
  });

  if (result.canceled || result.filePaths.length === 0) {
    return null;
  }

  return result.filePaths[0];
}

// === НОВАЯ ЧАСТЬ: Обработка выбора файла ===
ipcMain.handle('open-file-dialog', async () => {
  return chooseFile([
    { name: 'Movies', extensions: ['mp4', 'mkv', 'mov', 'avi'] }
  ]);
});

ipcMain.on('open-file-dialog', async (event) => {
  try {
    const filePath = await chooseFile([
      { name: 'Movies', extensions: ['mp4', 'mkv', 'mov', 'avi'] }
    ]);
    if (filePath) event.reply('selected-file', filePath);
  } catch (err) {
    console.error('[open-file-dialog]', err);
  }
});

ipcMain.handle('open-audio-dialog', async () => {
  return chooseFile([
    { name: 'Audio', extensions: ['mp3', 'wav', 'm4a', 'flac'] }
  ]);
});

ipcMain.on('open-audio-dialog', async (event) => {
  try {
    const filePath = await chooseFile([
      { name: 'Audio', extensions: ['mp3', 'wav', 'm4a', 'flac'] }
    ]);
    if (filePath) event.reply('selected-audio', filePath);
  } catch (err) {
    console.error('[open-audio-dialog]', err);
  }
});

ipcMain.handle('open-script-dialog', async () => {
  return chooseFile([
    { name: 'Script', extensions: ['docx', 'md', 'txt'] }
  ]);
});

ipcMain.on('open-script-dialog', async (event) => {
  try {
    const filePath = await chooseFile([
      { name: 'Script', extensions: ['docx', 'md', 'txt'] }
    ]);
    if (filePath) event.reply('selected-script', filePath);
  } catch (err) {
    console.error('[open-script-dialog]', err);
  }
});

ipcMain.on('open-folder', (event, path) => {
  shell.openPath(path);
});

async function getSunoCookieBundle(session) {
  const allCookies = await session.cookies.get({});
  const sunoCookies = allCookies.filter((cookie) => {
    const domain = (cookie.domain || '').replace(/^\./, '');
    return domain === 'suno.com' || domain.endsWith('.suno.com');
  });

  const byName = {};
  for (const cookie of sunoCookies) {
    byName[cookie.name] = cookie.value;
  }

  return {
    ...byName,
    __cookie_header: sunoCookies
      .map((cookie) => `${cookie.name}=${cookie.value}`)
      .join('; '),
    __cookie_domains: sunoCookies
      .map((cookie) => `${cookie.name}@${cookie.domain || 'host'}`)
      .join(', ')
  };
}

// === SUNO AUTHENTICATION ===
ipcMain.handle('suno-auth', async () => {
  return new Promise((resolve) => {
    (async () => {
      // 1. Clear ALL old suno.com cookies to force a fresh login
      const session = mainWindow.webContents.session;
      try {
        const oldCookies = await session.cookies.get({ domain: '.suno.com' });
        for (const c of oldCookies) {
          const url = `${c.secure ? 'https' : 'http'}://${c.domain.replace(/^\./, '')}${c.path}`;
          await session.cookies.remove(url, c.name);
        }
        console.log(`[Suno Auth] Cleared ${oldCookies.length} old suno.com cookies`);
      } catch (e) {
        console.error('[Suno Auth] Error clearing old cookies:', e);
      }

      // 2. Open auth window with a clean session (shared with main)
      let authWindow = new BrowserWindow({
        width: 900,
        height: 700,
        title: "Login to Suno",
        webPreferences: {
          nodeIntegration: false,
          contextIsolation: true,
          session: session
        }
      });

      let resolved = false;

      // 3. Check for FRESH session cookies after user logs in
      const checkCookies = async () => {
        try {
          if (!authWindow || resolved) return;
          const cookies = await authWindow.webContents.session.cookies.get({});
          const sunoCookies = cookies.filter((cookie) => {
            const domain = (cookie.domain || '').replace(/^\./, '');
            return domain === 'suno.com' || domain.endsWith('.suno.com');
          });

          const cookieObj = {};
          sunoCookies.forEach(c => { cookieObj[c.name] = c.value; });

          if (cookieObj['__client_uat'] && (cookieObj['__client_session'] || cookieObj['__session'])) {
            resolved = true;
            clearInterval(interval);

            // Give Clerk/Suno a short moment to persist same-site and subdomain cookies.
            setTimeout(async () => {
              try {
                const bundle = await getSunoCookieBundle(session);
                console.log('[Suno Auth] ✅ Detected fresh login cookies:', bundle.__cookie_domains || Object.keys(bundle).join(', '));
                if (authWindow && !authWindow.isDestroyed()) {
                  authWindow.close();
                }
                resolve(bundle);
              } catch (e) {
                console.error('[Suno Auth] Error building cookie bundle:', e);
                if (authWindow && !authWindow.isDestroyed()) {
                  authWindow.close();
                }
                resolve(cookieObj);
              }
            }, 2500);
          }
        } catch {
          // Window may be closing
        }
      };

      const interval = setInterval(checkCookies, 1500);

      authWindow.on('closed', () => {
        clearInterval(interval);
        authWindow = null;
        if (!resolved) {
          console.log('[Suno Auth] ⚠️ Auth window closed without detecting login');
          getSunoCookieBundle(session)
            .then(bundle => {
              if (bundle['__client_session'] || bundle['__session']) {
                resolve(bundle);
              } else {
                resolve(null);
              }
            }).catch(() => resolve(null));
        }
      });

      authWindow.loadURL('https://suno.com');
      console.log('[Suno Auth] Opened auth window at https://suno.com');
    })();
  });
});

ipcMain.handle('suno-cookies', async () => {
  try {
    const cookieObj = await getSunoCookieBundle(mainWindow.webContents.session);
    
    // Check if valid
    if (cookieObj['__client_session'] || cookieObj['__session']) {
      return cookieObj;
    }
  } catch (e) {
    console.error("Cookie fetch error", e);
  }
  return null;
});
