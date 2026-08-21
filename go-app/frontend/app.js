/* ============================================================================
 *  File Transfer Easy — desktop window
 *  Plain JS. No framework, no build step, no Wails runtime.
 *  State arrives over SSE; every mutation is a POST. Rendering diffs by id and
 *  reuses DOM nodes so progress bars keep animating and hover state survives.
 * ========================================================================== */
(function () {
  'use strict';

  var TOKEN = String(window.__FTE_TOKEN__ || '');
  var SVGNS = 'http://www.w3.org/2000/svg';

  /* ------------------------------------------------------------------ *
   *  helpers
   * ------------------------------------------------------------------ */

  function $(sel, root) { return (root || document).querySelector(sel); }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function icon(name, cls) {
    var s = document.createElementNS(SVGNS, 'svg');
    s.setAttribute('viewBox', '0 0 24 24');
    s.setAttribute('aria-hidden', 'true');
    s.setAttribute('class', 'ico' + (cls ? ' ' + cls : ''));
    var u = document.createElementNS(SVGNS, 'use');
    u.setAttribute('href', '#i-' + name);
    s.appendChild(u);
    return s;
  }

  /* write-only-if-changed: keeps the DOM (and its animations) untouched */
  function txt(node, value) {
    var v = value == null ? '' : String(value);
    if (node && node.textContent !== v) node.textContent = v;
  }
  function show(node, on) {
    if (node && node.hidden === !!on) node.hidden = !on;
  }
  function cls(node, name, on) {
    if (node) node.classList.toggle(name, !!on);
  }
  function attr(node, name, value) {
    if (!node) return;
    if (value == null) { if (node.hasAttribute(name)) node.removeAttribute(name); }
    else if (node.getAttribute(name) !== value) node.setAttribute(name, value);
  }

  function nfmt(n) {
    n = Number(n) || 0;
    try { return n.toLocaleString('es-ES'); } catch (e) { return String(n); }
  }
  function plural(n, one, many) { return Number(n) === 1 ? one : many; }

  var UNITS = ['B', 'KB', 'MB', 'GB', 'TB'];
  function fmtBytes(bytes) {
    var b = Number(bytes) || 0, i = 0;
    while (b >= 1024 && i < UNITS.length - 1) { b /= 1024; i += 1; }
    var dec = i === 0 ? 0 : (b < 10 ? 1 : 0);
    var s;
    try { s = b.toLocaleString('es-ES', { minimumFractionDigits: dec, maximumFractionDigits: dec }); }
    catch (e) { s = b.toFixed(dec); }
    return s + ' ' + UNITS[i];
  }

  function hhmm(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    try { return d.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' }); }
    catch (e) { return ''; }
  }

  function join(parts) {
    var out = [];
    for (var i = 0; i < parts.length; i++) {
      var p = parts[i];
      if (p != null && String(p).trim() !== '') out.push(String(p).trim());
    }
    return out.join(' · ');
  }

  /* deterministic avatar hue from the visitor id */
  function hueOf(id) {
    var s = String(id || ''), h = 0;
    for (var i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
    return (h % 6) + 1;
  }

  function initialsOf(v) {
    var parts = String(v.label || '').split(/[^0-9A-Za-zÀ-ÿ]+/).filter(Boolean);
    if (parts.length >= 2) return (parts[0].charAt(0) + parts[1].charAt(0)).toUpperCase();
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    var ip = String(v.ip || '').replace(/[^0-9A-Za-z]/g, '');
    return (ip.slice(0, 2) || '··').toUpperCase();
  }

  /* ------------------------------------------------------------------ *
   *  list diffing — reuse nodes keyed by id
   * ------------------------------------------------------------------ */

  function syncList(host, data, create, update) {
    var map = host.__nodes || (host.__nodes = Object.create(null));
    var keep = Object.create(null);

    for (var i = 0; i < data.length; i++) {
      var d = data[i];
      var id = String(d.id != null ? d.id : i);
      keep[id] = true;
      var node = map[id];
      if (!node) {
        node = create(d);
        node.dataset.id = id;
        map[id] = node;
      }
      update(node, d);
      var at = host.children[i];
      if (at !== node) host.insertBefore(node, at || null);
    }

    for (var key in map) {
      if (!keep[key]) {
        if (map[key].parentNode) map[key].parentNode.removeChild(map[key]);
        delete map[key];
      }
    }
  }

  /* ------------------------------------------------------------------ *
   *  api
   * ------------------------------------------------------------------ */

  function post(path, body) {
    return fetch(path, {
      method: 'POST',
      headers: { 'X-FTE-Token': TOKEN, 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    }).then(function (res) {
      return res.json().catch(function () { return null; }).then(function (data) {
        if (!res.ok) return { ok: false, error: (data && data.error) || ('HTTP ' + res.status) };
        if (data && data.ok === false) return { ok: false, error: data.error || 'La acción no se pudo completar' };
        return { ok: true, data: data };
      });
    }).catch(function () {
      return { ok: false, error: 'Sin conexión con la aplicación' };
    });
  }

  /* fire an action and surface the failure as a toast */
  function act(path, body, okMessage) {
    return post(path, body).then(function (r) {
      if (!r.ok) toast(r.error, 'error');
      else if (okMessage) toast(okMessage, 'ok');
      return r;
    });
  }

  /* ------------------------------------------------------------------ *
   *  toasts
   * ------------------------------------------------------------------ */

  var toastHost;

  function toast(message, kind) {
    if (!toastHost) toastHost = $('#toasts');
    if (!toastHost || !message) return;

    while (toastHost.children.length >= 4) dismiss(toastHost.firstElementChild, true);

    var t = el('div', 'toast' + (kind ? ' is-' + kind : ''));
    t.appendChild(el('span', 'toast-dot'));
    t.appendChild(el('span', 'toast-msg', message));

    var x = el('button', 'iconbtn');
    x.type = 'button';
    x.setAttribute('aria-label', 'Cerrar aviso');
    x.appendChild(icon('x'));
    x.addEventListener('click', function () { dismiss(t); });
    t.appendChild(x);

    toastHost.appendChild(t);
    var timer = setTimeout(function () { dismiss(t); }, 3000);
    t.__timer = timer;
  }

  function dismiss(t, immediate) {
    if (!t || t.__gone) return;
    t.__gone = true;
    clearTimeout(t.__timer);
    if (immediate) { if (t.parentNode) t.parentNode.removeChild(t); return; }
    t.classList.add('is-out');
    setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 200);
  }

  /* ------------------------------------------------------------------ *
   *  element cache
   * ------------------------------------------------------------------ */

  var E = {};
  function cache() {
    E.topbar = $('#topbar');
    E.stage = $('#stage');
    E.viewEmpty = $('#view-empty');
    E.viewActive = $('#view-active');
    E.reconnect = $('#reconnect');

    E.linkcard = $('#linkcard');
    E.statusPill = $('#status-pill');
    E.statusText = $('#status-text');
    E.since = $('#share-since');
    E.urlText = $('#url-text');
    E.urlSkeleton = $('#url-skeleton');
    E.btnCopy = $('#btn-copy');
    E.copyLabel = $('#copy-label');
    E.lanLine = $('#lan-line');
    E.lanUrl = $('#lan-url');
    E.btnToggle = $('#btn-share-toggle');
    E.shareError = $('#share-error');
    E.shareErrorText = $('#share-error-text');
    E.qrWrap = $('#qr-wrap');
    E.qrImg = $('#qr-img');

    E.stDownloads = $('#st-downloads');
    E.stBytes = $('#st-bytes');
    E.stVisitors = $('#st-visitors');
    E.stActive = $('#st-active');

    E.itemsTotals = $('#items-totals');
    E.itemsList = $('#items-list');
    E.btnClear = $('#btn-clear');

    E.transfersList = $('#transfers-list');
    E.transfersEmpty = $('#transfers-empty');
    E.trCount = $('#tr-count');
    E.visitorsList = $('#visitors-list');
    E.visitorsEmpty = $('#visitors-empty');
    E.viCount = $('#vi-count');

    E.logbox = $('#logbox');
    E.logLines = $('#log-lines');
    E.logCount = $('#log-count');

    E.veil = $('#veil');
    toastHost = $('#toasts');
  }

  /* ------------------------------------------------------------------ *
   *  share / link card
   * ------------------------------------------------------------------ */

  var TONE = {
    idle: 'neutral', stopped: 'neutral',
    preparing: 'warn', installing: 'warn', starting: 'warn', stopping: 'warn',
    live: 'ok', error: 'danger'
  };
  var FALLBACK_STATUS = {
    idle: 'Listo', preparing: 'Preparando…', installing: 'Instalando cloudflared…',
    starting: 'Iniciando túnel…', live: 'Compartiendo', stopping: 'Deteniendo…',
    stopped: 'Detenido', error: 'Error'
  };
  var BUSY_SHARE = { preparing: 1, installing: 1, starting: 1, live: 1, stopping: 1 };

  var copyTimer = null, copiedUntil = 0;

  function renderShare(share) {
    var status = String(share.status || 'idle');
    var tone = TONE[status] || 'neutral';
    var live = status === 'live' && !!share.url;

    if (E.statusPill.className !== 'statuspill is-' + tone) {
      E.statusPill.className = 'statuspill is-' + tone;
    }
    txt(E.statusText, share.statusText || FALLBACK_STATUS[status] || status);
    cls(E.linkcard, 'is-live', live);

    /* url or skeleton */
    show(E.urlText, live);
    show(E.urlSkeleton, !live);
    txt(E.urlText, live ? share.url : '');
    attr(E.urlText, 'title', live ? share.url : null);

    /* copy button */
    E.btnCopy.disabled = !live;
    paintCopy();

    /* since */
    var sinceText = live && share.since ? 'activo desde ' + hhmm(share.since) : '';
    show(E.since, !!sinceText);
    txt(E.since, sinceText);

    /* lan url */
    var lan = share.lanUrl || '';
    show(E.lanLine, !!lan);
    txt(E.lanUrl, lan);
    attr(E.lanLine, 'title', lan || null);

    /* error */
    var err = status === 'error' ? (share.error || 'No se pudo iniciar el túnel') : '';
    show(E.shareError, !!err);
    txt(E.shareErrorText, err);

    /* toggle */
    var sharing = !!BUSY_SHARE[status];
    txt($('.btn-label', E.btnToggle), sharing ? 'Dejar de compartir' : 'Compartir');
    E.btnToggle.dataset.mode = sharing ? 'stop' : 'start';
    attr(E.btnToggle, 'aria-label', sharing ? 'Dejar de compartir' : 'Empezar a compartir');

    updateQR(live ? share.url : '');
  }

  function paintCopy() {
    var copied = Date.now() < copiedUntil;
    cls(E.btnCopy, 'is-copied', copied);
    txt(E.copyLabel, copied ? '¡Copiado!' : 'Copiar');
    attr(E.btnCopy, 'aria-label', copied ? 'Enlace copiado' : 'Copiar el enlace público');
  }

  function flashCopied() {
    copiedUntil = Date.now() + 1600;
    paintCopy();
    clearTimeout(copyTimer);
    copyTimer = setTimeout(function () { copiedUntil = 0; paintCopy(); }, 1650);
  }

  /* QR: <img> cannot send the token header, so fetch it and swap in a blob URL.
     Falls back to a direct src (token as query param) if that ever fails. */
  var qrFor = null, qrObjectUrl = null;

  function updateQR(url) {
    if (url === qrFor) return;
    qrFor = url;

    if (qrObjectUrl) { URL.revokeObjectURL(qrObjectUrl); qrObjectUrl = null; }

    if (!url) {
      show(E.qrWrap, false);
      E.qrImg.removeAttribute('src');
      return;
    }

    var src = '/api/qr.png?v=' + encodeURIComponent(url) +
              (TOKEN ? '&t=' + encodeURIComponent(TOKEN) : '');

    fetch(src, { headers: { 'X-FTE-Token': TOKEN } })
      .then(function (res) { return res.ok ? res.blob() : Promise.reject(res.status); })
      .then(function (blob) {
        if (qrFor !== url) return;
        qrObjectUrl = URL.createObjectURL(blob);
        E.qrImg.src = qrObjectUrl;
        show(E.qrWrap, true);
      })
      .catch(function () {
        if (qrFor !== url) return;
        E.qrImg.src = src;              /* last resort: let the <img> try itself */
        show(E.qrWrap, true);
      });
  }

  /* ------------------------------------------------------------------ *
   *  items
   * ------------------------------------------------------------------ */

  function createItem(d) {
    var li = el('li', 'item');

    var tile = el('span', 'tile');
    if (d.kind === 'folder') {
      tile.classList.add('is-folder');
      tile.appendChild(icon('folder'));
    } else {
      var ext = String(d.ext || '').toUpperCase().slice(0, 4);
      if (ext) {
        tile.classList.add('is-ext');
        if (ext.length > 3) tile.classList.add('is-long');
        tile.textContent = ext;
      } else {
        tile.appendChild(icon('file'));
      }
    }
    li.appendChild(tile);

    var body = el('div', 'item-body');
    var name = el('div', 'item-name');
    var meta = el('div', 'item-meta');
    var metaText = el('span', 'meta-text');
    var tag = el('span', 'tag', 'no encontrado');
    tag.hidden = true;
    meta.appendChild(metaText);
    meta.appendChild(tag);
    body.appendChild(name);
    body.appendChild(meta);
    li.appendChild(body);

    var actions = el('div', 'row-actions');

    var reveal = el('button', 'iconbtn iconbtn-sm');
    reveal.type = 'button';
    reveal.setAttribute('aria-label', 'Mostrar en el explorador de archivos');
    reveal.title = 'Mostrar en el explorador de archivos';
    reveal.appendChild(icon('reveal'));
    reveal.addEventListener('click', function () {
      act('/api/items/reveal', { id: li.dataset.id });
    });

    var remove = el('button', 'iconbtn iconbtn-sm is-danger');
    remove.type = 'button';
    remove.setAttribute('aria-label', 'Quitar de la lista');
    remove.title = 'Quitar de la lista';
    remove.appendChild(icon('x'));
    remove.addEventListener('click', function () {
      act('/api/items/remove', { ids: [li.dataset.id] });
    });

    actions.appendChild(reveal);
    actions.appendChild(remove);
    li.appendChild(actions);

    li.__refs = { name: name, metaText: metaText, tag: tag, tile: tile };
    return li;
  }

  function updateItem(li, d) {
    var r = li.__refs;
    txt(r.name, d.name || '');
    attr(li, 'title', d.path || d.name || null);

    var bits = [d.sizeText || fmtBytes(d.size)];
    if (d.kind === 'folder') {
      bits.push(nfmt(d.fileCount) + ' ' + plural(d.fileCount, 'archivo', 'archivos'));
    }
    txt(r.metaText, join(bits));

    cls(li, 'is-missing', !!d.missing);
    show(r.tag, !!d.missing);
  }

  function renderItems(items, totals) {
    syncList(E.itemsList, items, createItem, updateItem);
    txt(E.itemsTotals, join([
      nfmt(totals.items) + ' ' + plural(totals.items, 'elemento', 'elementos'),
      nfmt(totals.files) + ' ' + plural(totals.files, 'archivo', 'archivos'),
      totals.bytesText || fmtBytes(totals.bytes)
    ]));
  }

  /* ------------------------------------------------------------------ *
   *  transfers
   * ------------------------------------------------------------------ */

  var TR_STATE = { done: 'Completada', cancelled: 'Cancelada', error: 'Error' };

  function createTransfer(d) {
    var li = el('li', 'tr');

    var top = el('div', 'tr-top');
    var kind = el('span', 'tr-kind');
    kind.appendChild(icon(d.kind === 'zip' ? 'archive' : 'file'));
    var name = el('span', 'tr-name');
    var ip = el('span', 'tr-ip mono');
    var pct = el('span', 'tr-pct');

    var cancel = el('button', 'iconbtn iconbtn-sm is-danger tr-cancel');
    cancel.type = 'button';
    cancel.setAttribute('aria-label', 'Cancelar esta descarga');
    cancel.title = 'Cancelar';
    cancel.appendChild(icon('x'));
    cancel.addEventListener('click', function () {
      act('/api/transfers/cancel', { id: li.dataset.id });
    });

    top.appendChild(kind);
    top.appendChild(name);
    top.appendChild(ip);
    top.appendChild(pct);
    top.appendChild(cancel);

    var bar = el('div', 'bar');
    var fill = el('div', 'bar-fill');
    bar.appendChild(fill);

    var meta = el('div', 'tr-meta');
    var state = el('span', 'tr-state');
    var rest = el('span', 'tr-rest');
    meta.appendChild(state);
    meta.appendChild(rest);

    li.appendChild(top);
    li.appendChild(bar);
    li.appendChild(meta);

    li.__refs = { name: name, ip: ip, pct: pct, fill: fill, state: state, rest: rest, cancel: cancel };
    return li;
  }

  function updateTransfer(li, d) {
    var r = li.__refs;
    var status = String(d.status || 'active');
    var active = status === 'active';

    txt(r.name, d.name || '');
    attr(li, 'title', d.name || null);
    txt(r.ip, d.ip || '');

    var p = Math.max(0, Math.min(100, Number(d.percent) || 0));
    txt(r.pct, Math.round(p) + '%');

    var w = (status === 'done' ? 100 : p).toFixed(1) + '%';
    if (r.fill.style.width !== w) r.fill.style.width = w;

    cls(li, 'is-active', active);
    cls(li, 'is-done', status === 'done');
    cls(li, 'is-cancelled', status === 'cancelled');
    cls(li, 'is-error', status === 'error');

    show(r.cancel, active);

    if (active) {
      txt(r.state, '');
      txt(r.rest, join([
        d.total ? fmtBytes(d.bytes) + ' de ' + fmtBytes(d.total) : fmtBytes(d.bytes),
        d.speedText,
        d.etaText
      ]));
    } else {
      txt(r.state, TR_STATE[status] || status);
      txt(r.rest, ' · ' + fmtBytes(d.bytes));
    }
    attr(r.state, 'hidden', active ? '' : null);
  }

  function renderTransfers(transfers) {
    syncList(E.transfersList, transfers, createTransfer, updateTransfer);
    show(E.transfersEmpty, transfers.length === 0);
    var activeCount = 0;
    for (var i = 0; i < transfers.length; i++) if (transfers[i].status === 'active') activeCount++;
    txt(E.trCount, String(activeCount || transfers.length));
    return activeCount;
  }

  /* ------------------------------------------------------------------ *
   *  visitors
   * ------------------------------------------------------------------ */

  function createVisitor(d) {
    var li = el('li', 'vis');

    var avatar = el('span', 'avatar av-' + hueOf(d.id));

    var body = el('div', 'vis-body');
    var top = el('div', 'vis-top');
    var ip = el('span', 'vis-ip mono');
    var dot = el('span', 'onlinedot');
    top.appendChild(ip);
    top.appendChild(dot);
    var label = el('div', 'vis-label');
    body.appendChild(top);
    body.appendChild(label);

    var stats = el('span', 'vis-stats');

    var actions = el('div', 'row-actions');
    var forget = el('button', 'iconbtn iconbtn-sm is-danger');
    forget.type = 'button';
    forget.setAttribute('aria-label', 'Olvidar este visitante');
    forget.title = 'Olvidar visitante';
    forget.appendChild(icon('user-minus'));
    forget.addEventListener('click', function () {
      act('/api/visitors/forget', { id: li.dataset.id });
    });
    actions.appendChild(forget);

    li.appendChild(avatar);
    li.appendChild(body);
    li.appendChild(stats);
    li.appendChild(actions);

    li.__refs = { avatar: avatar, ip: ip, dot: dot, label: label, stats: stats };
    return li;
  }

  function updateVisitor(li, d) {
    var r = li.__refs;
    txt(r.avatar, initialsOf(d));
    txt(r.ip, d.ip || '—');
    txt(r.label, d.label || 'Visitante');
    attr(li, 'title', join([d.label, d.ip, d.lastSeen ? 'visto a las ' + hhmm(d.lastSeen) : '']) || null);
    cls(r.dot, 'is-online', !!d.online);
    attr(r.dot, 'title', d.online ? 'En línea' : 'Desconectado');
    txt(r.stats, join([
      nfmt(d.downloads) + ' ' + plural(d.downloads, 'descarga', 'descargas'),
      d.bytesText || fmtBytes(d.bytes)
    ]));
  }

  function renderVisitors(visitors) {
    syncList(E.visitorsList, visitors, createVisitor, updateVisitor);
    show(E.visitorsEmpty, visitors.length === 0);
    var online = 0;
    for (var i = 0; i < visitors.length; i++) if (visitors[i].online) online++;
    txt(E.viCount, String(visitors.length));
    return online;
  }

  /* ------------------------------------------------------------------ *
   *  log
   * ------------------------------------------------------------------ */

  var logSig = null;

  function renderLog(log) {
    txt(E.logCount, String(log.length));
    var last = log[log.length - 1];
    var sig = log.length + '|' + (last ? last.time + '|' + last.text : '');
    if (sig === logSig) return;
    logSig = sig;

    var box = E.logLines;
    var stuck = !E.logbox.open ||
      (box.scrollHeight - box.scrollTop - box.clientHeight) < 28;

    var frag = document.createDocumentFragment();
    for (var i = 0; i < log.length; i++) {
      var entry = log[i] || {};
      var line = el('div', 'logline lv-' + (entry.level || 'info'));
      line.appendChild(el('span', 'logline-time', entry.time || ''));
      line.appendChild(el('span', 'logline-text', entry.text || ''));
      frag.appendChild(line);
    }
    box.replaceChildren(frag);
    if (stuck) box.scrollTop = box.scrollHeight;
  }

  /* ------------------------------------------------------------------ *
   *  master render
   * ------------------------------------------------------------------ */

  var state = null, gotState = false;

  function apply(next) {
    if (!next || typeof next !== 'object') return;
    gotState = true;
    state = next;
    render();
  }

  function render() {
    var s = state || {};
    var items = Array.isArray(s.items) ? s.items : [];
    var totals = s.totals || { items: items.length, files: 0, bytes: 0, bytesText: '' };
    var share = s.share || {};
    var visitors = Array.isArray(s.visitors) ? s.visitors : [];
    var transfers = Array.isArray(s.transfers) ? s.transfers : [];
    var stats = s.stats || {};
    var log = Array.isArray(s.log) ? s.log : [];

    var empty = items.length === 0;
    show(E.viewEmpty, empty);
    show(E.viewActive, !empty);
    if (empty) {
      updateQR('');
      return;
    }

    renderShare(share);
    renderItems(items, totals);
    var activeCount = renderTransfers(transfers);
    renderVisitors(visitors);
    renderLog(log);

    txt(E.stDownloads, nfmt(stats.downloads));
    txt(E.stBytes, stats.bytesText || fmtBytes(stats.bytes));
    txt(E.stVisitors, nfmt(stats.visitors != null ? stats.visitors : visitors.length));
    txt(E.stActive, nfmt(activeCount));
  }

  /* ------------------------------------------------------------------ *
   *  actions wiring
   * ------------------------------------------------------------------ */

  var addBusy = null;   /* "add-files" | "add-folder" | null — native dialogs are modal */

  function paintAddButtons() {
    var btns = document.querySelectorAll('[data-act]');
    for (var i = 0; i < btns.length; i++) {
      var b = btns[i];
      b.classList.toggle('is-busy', addBusy === b.dataset.act);
      b.disabled = !!addBusy && addBusy !== b.dataset.act;
    }
  }

  function runAdd(action) {
    if (addBusy) return;
    addBusy = action;
    paintAddButtons();
    post('/api/items/' + action).then(function (r) {
      addBusy = null;
      paintAddButtons();
      if (!r.ok) toast(r.error, 'error');
    });
  }

  var clearArmed = false, clearTimer = null;

  function paintClear() {
    cls(E.btnClear, 'btn-danger', clearArmed);
    txt($('.btn-label', E.btnClear), clearArmed ? '¿Vaciar todo?' : 'Vaciar');
    attr(E.btnClear, 'aria-label', clearArmed
      ? 'Confirmar: quitar todos los elementos'
      : 'Quitar todos los elementos');
  }

  function disarmClear() {
    clearArmed = false;
    clearTimeout(clearTimer);
    paintClear();
  }

  function bind() {
    document.addEventListener('click', function (ev) {
      var b = ev.target.closest ? ev.target.closest('[data-act]') : null;
      if (b && b.dataset.act) runAdd(b.dataset.act);
    });

    E.btnCopy.addEventListener('click', function () {
      post('/api/share/copy').then(function (r) {
        if (r.ok) flashCopied();
        else toast(r.error, 'error');
      });
    });

    E.btnToggle.addEventListener('click', function () {
      var stop = E.btnToggle.dataset.mode === 'stop';
      act(stop ? '/api/share/stop' : '/api/share/start');
    });

    E.btnClear.addEventListener('click', function () {
      if (clearArmed) {
        disarmClear();
        act('/api/items/clear');
        return;
      }
      clearArmed = true;
      paintClear();
      clearTimeout(clearTimer);
      clearTimer = setTimeout(disarmClear, 3000);
    });
    E.btnClear.addEventListener('blur', function () {
      if (clearArmed) setTimeout(disarmClear, 120);
    });

    $('#btn-minimise').addEventListener('click', function () { post('/api/window/minimise'); });
    $('#btn-hide').addEventListener('click', function () { post('/api/window/hide'); });

    E.logbox.addEventListener('toggle', function () {
      if (E.logbox.open) E.logLines.scrollTop = E.logLines.scrollHeight;
    });

    E.stage.addEventListener('scroll', function () {
      cls(E.topbar, 'is-scrolled', E.stage.scrollTop > 2);
    }, { passive: true });

    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape' && clearArmed) disarmClear();
    });
  }

  /* ------------------------------------------------------------------ *
   *  drag & drop affordance
   *  Wails handles the real drop natively on the Go side; JS only paints
   *  the overlay and never touches the payload.
   * ------------------------------------------------------------------ */

  var dragDepth = 0, dragTimer = null;

  function veilOn() {
    cls(E.veil, 'is-on', true);
    clearTimeout(dragTimer);
    dragTimer = setTimeout(veilOff, 1200);  /* safety: the native drop can swallow `drop` */
  }
  function veilOff() {
    dragDepth = 0;
    clearTimeout(dragTimer);
    cls(E.veil, 'is-on', false);
  }

  function bindDnd() {
    window.addEventListener('dragenter', function (ev) {
      ev.preventDefault();
      dragDepth++;
      veilOn();
    });
    window.addEventListener('dragover', function (ev) {
      ev.preventDefault();
      if (ev.dataTransfer) { try { ev.dataTransfer.dropEffect = 'copy'; } catch (e) {} }
      if (dragDepth < 1) dragDepth = 1;
      veilOn();
    });
    window.addEventListener('dragleave', function (ev) {
      ev.preventDefault();
      dragDepth = Math.max(0, dragDepth - 1);
      if (dragDepth === 0) veilOff();
    });
    window.addEventListener('drop', function (ev) {
      ev.preventDefault();
      veilOff();
    });
    window.addEventListener('dragend', function () { veilOff(); });
    window.addEventListener('blur', function () { veilOff(); });
  }

  /* ------------------------------------------------------------------ *
   *  transport
   * ------------------------------------------------------------------ */

  var es = null, everOpen = false;

  function setReconnecting(on) {
    show(E.reconnect, on);
  }

  function connect() {
    if (es) { try { es.close(); } catch (e) {} }
    var url = '/api/events' + (TOKEN ? '?t=' + encodeURIComponent(TOKEN) : '');
    es = new EventSource(url);

    es.addEventListener('open', function () {
      everOpen = true;
      setReconnecting(false);
    });

    es.addEventListener('state', function (ev) {
      setReconnecting(false);
      try { apply(JSON.parse(ev.data)); } catch (e) {}
    });

    es.addEventListener('error', function () {
      /* EventSource reconnects on its own; just hint at it */
      setReconnecting(true);
      if (!everOpen) setTimeout(function () { if (es && es.readyState === 2) connect(); }, 2000);
    });
  }

  function loadState() {
    return fetch('/api/state', { headers: { 'X-FTE-Token': TOKEN } })
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(apply)
      .catch(function () {
        toast('No se pudo cargar el estado de la aplicación', 'error');
        apply({ items: [] });
      });
  }

  /* ------------------------------------------------------------------ *
   *  boot
   * ------------------------------------------------------------------ */

  function boot() {
    if (/Mac|iPhone|iPad/i.test(navigator.userAgent || '')) {
      document.documentElement.classList.add('is-mac');
    }
    cache();
    bind();
    bindDnd();
    paintClear();
    paintCopy();
    paintAddButtons();

    /* keep both views hidden until the first state lands, so we never flash the
       wrong screen; fall back to the empty state if the backend is slow */
    setTimeout(function () { if (!gotState) apply({ items: [] }); }, 1200);

    loadState().then(connect);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
