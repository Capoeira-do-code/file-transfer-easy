#!/usr/bin/env node
// Exercise sharing/security/upload flows through two real Windows WebView2 pages.
// Requires Windows, Go from go.mod, WebView2 and Node.js >= 22.
// Run from any directory: node go-app/scripts/test-sharing-features.mjs
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
const temporary = await mkdtemp(join(tmpdir(), 'fte-sharing-features-'));
const children = [];
const waitMS = 20_000;
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

let admin, recipient;
let phase = 'preparing';
const pagePassword = 'page-test-secret';
const itemPassword = 'file-test-secret';
const fixtureText = 'Private browser fixture\n';
const uploadText = 'Browser upload\nUnicode: café\n';

async function evaluate(client, expression) {
  return client.evaluate(`(async () => { ${expression} })()`);
}

async function pageHas(client, expression, label) {
  return waitFor(label, async () => client.evaluate(expression));
}

async function clickText(client, selector, text) {
  await evaluate(client, `
    const button = [...document.querySelectorAll(${JSON.stringify(selector)})]
      .find(button => button.textContent.trim() === ${JSON.stringify(text)});
    if (!button) throw new Error('Missing button: ' + ${JSON.stringify(text)});
    if (button.disabled || !button.getClientRects().length) throw new Error('Unavailable button: ' + button.textContent);
    button.click(); return true;
  `);
}

try {
  const reservation = createServer();
  reservation.listen(0, '127.0.0.1');
  await once(reservation, 'listening');
  const port = reservation.address().port;
  await new Promise((resolve, reject) => reservation.close(error => error ? reject(error) : resolve()));
  const debuggerURL = `http://127.0.0.1:${port}`;
  const received = join(temporary, 'received');
  const folder = join(temporary, 'shared-folder');
  const privateFile = join(temporary, 'private.txt');
  await mkdir(received);
  await mkdir(folder);
  await mkdir(join(temporary, 'config'));
  await writeFile(privateFile, fixtureText);
  await writeFile(join(folder, 'folder-note.txt'), 'Shared folder fixture\n');

  let main = await readFile(join(root, 'main.go'), 'utf8');
  main = replaceOnce(main, '\t"embed"', '\t"embed"\n\t"fmt"\n\t"net"\n\t"net/http"\n\t"time"');
  main = replaceOnce(main, '\t"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/app"',
    '\t"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/app"\n\t"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/publicweb"');
  main = replaceOnce(main, '\t\tLinux: application.LinuxOptions{', `
    Windows: application.WindowsOptions{
      WebviewUserDataPath: ${JSON.stringify(join(temporary, 'webview'))},
      AdditionalBrowserArgs: []string{"--remote-debugging-port=${port}"},
    },
\t\tLinux: application.LinuxOptions{`);
  main = replaceOnce(main, '"com.filetransfereasy.desktop"',
    JSON.stringify(`com.filetransfereasy.features-test.${process.pid}.${port}`));
  main = replaceOnce(main, '\tdefer core.Close()', `
\tdefer core.Close()
  featureMux := http.NewServeMux()
  featureMux.Handle("/s/", publicweb.New(public, core.Store, core.Tracker, "feature-test",
    publicweb.Options{Access: core.Access, OnUpload: core.ReceivePaths}))
  featureMux.HandleFunc("POST /__fixture", func(w http.ResponseWriter, r *http.Request) {
    if _, err := core.Store.AddPaths([]string{${JSON.stringify(privateFile)}, ${JSON.stringify(folder)}}); err != nil {
      http.Error(w, err.Error(), http.StatusInternalServerError); return
    }
    core.MarkDirty()
    w.Header().Set("Content-Type", "application/json")
    fmt.Fprint(w, "{}")
  })
  featureListener, err := net.Listen("tcp", "127.0.0.1:0")
  if err != nil { return err }
  featureServer := &http.Server{Handler:featureMux, ReadHeaderTimeout:10*time.Second}
  defer featureServer.Close()
  go featureServer.Serve(featureListener)
  featureURL := "http://"+featureListener.Addr().String()+"/s/feature-test/"
  fmt.Fprintln(os.Stderr, "FTE_FEATURE_PUBLIC " + featureURL)
`);
  main = replaceOnce(main, '\treturn wails.Run()', `
  wails.Window.NewWithOptions(application.WebviewWindowOptions{
    Name:"recipient-test", Title:"Sharing features recipient", URL:featureURL, Hidden:true,
  })
\treturn wails.Run()`);
  const mainOverlay = join(temporary, 'main.go');
  const overlayPath = join(temporary, 'overlay.json');
  const executable = join(temporary, 'FileTransferEasy-FeaturesTest.exe');
  await writeFile(mainOverlay, main);
  await writeFile(overlayPath, JSON.stringify({ Replace: { [join(root, 'main.go')]: mainOverlay } }));
  console.log('Building isolated sharing features executable...');
  const build = start('go', ['build', '-overlay', overlayPath, '-ldflags', '-H windowsgui', '-o', executable, '.'], {
    env: { ...process.env, CGO_ENABLED: '0' },
  });
  build.stdout.pipe(process.stdout);
  build.stderr.pipe(process.stderr);
  assert.equal(await completed(build, 120_000), 0, 'Go build failed');
  const environment = { ...process.env, APPDATA: join(temporary, 'config') };
  delete environment.FRONTEND_DEVSERVER_URL;
  app = start(executable, [], { env: environment });
  for (const stream of [app.stdout, app.stderr]) {
    stream.on('data', chunk => { log = (log + chunk).slice(-100_000); });
  }
  const publicURL = await waitFor('public loopback server', () => log.match(/FTE_FEATURE_PUBLIC (http:\/\/127\.0\.0\.1:\d+\/s\/feature-test\/)/)?.[1]);
  const targets = await waitFor('two WebView2 pages', async () => {
    const pages = (await json(`${debuggerURL}/json/list`)).filter(target => target.type === 'page');
    const publicPage = pages.find(page => page.url === publicURL);
    const adminPage = pages.find(page => /^http:\/\/127\.0\.0\.1:\d+\/$/.test(page.url));
    return publicPage && adminPage ? { publicPage, adminPage } : null;
  });
  admin = await CDP.connect(targets.adminPage.webSocketDebuggerUrl);
  recipient = await CDP.connect(targets.publicPage.webSocketDebuggerUrl);
  // The recipient window stays hidden, but its real five-second poller must
  // run as it does for a foreground recipient browser. No application source
  // or request handler is mocked here.
  await recipient.evaluate("Object.defineProperty(document, 'visibilityState', {configurable:true,get:()=> 'visible'}); true");
  await pageHas(admin, 'typeof window.__FTE_TOKEN__ === "string" && !!document.querySelector("#btn-settings")', 'admin boot');
  const token = await admin.evaluate('window.__FTE_TOKEN__');
  const adminURL = targets.adminPage.url;
  async function state() {
    const response = await fetch(new URL('/api/state', adminURL), {
      headers: { 'X-FTE-Token': token }, signal: AbortSignal.timeout(3000),
    });
    assert.ok(response.ok, `Admin state HTTP ${response.status}`);
    return response.json();
  }
  async function access() {
    return evaluate(recipient, `return await (await fetch('api/access', {cache:'no-store'})).json();`);
  }
  async function saveSettings() {
    await admin.evaluate("document.querySelector('#settings-form').requestSubmit(); true");
    await pageHas(admin, "!document.querySelector('#settings-dialog').open", 'settings save');
  }
  async function openSettings(tab) {
    await admin.evaluate("document.querySelector('#btn-settings').click(); true");
    await pageHas(admin, "document.querySelector('#settings-dialog').open", 'settings data and dialog readiness');
    if (tab) await admin.evaluate(`document.querySelector(${JSON.stringify('#tab-' + tab)}).click(); true`);
  }
  async function submitPagePassword(password, name = 'Browser visitor') {
    await evaluate(recipient, `
      const form = document.querySelector('.gate form');
      if (!form) throw new Error('Missing access gate form');
      form.querySelector('input[type=password]').value = ${JSON.stringify(password)};
      form.querySelector('input[type=text]').value = ${JSON.stringify(name)};
      form.requestSubmit(); return true;
    `);
  }

  phase = 'default theme and synchronized settings';
  await pageHas(admin, "document.documentElement.dataset.theme === 'light'", 'default desktop light theme');
  await pageHas(recipient, "document.documentElement.dataset.theme === 'light'", 'default public light theme');
  await openSettings('general');
  await admin.evaluate("document.querySelector('#setting-theme').value='dark'; document.querySelector('#setting-theme').dispatchEvent(new Event('change',{bubbles:true})); true");
  await saveSettings();
  await pageHas(admin, "document.documentElement.dataset.theme === 'dark'", 'desktop dark theme');
  await pageHas(recipient, "document.documentElement.dataset.theme === 'dark'", 'public theme synchronization');
  assert.equal((await state()).settings.theme, 'dark');
  console.log('PASS light defaults and settings theme synchronize to the real recipient page');

  phase = 'fixtures and per-file protection';
  const fixtureResponse = await fetch(new URL('/__fixture', publicURL), { method: 'POST' });
  assert.ok(fixtureResponse.ok, 'Failed to add isolated fixtures');
  await waitFor('two shared fixture items', async () => (await state()).items.length === 2);
  await pageHas(admin, "document.querySelectorAll('#items-list .item').length === 2", 'desktop fixture rows');
  await pageHas(recipient, "document.querySelectorAll('#stage .row').length === 2", 'public fixture rows');
  await evaluate(admin, `
    const row = [...document.querySelectorAll('#items-list .item')].find(row=>row.textContent.includes('private.txt'));
    if (!row) throw new Error('Missing private file row');
    row.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true,clientX:120,clientY:160}));
    const button = [...document.querySelectorAll('#item-menu button')].find(button=>button.textContent.startsWith('Proteger'));
    if (!button) throw new Error('Missing protect action'); button.click();
    document.querySelector('#edit-input').value=${JSON.stringify(itemPassword)};
    document.querySelector('#edit-form').requestSubmit(); return true;
  `);
  await waitFor('protected file state', async () => (await state()).items.find(item => item.name === 'private.txt')?.protected);
  await pageHas(admin, "!document.querySelector('#edit-dialog').open", 'item password saved');
  console.log('PASS real context menu protects an individual file');

  phase = 'folder password context menu and inherited protection';
  const folderItem = (await state()).items.find(item => item.kind === 'folder' && item.name === 'shared-folder');
  assert.ok(folderItem, 'Fixture did not create a folder item');
  await evaluate(admin, `
    const row=[...document.querySelectorAll('#items-list .item')].find(row=>row.textContent.includes('shared-folder'));
    if (!row) throw new Error('Missing shared-folder row');
    row.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true,clientX:120,clientY:220}));
    const button=[...document.querySelectorAll('#item-menu button')].find(button=>button.textContent.startsWith('Proteger'));
    if (!button) throw new Error('Missing folder protect action'); button.click();
    document.querySelector('#edit-input').value='folder-test-secret';
    document.querySelector('#edit-form').requestSubmit(); return true;
  `);
  await waitFor('folder marked protected in host state', async () => (await state()).items.find(item => item.id === folderItem.id)?.protected);
  await pageHas(admin, "!document.querySelector('#edit-dialog').open", 'folder password saved');
  const protectedFolderManifest = await evaluate(recipient, "return await (await fetch('api/manifest')).json();");
  const protectedFolder = protectedFolderManifest.folders.find(folder => folder.id === folderItem.id);
  const folderFile = protectedFolderManifest.files.find(file => file.name === 'folder-note.txt');
  assert.ok(protectedFolder?.protected && protectedFolder.locked, 'Public folder does not require its password');
  assert.equal(folderFile.ownerId, folderItem.id, 'Folder child is owned by an unrelated file/alias');
  assert.ok(folderFile.protected && folderFile.locked, 'Folder child did not inherit folder protection');
  assert.equal(folderFile.protectionKind, 'folder');
  assert.equal(folderFile.protectionName, 'shared-folder');
  await pageHas(recipient, "!!document.querySelector('button[aria-label=\"Desbloquear folder-note.txt\"]')", 'protected folder child in recipient DOM');
  await recipient.evaluate("document.querySelector('button[aria-label=\"Desbloquear folder-note.txt\"]').click(); true");
  await pageHas(recipient, "document.querySelector('#unlock-dialog').open && document.querySelector('#unlock-title').textContent === 'Desbloquear carpeta' && document.querySelector('#unlock-name').textContent === 'shared-folder'", 'effective folder password dialog labels');
  await recipient.evaluate("document.querySelector('#unlock-cancel').click(); true");
  await evaluate(admin, `
    const row=[...document.querySelectorAll('#items-list .item')].find(row=>row.textContent.includes('shared-folder'));
    row.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true,clientX:120,clientY:220}));
    const button=[...document.querySelectorAll('#item-menu button')].find(button=>button.textContent.startsWith('Quitar contraseña'));
    if (!button) throw new Error('Missing remove folder password action'); button.click();
    if (!document.querySelector('#edit-dialog').open) throw new Error('Missing folder password removal confirmation');
    document.querySelector('#edit-form').requestSubmit(); return true;
  `);
  await waitFor('folder password removed in host state', async () => (await state()).items.find(item => item.id === folderItem.id)?.protected === false);
  await pageHas(admin, "!document.querySelector('#edit-dialog').open", 'folder password removal confirmed');
  await pageHas(recipient, "!!document.querySelector('a[aria-label=\"Descargar folder-note.txt\"]')", 'folder download restored after password removal');
  assert.equal((await state()).items.find(item => item.name === 'private.txt').protected, true,
    'Removing the folder password also removed an unrelated file password');
  console.log('PASS folder context menu protection, inherited child owner/lock, and confirmed password removal');

  phase = 'page password, approvals and receiving settings';
  await openSettings('security');
  await evaluate(admin, `
    const password=document.querySelector('#setting-password'); password.value=${JSON.stringify(pagePassword)};
    password.dispatchEvent(new Event('input',{bubbles:true}));
    document.querySelector('#setting-approval').checked=true;
    document.querySelector('#tab-receiving').click();
    document.querySelector('#setting-uploads').checked=true;
    document.querySelector('#setting-upload-dir').value=${JSON.stringify(received)};
    document.querySelector('#setting-max-upload').value='16'; return true;
  `);
  await saveSettings();
  const configured = (await state()).settings;
  assert.equal(configured.pagePasswordSet, true);
  assert.equal(configured.requireApproval, true);
  assert.equal(configured.uploadsEnabled, true);
  assert.equal(configured.maxUploadMB, 16);
  await pageHas(recipient, "!!document.querySelector('.gate input[type=password]')", 'page password gate');
  await submitPagePassword('wrong-password');
  const pageError = await waitFor('specific incorrect page password error', async () => {
    const message = await recipient.evaluate("document.querySelector('.gate [role=alert]')?.hidden === false ? document.querySelector('.gate [role=alert]').textContent : ''");
    return /contrase.*correct/i.test(message) ? message : null;
  });
  await submitPagePassword(pagePassword);
  await pageHas(recipient, "document.querySelector('.gate h2')?.textContent === 'Esperando autorización'", 'pending approval gate');
  await pageHas(admin, "[...document.querySelectorAll('#request-list button')].some(button=>button.textContent==='Aceptar')", 'desktop approval request');
  await clickText(admin, '#request-list button', 'Aceptar');
  await pageHas(recipient, "!document.querySelector('.gate') && !!document.querySelector('.unlock-button')", 'approved protected file list');
  assert.equal((await access()).status, 'allowed');
  console.log(`PASS incorrect page password: ${pageError}; real recipient approval opens the page`);

  phase = 'individual file unlock and download';
  const protectedManifest = await evaluate(recipient, "return await (await fetch('api/manifest')).json();");
  const protectedFile = protectedManifest.files.find(file => file.name === 'private.txt');
  assert.ok(protectedFile?.locked && protectedFile.protected, 'Public manifest did not protect private.txt');
  assert.equal(protectedFile.protectionKind, 'file');
  assert.equal(protectedFile.protectionName, 'private.txt');
  const deniedDownload = await evaluate(recipient, `
    const response=await fetch('api/download/'+${JSON.stringify(protectedFile.id)});
    return {status:response.status,body:await response.text()};
  `);
  assert.equal(deniedDownload.status, 403, deniedDownload.body);
  assert.match(deniedDownload.body, /contraseña.*archivo|archivo.*contraseña/i);
  await evaluate(recipient, `
    document.querySelector('.unlock-button').click();
    document.querySelector('#unlock-password').value='wrong-password';
    document.querySelector('#unlock-form').requestSubmit(); return true;
  `);
  const itemError = await waitFor('specific incorrect file password error', async () => {
    const message = await recipient.evaluate("!document.querySelector('#unlock-error').hidden ? document.querySelector('#unlock-error').textContent : ''");
    return /contrase.*correct/i.test(message) ? message : null;
  });
  await recipient.evaluate(`document.querySelector('#unlock-password').value=${JSON.stringify(itemPassword)}; document.querySelector('#unlock-form').requestSubmit(); true`);
  await pageHas(recipient, "!document.querySelector('#unlock-dialog').open && !!document.querySelector('a[aria-label=\"Descargar private.txt\"]')", 'file unlocked');
  const downloaded = await evaluate(recipient, `
    const response=await fetch(document.querySelector('a[aria-label="Descargar private.txt"]').href);
    return {status:response.status,body:await response.text()};
  `);
  assert.equal(downloaded.status, 200);
  assert.equal(downloaded.body, fixtureText);
  console.log(`PASS locked download rejected, incorrect file password: ${itemError}, correct password restores exact file bytes`);

  phase = 'browser upload and host receipt';
  await pageHas(recipient, "!document.querySelector('#upload-section').hidden", 'recipient upload controls');
  await evaluate(recipient, `
    const selection=new DataTransfer(); selection.items.add(new File([${JSON.stringify(uploadText)}],'browser.txt',{type:'text/plain'}));
    const input=document.querySelector('#upload-files'); input.files=selection.files;
    input.dispatchEvent(new Event('change',{bubbles:true}));
    document.querySelector('#upload-start').click(); return true;
  `);
  await pageHas(recipient, "document.querySelector('#upload-status').textContent === 'Envío completado'", 'successful browser upload');
  await waitFor('received file on disk', async () => (await readFile(join(received, 'browser.txt'), 'utf8')) === uploadText);
  const uploaded = await waitFor('received file and upload statistics in state', async () => {
    const snapshot = await state();
    return snapshot.stats.uploads === 1 && snapshot.items.some(item => item.name === 'browser.txt') ? snapshot : null;
  });
  assert.equal(uploaded.stats.receivedBytes, Buffer.byteLength(uploadText));
  await pageHas(admin, "[...document.querySelectorAll('#items-list .item')].some(row=>row.textContent.includes('browser.txt'))", 'received item in desktop list');
  console.log('PASS browser File/DataTransfer/XHR upload saves exact bytes and appears in host state/UI/statistics');

  phase = 'history naming and IP blocking';
  await openSettings('history');
  await pageHas(admin, "[...document.querySelectorAll('#history-list .history-row')].some(row=>row.textContent.includes('127.0.0.1'))", 'persistent visitor history row');
  await clickText(admin, '#history-list .history-row button', 'Nombre');
  await admin.evaluate("document.querySelector('#edit-input').value='Recipient test name'; document.querySelector('#edit-form').requestSubmit(); true");
  await pageHas(admin, "!document.querySelector('#edit-dialog').open && document.querySelector('#history-list').textContent.includes('Recipient test name')", 'renamed visitor in history UI');
  await waitFor('renamed visitor saved', async () => (await state()).history.some(visitor => visitor.ip === '127.0.0.1' && visitor.name === 'Recipient test name'));
  await clickText(admin, '#history-list .history-row button', 'Bloquear');
  await pageHas(recipient, "document.querySelector('.gate h2')?.textContent === 'Acceso bloqueado'", 'recipient block feedback');
  assert.equal((await access()).status, 'blocked');
  await clickText(admin, '#history-list .history-row button', 'Desbloquear');
  await pageHas(recipient, "!!document.querySelector('.gate input[type=password]')", 'unblocked recipient must authenticate again');
  await admin.evaluate("document.querySelector('#settings-close').click(); true");
  await submitPagePassword(pagePassword, 'Denied visitor');
  await pageHas(recipient, "document.querySelector('.gate h2')?.textContent === 'Esperando autorización'", 'second pending approval');
  await pageHas(admin, "[...document.querySelectorAll('#request-list button')].some(button=>button.textContent==='Rechazar')", 'second desktop approval request');
  await clickText(admin, '#request-list button', 'Rechazar');
  await pageHas(recipient, "document.querySelector('.gate h2')?.textContent === 'Acceso rechazado'", 'rejected visitor feedback');
  assert.equal((await access()).status, 'denied');
  console.log('PASS history rename, immediate IP block, unblock revokes old grants, and second approval rejection');
  assert.equal((await state()).share.status, 'idle', 'Test unexpectedly started a tunnel');
  console.log('PASS all sharing feature flows use loopback only; no cloudflared/tunnel starts');
} catch (error) {
  console.error(`FAIL during ${phase}: ${error.stack || error}`);
  for (const [name, client] of [['desktop', admin], ['recipient', recipient]]) {
    if (client) {
      try { console.error(`${name} DOM: ${await client.evaluate('document.body.innerText')}`); } catch {}
    }
  }
  if (log) console.error(`Desktop diagnostic log:\n${log}`);
  process.exitCode = 1;
} finally {
  admin?.close(); recipient?.close();
  for (const child of children.toReversed()) {
    if (!child.pid || child.exitCode !== null || child.signalCode !== null) continue;
    const killer = spawn('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], {
      windowsHide: true, stdio: 'ignore',
    });
    await completed(killer, 5000).catch(() => {});
  }
  assert.equal(dirname(resolve(temporary)), resolve(tmpdir()), 'Unsafe temporary cleanup path');
  assert.ok(basename(temporary).startsWith('fte-sharing-features-'), 'Unexpected temporary directory');
  await rm(temporary, { recursive: true, force: true, maxRetries: 20, retryDelay: 200 });
}

