#!/usr/bin/env node
// Exercise the actual Windows/WebView2 desktop without npm dependencies.
// Requires Windows, Go from go.mod, WebView2 and Node.js >= 22.
// Run from any directory: node go-app/scripts/test-windows-ui.mjs
// Test-only Go overlays leave the application sources and module cache intact.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { basename, dirname, join, resolve } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';

assert.equal(process.platform, 'win32', 'This test requires a Windows desktop');
assert.ok(Number(process.versions.node.split('.')[0]) >= 22, 'Node.js >= 22 is required');

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const temporary = await mkdtemp(join(tmpdir(), 'fte-windows-ui-'));
const children = [];
const waitMS = 18_000;
let app;
let log = '';

function replaceOnce(source, before, after) {
  assert.equal(source.split(before).length, 2, `Overlay anchor must occur once: ${before}`);
  return source.replace(before, after);
}

async function waitFor(label, probe, timeout = waitMS) {
  const deadline = Date.now() + timeout;
  let lastError;
  while (Date.now() < deadline) {
    if (app && app.exitCode !== null) throw new Error(`App exited with ${app.exitCode}\n${log}`);
    try {
      const result = await probe();
      if (result) return result;
    } catch (error) {
      lastError = error;
    }
    await delay(150);
  }
  throw new Error(`Timed out: ${label}${lastError ? ` (${lastError.message})` : ''}`);
}

function start(executable, args = [], options = {}) {
  const child = spawn(executable, args, {
    cwd: root,
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
    ...options,
  });
  children.push(child);
  return child;
}

async function completed(child, timeout) {
  if (child.exitCode !== null) return child.exitCode;
  const [code, signal] = await once(child, 'exit', { signal: AbortSignal.timeout(timeout) });
  assert.equal(signal, null, `Process ${child.pid} was terminated by ${signal}`);
  return code;
}

async function json(url) {
  const response = await fetch(url, { signal: AbortSignal.timeout(1500) });
  assert.ok(response.ok, `${url}: HTTP ${response.status}`);
  return response.json();
}

class CDP {
  constructor(socket) {
    this.socket = socket;
    this.sequence = 0;
    this.pending = new Map();
    socket.addEventListener('message', event => {
      const message = JSON.parse(String(event.data));
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      clearTimeout(pending.timer);
      if (message.error) pending.reject(new Error(message.error.message));
      else pending.resolve(message.result);
    });
    socket.addEventListener('close', () => {
      for (const pending of this.pending.values()) {
        clearTimeout(pending.timer);
        pending.reject(new Error('CDP connection closed'));
      }
      this.pending.clear();
    });
  }

  static async connect(url) {
    const socket = new WebSocket(url);
    try {
      await once(socket, 'open', { signal: AbortSignal.timeout(2000) });
      return new CDP(socket);
    } catch (error) {
      socket.close();
      throw error;
    }
  }

  call(method, params = {}, timeout = 3000) {
    return new Promise((resolve, reject) => {
      const id = ++this.sequence;
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`CDP timed out: ${method}`));
      }, timeout);
      this.pending.set(id, { resolve, reject, timer });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  async evaluate(expression) {
    const result = await this.call('Runtime.evaluate', {
      expression, awaitPromise: true, returnByValue: true,
    });
    assert.ok(!result.exceptionDetails,
      result.exceptionDetails?.exception?.description || 'JavaScript evaluation failed');
    return result.result.value;
  }

  close() { this.socket.close(); }
}

// This checks delivery and execution: app.js must have requested its initial
// state, and CSS must have created the app layout. API checks run outside the
// page so the test cannot create the resource entry it is looking for.
const inspectUI = `(() => {
  const options = [...document.querySelectorAll('#view-empty [data-act]')];
  const token = window.__FTE_TOKEN__;
  const resources = performance.getEntriesByType('resource');
  return {
    url: location.href,
    emptyVisible: !document.querySelector('#view-empty').hidden,
    options: options.map(button => ({
      action: button.dataset.act,
      visible: button.getClientRects().length > 0,
      disabled: button.disabled
    })),
    layout: getComputedStyle(document.querySelector('.app')).display,
    scriptLoaded: resources.some(r => r.name.endsWith('/app.js')),
    stateRequested: resources.some(r => new URL(r.name).pathname === '/api/state'),
    token
  };
})()`;

function assertUI(state, expectedURL) {
  assert.equal(state.emptyVisible, true, 'The empty view remained hidden');
  assert.equal(state.layout, 'flex', 'The stylesheet did not load');
  assert.equal(state.scriptLoaded, true, 'app.js was not loaded by WebView2');
  assert.equal(state.stateRequested, true, 'app.js did not execute its initial state request');
  assert.ok(typeof state.token === 'string' && state.token.length > 0, 'Missing UI API token');
  assert.deepEqual(state.options.map(option => option.action), ['add-files', 'add-folder']);
  assert.ok(state.options.every(option => option.visible && !option.disabled),
    'Add file/folder options are hidden or disabled');
  if (expectedURL) assert.equal(state.url, expectedURL, 'Recovery changed the UI session');
}

function nativeWindows() {
  return new Set([...log.matchAll(/FTE_TEST_CREATE ([0-9a-f]+)/g)].map(match => match[1]));
}

try {
  const reservation = createServer();
  reservation.listen(0, '127.0.0.1');
  await once(reservation, 'listening');
  const port = reservation.address().port;
  await new Promise((resolve, reject) => reservation.close(error => error ? reject(error) : resolve()));
  const debuggerURL = `http://127.0.0.1:${port}`;

  let main = await readFile(join(root, 'main.go'), 'utf8');
  main = replaceOnce(main, '\t"embed"',
    '\t"embed"\n\t"fmt"\n\t"syscall"\n\t"time"\n\t"github.com/wailsapp/wails/v3/pkg/w32"');
  main = replaceOnce(main, '\t\tLinux: application.LinuxOptions{', `
    Windows: application.WindowsOptions{
      WebviewUserDataPath: ${JSON.stringify(join(temporary, 'webview'))},
      AdditionalBrowserArgs: []string{"--remote-debugging-port=${port}"},
      WndProcInterceptor: func(hwnd uintptr, msg uint32, wParam, lParam uintptr) (uintptr, bool) {
        if msg == 0x0001 { fmt.Fprintf(os.Stderr, "FTE_TEST_CREATE %x\\n", hwnd) }
        return 0, false
      },
    },
\t\tLinux: application.LinuxOptions{`);
  // An independent single-instance identifier prevents interference with an
  // installed app or another copy of this test running on the same desktop.
  main = replaceOnce(main, '"com.filetransfereasy.desktop"',
    JSON.stringify(`com.filetransfereasy.windows-test.${process.pid}.${port}`));
  main = replaceOnce(main, '\tconfigureWindowIcon(window)', `
\tconfigureWindowIcon(window)
  window.OnWindowEvent(events.Windows.WebViewNavigationCompleted, func(*application.WindowEvent) {
    time.AfterFunc(250*time.Millisecond, func() {
      application.InvokeAsync(func() { fteTestWindowIcons(window) })
    })
  })`);
  // Read the actual HWND icon slots and class icon. Compare their rendered
  // pixels to the embedded ICO at the native Windows large/small sizes.
  main += `
func fteTestWindowIcons(window *application.WebviewWindow) {
  hwnd := uintptr(window.NativeWindow())
  large, err := w32.CreateLargeHIconFromImage(icon("icon.ico"))
  if err != nil { fmt.Fprintf(os.Stderr, "FTE_TEST_ICON_ERROR %v\\n", err); return }
  defer w32.DestroyIcon(large)
  small, err := w32.CreateSmallHIconFromImage(icon("icon.ico"))
  if err != nil { fmt.Fprintf(os.Stderr, "FTE_TEST_ICON_ERROR %v\\n", err); return }
  defer w32.DestroyIcon(small)
  classIcon, _, _ := syscall.NewLazyDLL("user32.dll").NewProc("GetClassLongPtrW").Call(hwnd, ^uintptr(13))
  handles := map[string]uintptr{
    "expected-large": large, "expected-small": small,
    "window-large": w32.SendMessage(hwnd, 0x007F, w32.ICON_BIG, 0),
    "window-small": w32.SendMessage(hwnd, 0x007F, w32.ICON_SMALL, 0),
    "class-large": classIcon,
  }
  for name, handle := range handles {
    if handle == 0 { fmt.Fprintf(os.Stderr, "FTE_TEST_ICON_ERROR %s is missing\\n", name); return }
    if err := w32.SaveHIconAsPNG(handle, filepath.Join(${JSON.stringify(temporary)}, name+".png")); err != nil {
      fmt.Fprintf(os.Stderr, "FTE_TEST_ICON_ERROR %s: %v\\n", name, err); return
    }
  }
  fmt.Fprintln(os.Stderr, "FTE_TEST_ICONS_READY")
}
`;

  const serverPath = join(root, 'internal', 'uiserver', 'server.go');
  const server = await readFile(serverPath, 'utf8') + `
func init() {
  _ = mime.AddExtensionType(".js", "text/csv")
  _ = mime.AddExtensionType(".css", "application/octet-stream")
}
`;
  const mainOverlay = join(temporary, 'main.go');
  const serverOverlay = join(temporary, 'server.go');
  const overlayPath = join(temporary, 'overlay.json');
  const executable = join(temporary, 'FileTransferEasy-WindowsTest.exe');
  await writeFile(mainOverlay, main);
  await writeFile(serverOverlay, server);
  await writeFile(overlayPath, JSON.stringify({ Replace: {
    [join(root, 'main.go')]: mainOverlay,
    [serverPath]: serverOverlay,
  } }));
  await mkdir(join(temporary, 'config'));

  console.log('Building isolated Windows test executable...');
  const build = start('go', ['build', '-overlay', overlayPath, '-ldflags', '-H windowsgui', '-o', executable, '.'], {
    env: { ...process.env, CGO_ENABLED: '0' },
  });
  build.stdout.pipe(process.stdout);
  build.stderr.pipe(process.stderr);
  // Compiling Go may take longer with an empty cache; desktop polling below
  // has an 18-second limit for each phase.
  assert.equal(await completed(build, 120_000), 0, 'Go build failed');

  const environment = { ...process.env, APPDATA: join(temporary, 'config') };
  delete environment.FRONTEND_DEVSERVER_URL;
  app = start(executable, [], { env: environment });
  for (const stream of [app.stdout, app.stderr]) {
    stream.on('data', chunk => { log = (log + chunk).slice(-100_000); });
  }

  async function ready(expectedURL) {
    return waitFor('Windows UI readiness', async () => {
      const pages = (await json(`${debuggerURL}/json/list`)).filter(target => target.type === 'page');
      assert.equal(pages.length, 1, 'Expected one WebView2 page');
      const client = await CDP.connect(pages[0].webSocketDebuggerUrl);
      try {
        const state = await client.evaluate(inspectUI);
        assertUI(state, expectedURL);
        const response = await fetch(new URL('/api/state', state.url), {
          headers: { 'X-FTE-Token': state.token },
          signal: AbortSignal.timeout(1500),
        });
        assert.ok(response.ok, `Authenticated state API: HTTP ${response.status}`);
        assert.deepEqual((await response.json()).items, [], 'Unexpected files in the isolated test session');
        return { client, state };
      } catch (error) {
        client.close();
        throw error;
      }
    });
  }

  let page = await ready();
  const sessionURL = page.state.url;
  await waitFor('native tray creation', () => nativeWindows().size >= 3);
  await delay(300);
  // Wails v3.0.0 creates a dispatch window, the main window and one tray
  // window. Calling SystemTray.Run() twice used to create a fourth HWND.
  assert.equal(nativeWindows().size, 3, 'Duplicate native tray/window creation');
  console.log('PASS Windows options, CSS/JS and authenticated API with invalid platform MIME mappings');
  console.log('PASS one native tray (three Wails HWNDs)');

  await waitFor('native taskbar/window icons', () => log.includes('FTE_TEST_ICONS_READY'));
  const largeIcon = await readFile(join(temporary, 'expected-large.png'));
  const smallIcon = await readFile(join(temporary, 'expected-small.png'));
  assert.deepEqual(await readFile(join(temporary, 'window-large.png')), largeIcon,
    'The large taskbar icon differs from the embedded app icon');
  assert.deepEqual(await readFile(join(temporary, 'window-small.png')), smallIcon,
    'The small window/taskbar icon differs from the embedded app icon');
  assert.deepEqual(await readFile(join(temporary, 'class-large.png')), largeIcon,
    'The native window class still has a framework/default icon');
  console.log('PASS native large/small taskbar icons and window class use the app share symbol');

  assert.equal(await page.client.evaluate('document.visibilityState'), 'visible', 'The main window was never shown');
  await page.client.evaluate("document.querySelector('#btn-hide').click(); true");
  await waitFor('Hide button handler', async () =>
    await page.client.evaluate('document.visibilityState') === 'hidden');
  const second = start(executable, [], { env: environment });
  let secondLog = '';
  for (const stream of [second.stdout, second.stderr]) stream.on('data', chunk => { secondLog += chunk; });
  assert.equal(await completed(second, waitMS), 0, 'The second instance did not exit cleanly');
  await waitFor('second-instance window restore', async () =>
    await page.client.evaluate('document.visibilityState') === 'visible');
  assert.ok(!secondLog.includes('FTE_TEST_CREATE'), 'The second instance created a native window');
  assert.equal(nativeWindows().size, 3, 'Reopening created another tray/window');
  page.client.close();
  page = await ready(sessionURL);
  console.log('PASS Hide handler and second-instance restore without duplicate windows');

  // A crashed renderer keeps the native window alive. The library must reload
  // the same session and reattach working controls to the new document.
  const beforeRendererCrash = log.length;
  await page.client.call('Page.crash', {}, 1000).catch(error => {
    assert.match(error.message, /Target crashed|CDP (connection closed|timed out)/);
  });
  await waitFor('native renderer recovery handler', () =>
    /webview2: process failed \(kind=1\); recovery attempt/.test(log.slice(beforeRendererCrash)));
  page.client.close();
  page = await ready(sessionURL);
  console.log('PASS renderer crash recovery restores the same session and options');
  page.client.close();

  const browserBefore = await json(`${debuggerURL}/json/version`);
  const browser = await CDP.connect(browserBefore.webSocketDebuggerUrl);
  await browser.call('Browser.crash', {}, 1000).catch(error => {
    assert.match(error.message, /CDP (connection closed|timed out)/);
  });
  browser.close();
  await waitFor('replacement WebView2 browser', async () => {
    const current = await json(`${debuggerURL}/json/version`);
    return current.webSocketDebuggerUrl !== browserBefore.webSocketDebuggerUrl;
  });
  page = await ready(sessionURL);
  page.client.close();
  assert.equal(nativeWindows().size, 3, 'Crash recovery duplicated a native tray/window');
  console.log('PASS browser crash recovery restores the same session without another tray');
} catch (error) {
  console.error(`FAIL ${error.stack || error}`);
  if (log) console.error(`--- desktop diagnostic log ---\n${log}`);
  process.exitCode = 1;
} finally {
  // Kill only process trees launched by this script, including WebView2
  // children. Never terminate an installed app or a user's browser.
  for (const child of children.toReversed()) {
    if (!child.pid || child.exitCode !== null || child.signalCode !== null) continue;
    const killer = spawn('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], {
      windowsHide: true, stdio: 'ignore',
    });
    await completed(killer, 5000).catch(() => {});
  }
  assert.equal(dirname(resolve(temporary)), resolve(tmpdir()), 'Unsafe temporary cleanup path');
  assert.ok(basename(temporary).startsWith('fte-windows-ui-'), 'Unexpected temporary directory');
  await rm(temporary, { recursive: true, force: true, maxRetries: 20, retryDelay: 200 });
}
