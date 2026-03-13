/**
 * Preload script — exposes a minimal bridge for URL auto-fill.
 *
 * The main process calls executeJavaScript on the right panel to invoke
 * window.electronBridge.onListingDetected(url), which triggers the
 * callback registered by the dashboard's Controls component.
 */

const { contextBridge } = require("electron");

let listingCallback = null;

contextBridge.exposeInMainWorld("electronBridge", {
  /** Called by main process via executeJavaScript when a listing URL is detected. */
  onListingDetected: (url) => {
    if (listingCallback) listingCallback(url);
  },

  /** Called by the dashboard to register its URL handler. */
  setListingCallback: (cb) => {
    listingCallback = cb;
  },

  /** True when running inside Electron. */
  isElectron: true,
});
