'use strict'

const { app, BrowserWindow, BrowserView, shell, Menu, ipcMain, dialog, nativeTheme } = require('electron')
const path = require('path')
const fs   = require('fs')

// ── Constants ─────────────────────────────────────────────────────────────────
const APP_URL    = 'https://moneystx.com'
const STATE_FILE = path.join(app.getPath('userData'), 'window-state.json')

// ── Window state persistence ──────────────────────────────────────────────────
function loadState() {
  try { return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8')) } catch { return {} }
}
function saveState(win) {
  if (win.isMaximized() || win.isMinimized()) return
  try { fs.writeFileSync(STATE_FILE, JSON.stringify(win.getBounds())) } catch {}
}

// ── Navigate the web page to a tab via JS injection ──────────────────────────
function goTab(win, tab) {
  win.webContents.executeJavaScript(
    `if (typeof switchTab === 'function') switchTab('${tab}')`,
    true
  ).catch(() => {})
}

// ── Build the native macOS application menu ───────────────────────────────────
function buildMenu(win) {
  const isMac = process.platform === 'darwin'

  const template = [
    // ── App menu (macOS only) ────────────────────────────────────────
    ...(isMac ? [{
      label: app.name,
      submenu: [
        {
          label: 'About MONEYSTX',
          click: () => showAbout(win),
        },
        { type: 'separator' },
        { role: 'services' },
        { type: 'separator' },
        { role: 'hide' },
        { role: 'hideOthers' },
        { role: 'unhide' },
        { type: 'separator' },
        { role: 'quit' },
      ],
    }] : []),

    // ── View ─────────────────────────────────────────────────────────
    {
      label: 'View',
      submenu: [
        {
          label: 'Reload',
          accelerator: 'CmdOrCtrl+R',
          click: () => win.webContents.reload(),
        },
        {
          label: 'Developer Tools',
          accelerator: 'CmdOrCtrl+Alt+I',
          click: () => win.webContents.toggleDevTools(),
        },
        { type: 'separator' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { type: 'separator' },
        { role: 'togglefullscreen' },
      ],
    },

    // ── Go (tab navigation) ───────────────────────────────────────────
    {
      label: 'Go',
      submenu: [
        {
          label: 'Dashboard',
          accelerator: 'CmdOrCtrl+1',
          click: () => goTab(win, 'home'),
        },
        {
          label: 'Screener',
          accelerator: 'CmdOrCtrl+2',
          click: () => goTab(win, 'screener'),
        },
        {
          label: 'Watchlist',
          accelerator: 'CmdOrCtrl+3',
          click: () => goTab(win, 'watchlist'),
        },
        {
          label: 'Breakouts',
          accelerator: 'CmdOrCtrl+4',
          click: () => goTab(win, 'breakouts'),
        },
        {
          label: 'Backtester',
          accelerator: 'CmdOrCtrl+5',
          click: () => goTab(win, 'backtest'),
        },
        {
          label: 'Events',
          accelerator: 'CmdOrCtrl+6',
          click: () => goTab(win, 'events'),
        },
        {
          label: 'Practice',
          accelerator: 'CmdOrCtrl+7',
          click: () => goTab(win, 'practice'),
        },
        {
          label: 'Portfolio',
          accelerator: 'CmdOrCtrl+8',
          click: () => goTab(win, 'portfolio'),
        },
        { type: 'separator' },
        {
          label: 'Run Screener',
          accelerator: 'CmdOrCtrl+Return',
          click: () => {
            win.webContents.executeJavaScript(
              `if (typeof runScreenAll === 'function') { switchTab('screener'); setTimeout(runScreenAll, 100); }`,
              true
            ).catch(() => {})
          },
        },
        {
          label: 'Focus Search',
          accelerator: 'CmdOrCtrl+F',
          click: () => {
            win.webContents.executeJavaScript(
              `const el = document.getElementById('symbols-input'); if (el) { switchTab('screener'); el.focus(); el.select(); }`,
              true
            ).catch(() => {})
          },
        },
      ],
    },

    // ── Window ────────────────────────────────────────────────────────
    { role: 'windowMenu' },

    // ── Help ──────────────────────────────────────────────────────────
    {
      role: 'help',
      submenu: [
        {
          label: 'Open moneystx.com in Browser',
          click: () => shell.openExternal(APP_URL),
        },
        { type: 'separator' },
        {
          label: 'About MONEYSTX',
          click: () => showAbout(win),
        },
      ],
    },
  ]

  return Menu.buildFromTemplate(template)
}

// ── About dialog ──────────────────────────────────────────────────────────────
function showAbout(win) {
  dialog.showMessageBox(win, {
    type:    'none',
    title:   'MONEYSTX',
    message: 'MONEYSTX — Institutional Intelligence Terminal',
    detail:  `Version ${app.getVersion()}\n\nNSE swing-trading screener with 25 indicators, 2-stage filter, real-time charts, and candlestick pattern scanner.\n\nBuilt for Indian markets. Educational use only — not SEBI-registered investment advice.\n\nmoneystx.com`,
    icon:    path.join(__dirname, 'assets', 'icon.png'),
    buttons: ['OK'],
  })
}

// ── Create main window ────────────────────────────────────────────────────────
function createWindow() {
  const state = loadState()

  const win = new BrowserWindow({
    width:       state.width  || 1440,
    height:      state.height || 860,
    x:           state.x,
    y:           state.y,
    minWidth:    960,
    minHeight:   640,
    title:       'MONEYSTX',
    icon:        path.join(__dirname, 'assets', 'icon.png'),
    backgroundColor: '#050505',
    show:        false,
    // macOS: traffic-light buttons inside the window (like VS Code / Arc)
    titleBarStyle:      process.platform === 'darwin' ? 'hiddenInset' : 'default',
    trafficLightPosition: { x: 16, y: 16 },
    webPreferences: {
      nodeIntegration:  false,
      contextIsolation: true,
      spellcheck:       false,
      preload:          path.join(__dirname, 'preload.js'),
    },
  })

  // Set menu
  Menu.setApplicationMenu(buildMenu(win))

  // Load the app
  win.loadURL(APP_URL)

  // Show when ready — avoids white flash
  win.once('ready-to-show', () => {
    win.show()
    // Start in dark mode by default to match the app
    nativeTheme.themeSource = 'dark'
  })

  // Offline fallback
  win.webContents.on('did-fail-load', (_e, code) => {
    if ([-2, -6, -105, -106, -21, -3].includes(code)) {
      win.loadFile(path.join(__dirname, 'offline.html'))
    }
  })

  // External links → system browser
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })

  // Persist window bounds
  win.on('resize', () => saveState(win))
  win.on('move',   () => saveState(win))

  return win
}

// ── IPC: dock badge (called from preload → renderer) ─────────────────────────
ipcMain.on('set-badge', (_e, count) => {
  if (process.platform === 'darwin') {
    app.dock.setBadge(count > 0 ? String(count) : '')
  }
})

// ── IPC: send notification ────────────────────────────────────────────────────
ipcMain.on('notify', (_e, { title, body }) => {
  const { Notification } = require('electron')
  if (Notification.isSupported()) {
    new Notification({ title, body, silent: false }).show()
  }
})

// ── App lifecycle ─────────────────────────────────────────────────────────────
app.whenReady().then(createWindow)

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow()
})

// ── Set app user model id (Windows) ──────────────────────────────────────────
if (process.platform === 'win32') {
  app.setAppUserModelId('com.moneystx.app')
}
