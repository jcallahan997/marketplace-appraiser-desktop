/**
 * Marketplace Appraiser — Electron main process.
 *
 * Single window: Facebook Marketplace (left) + Dashboard (right).
 * Resizable split starting at 2:1 ratio.
 * Spawns FastAPI backend as a child process, connects via CDP for scraping.
 */

const { app, BaseWindow, WebContentsView } = require("electron");
const { spawn } = require("child_process");
const http = require("http");
const path = require("path");

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const PROJECT_DIR = app.isPackaged
  ? path.join(app.getPath("home"), "Projects", "agentic-marketplace-appraiser")
  : path.resolve(__dirname, "..");
const PYTHON = path.join(PROJECT_DIR, ".venv", "bin", "python");
const CDP_PORT = "9223";
const API_PORT = 8000;
const API_HOST = "127.0.0.1";
const DIVIDER_WIDTH = 6;
const MIN_PANEL_FRACTION = 0.15;
const LISTING_PATTERN = /facebook\.com\/marketplace\/item\/\d+/;
const isDev = process.argv.includes("--dev");

let splitRatio = 2 / 3; // 2:1 left-to-right

// Must be called before app.whenReady()
app.commandLine.appendSwitch("remote-debugging-port", CDP_PORT);

// ---------------------------------------------------------------------------
// Divider HTML (loaded as data URL for resizable split handle)
// ---------------------------------------------------------------------------

const DIVIDER_HTML = `<!DOCTYPE html><html><head><style>
*{margin:0;padding:0}html,body{height:100%;overflow:hidden}
body{cursor:col-resize}
#h{width:100%;height:100%;background:#d1d5db;transition:background .1s}
#h:hover{background:#9ca3af}
body.d #h{display:none}
</style></head><body><div id="h"></div><script>
let d=false;
document.addEventListener('mousedown',e=>{e.preventDefault();d=true;document.body.classList.add('d');console.log('drag:start')});
document.addEventListener('mousemove',e=>{if(d){e.preventDefault();console.log('drag:move:'+e.clientX)}});
document.addEventListener('mouseup',()=>{if(d){d=false;document.body.classList.remove('d');console.log('drag:end')}});
document.addEventListener('selectstart',e=>{if(d)e.preventDefault()});
</script></body></html>`;

// ---------------------------------------------------------------------------
// FastAPI child process
// ---------------------------------------------------------------------------

let fastapiProcess = null;

function startFastAPI() {
  console.log("[Electron] Starting FastAPI backend...");

  fastapiProcess = spawn(
    PYTHON,
    [
      "-m",
      "uvicorn",
      "marketplace_appraiser.server:app",
      "--host",
      API_HOST,
      "--port",
      String(API_PORT),
    ],
    {
      cwd: PROJECT_DIR,
      env: {
        ...process.env,
        CHROME_CDP_URL: `http://localhost:${CDP_PORT}`,
        PYTHONDONTWRITEBYTECODE: "1",
      },
      stdio: ["ignore", "pipe", "pipe"],
      detached: false,
    }
  );

  fastapiProcess.stdout.on("data", (data) => {
    process.stdout.write(`[FastAPI] ${data}`);
  });

  fastapiProcess.stderr.on("data", (data) => {
    process.stderr.write(`[FastAPI] ${data}`);
  });

  fastapiProcess.on("error", (err) => {
    console.error("[Electron] Failed to start FastAPI:", err.message);
  });

  fastapiProcess.on("exit", (code) => {
    console.log(`[Electron] FastAPI exited with code ${code}`);
    fastapiProcess = null;
  });
}

function stopFastAPI() {
  if (!fastapiProcess || fastapiProcess.killed) return;
  console.log("[Electron] Stopping FastAPI...");
  fastapiProcess.kill("SIGTERM");
  setTimeout(() => {
    if (fastapiProcess && !fastapiProcess.killed) {
      fastapiProcess.kill("SIGKILL");
    }
  }, 2000);
}

function waitForHealth(maxAttempts = 30, intervalMs = 500) {
  return new Promise((resolve, reject) => {
    let attempts = 0;
    const poll = () => {
      attempts++;
      const req = http.get(
        `http://${API_HOST}:${API_PORT}/api/health`,
        (res) => {
          let body = "";
          res.on("data", (chunk) => (body += chunk));
          res.on("end", () => {
            if (res.statusCode === 200) {
              console.log(
                `[Electron] FastAPI ready after ${attempts} attempt(s).`
              );
              resolve();
            } else {
              retry();
            }
          });
        }
      );
      req.on("error", retry);
      req.setTimeout(1000, retry);

      function retry() {
        req.destroy();
        if (attempts >= maxAttempts) {
          reject(
            new Error(
              `FastAPI did not start within ${maxAttempts * intervalMs}ms`
            )
          );
        } else {
          setTimeout(poll, intervalMs);
        }
      }
    };
    poll();
  });
}

// ---------------------------------------------------------------------------
// Window + panels
// ---------------------------------------------------------------------------

let mainWindow = null;
let leftView = null;
let rightView = null;
let dividerView = null;
let isDragging = false;
let lastDetectedUrl = "";
let urlPollInterval = null;

function layoutPanels() {
  if (!mainWindow || !leftView || !rightView || !dividerView) return;
  const { width, height } = mainWindow.getContentBounds();
  const divPos = Math.round(width * splitRatio);

  leftView.setBounds({ x: 0, y: 0, width: divPos, height });

  if (isDragging) {
    // During drag: expand divider to full window to capture mouse events
    dividerView.setBounds({ x: 0, y: 0, width, height });
  } else {
    dividerView.setBounds({ x: divPos, y: 0, width: DIVIDER_WIDTH, height });
  }

  const rightX = divPos + DIVIDER_WIDTH;
  rightView.setBounds({ x: rightX, y: 0, width: Math.max(0, width - rightX), height });
}

function handleUrlChange(url) {
  if (!LISTING_PATTERN.test(url)) return;
  if (url === lastDetectedUrl) return;
  lastDetectedUrl = url;
  console.log("[Electron] Detected listing URL:", url);

  // Send to dashboard via preload bridge
  if (rightView) {
    rightView.webContents
      .executeJavaScript(
        `window.electronBridge && window.electronBridge.onListingDetected(${JSON.stringify(url)})`
      )
      .catch(() => {
        /* page not ready yet */
      });
  }
}

function createWindow() {
  mainWindow = new BaseWindow({
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 600,
    title: "Marketplace Appraiser",
  });

  // Left panel — Facebook Marketplace (uses defaultSession for cookie persistence)
  leftView = new WebContentsView({
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      sandbox: true,
      contextIsolation: true,
    },
  });

  // Right panel — Dashboard
  rightView = new WebContentsView({
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      sandbox: true,
      contextIsolation: true,
    },
  });

  // Divider — resizable split handle
  dividerView = new WebContentsView({
    webPreferences: { sandbox: true, contextIsolation: true },
  });

  // Add views (divider last = topmost for mouse capture during drag)
  mainWindow.contentView.addChildView(leftView);
  mainWindow.contentView.addChildView(rightView);
  mainWindow.contentView.addChildView(dividerView);
  layoutPanels();

  // Load divider UI
  dividerView.setBackgroundColor("#00000000");
  dividerView.webContents.loadURL(
    "data:text/html;charset=utf-8," + encodeURIComponent(DIVIDER_HTML)
  );

  // Divider drag handling via console messages from inline page
  dividerView.webContents.on("console-message", (_event, _level, message) => {
    if (message === "drag:start") {
      isDragging = true;
      layoutPanels();
    } else if (message.startsWith("drag:move:") && isDragging) {
      const clientX = parseInt(message.split(":")[2], 10);
      if (!isNaN(clientX)) {
        const { width, height } = mainWindow.getContentBounds();
        splitRatio = Math.max(
          MIN_PANEL_FRACTION,
          Math.min(1 - MIN_PANEL_FRACTION, clientX / width)
        );
        const divPos = Math.round(width * splitRatio);
        leftView.setBounds({ x: 0, y: 0, width: divPos, height });
        const rightX = divPos + DIVIDER_WIDTH;
        rightView.setBounds({
          x: rightX,
          y: 0,
          width: Math.max(0, width - rightX),
          height,
        });
      }
    } else if (message === "drag:end") {
      isDragging = false;
      layoutPanels();
    }
  });

  // Set a Chrome-like user-agent so Facebook doesn't block us
  const chromeUA =
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) " +
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";
  leftView.webContents.setUserAgent(chromeUA);

  // Load URLs
  leftView.webContents.loadURL("https://www.facebook.com/marketplace");

  const dashboardUrl = isDev
    ? "http://localhost:3000"
    : `http://${API_HOST}:${API_PORT}`;
  rightView.webContents.loadURL(dashboardUrl);

  // Resize handler
  mainWindow.on("resize", layoutPanels);

  // URL detection — navigation events
  leftView.webContents.on("did-navigate", (_event, url) => {
    handleUrlChange(url);
  });
  leftView.webContents.on("did-navigate-in-page", (_event, url) => {
    handleUrlChange(url);
  });

  // Fallback: poll for SPA navigations that don't fire events
  urlPollInterval = setInterval(() => {
    if (leftView && !leftView.webContents.isDestroyed()) {
      const url = leftView.webContents.getURL();
      handleUrlChange(url);
    }
  }, 1000);

  // Clean up WebContentsView on close (prevent memory leaks)
  mainWindow.on("close", () => {
    clearInterval(urlPollInterval);
    for (const view of [leftView, rightView, dividerView]) {
      if (view && !view.webContents.isDestroyed()) {
        view.webContents.close();
      }
    }
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
    leftView = null;
    rightView = null;
    dividerView = null;
  });
}

// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------

app.whenReady().then(async () => {
  try {
    startFastAPI();
    await waitForHealth();
    createWindow();
  } catch (err) {
    console.error("[Electron] Startup failed:", err.message);
    stopFastAPI();
    app.quit();
  }
});

app.on("window-all-closed", () => {
  app.quit();
});

app.on("before-quit", () => {
  stopFastAPI();
});
