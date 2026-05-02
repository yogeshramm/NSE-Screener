'use strict'

const { contextBridge, ipcRenderer } = require('electron')

/**
 * Expose a safe native bridge to the renderer (moneystx.com page).
 * The web page can call window.mx.* to interact with the desktop shell.
 */
contextBridge.exposeInMainWorld('mx', {
  /**
   * Set the macOS dock badge count.
   * Call with 0 to clear it.
   * Usage: window.mx.setBadge(42)
   */
  setBadge: (count) => {
    ipcRenderer.send('set-badge', Math.max(0, parseInt(count) || 0))
  },

  /**
   * Show a system notification.
   * Usage: window.mx.notify('Screener', '12 stocks matched your criteria')
   */
  notify: (title, body) => {
    ipcRenderer.send('notify', { title: String(title), body: String(body) })
  },

  /** True when running inside the desktop app. */
  isDesktop: true,

  /** Platform string: 'darwin' | 'win32' | 'linux' */
  platform: process.platform,
})
