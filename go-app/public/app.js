/* ==========================================================================
   File Transfer Easy — página pública de descarga
   Sin dependencias. Habla con el servidor público por fetch.
   ========================================================================== */

(function () {
  "use strict";

  /* ------------------------------------------------------------- base --- */

  // El literal se parte para que una sustitución global en los assets no lo toque.
  var PLACEHOLDER = "__FTE" + "_BASE__";

  function resolveBase() {
    var raw = typeof window.__FTE_BASE__ === "string" ? window.__FTE_BASE__ : "";
    if (!raw || raw === PLACEHOLDER) {
      // Reserva para desarrollo local: deducimos la base de la propia URL.
      raw = window.location.pathname.replace(/\/index\.html$/, "");
    }
    return raw.replace(/\/+$/, "");
  }

  var BASE = resolveBase();
  var MANIFEST_URL = BASE + "/api/manifest";
  var PING_URL = BASE + "/ping";
  var ZIP_URL = BASE + "/zip";

  var POLL_MS = 5000;
  var PING_MS = 10000;
  var FLASH_MS = 1800;

  /* ------------------------------------------------------------ iconos --- */

  function svg(paths) {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" ' +
      'stroke-linecap="round" stroke-linejoin="round" focusable="false" aria-hidden="true">' +
      paths + "</svg>";
  }

  var ICONS = {
    lock: svg('<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>'),
    download: svg('<path d="M12 3.7v10.5"/><path d="m7.9 10.1 4.1 4.1 4.1-4.1"/>' +
      '<path d="M4.8 16.4v1.8a2.1 2.1 0 0 0 2.1 2.1h10.2a2.1 2.1 0 0 0 2.1-2.1v-1.8"/>'),
    check: svg('<path d="m5.4 12.4 4.3 4.3 8.9-9"/>'),
    file: svg('<path d="M6.6 3.6h6.9L19 9.1v11.3H6.6z"/><path d="M13.5 3.6v5.5H19"/>'),
    folder: svg('<path d="M3.6 7.1a2 2 0 0 1 2-2h3.2l2 2.2h7.6a2 2 0 0 1 2 2v7.6a2 2 0 0 1-2 2H5.6a2 2 0 0 1-2-2z"/>'),
    chevron: svg('<path d="m9.6 5.9 6.1 6.1-6.1 6.1"/>'),
    clock: svg('<circle cx="12" cy="12" r="8.3"/><path d="M12 7.5V12l3.1 1.9"/>'),
    inbox: svg('<path d="M3.7 13.5 6.3 5.9a2 2 0 0 1 1.9-1.4h7.6a2 2 0 0 1 1.9 1.4l2.6 7.6"/>' +
      '<path d="M3.7 13.5h4.2l1.2 2.5h5.8l1.2-2.5h4.2v4.3a2 2 0 0 1-2 2H5.7a2 2 0 0 1-2-2z"/>'),
    retry: svg('<path d="M20.1 12a8.1 8.1 0 1 1-2.4-5.7"/><path d="M20.4 4.2v4.3h-4.3"/>')
  };

  /* ------------------------------------------------------------ utils --- */

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function icon(name, cls) {
    var s = el("span", cls || "ic");
    s.setAttribute("aria-hidden", "true");
    s.innerHTML = ICONS[name] || "";
    return s;
  }

  function plural(n, one, many) {
    return n === 1 ? one : many;
  }

  function joinDot(parts) {
    var out = [];
    for (var i = 0; i < parts.length; i++) {
      var p = parts[i];
      if (typeof p === "string" && p.trim() !== "") out.push(p.trim());
    }
    return out.join(" · ");
  }

  function bytesText(n) {
    if (typeof n !== "number" || !isFinite(n) || n <= 0) return "";
    var units = ["B", "KB", "MB", "GB", "TB"];
    var i = 0;
    var v = n;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
    var s = v >= 100 || i === 0 ? Math.round(v) : Math.round(v * 10) / 10;
    return String(s).replace(".", ",") + " " + units[i];
  }

  function filesText(n) {
    return n + " " + plural(n, "archivo", "archivos");
  }

  /* ---------------------------------------------------------- el árbol --- */

  var stage = document.getElementById("stage");
  var summaryEl = document.getElementById("summary");
  var hintEl = document.getElementById("hint");
  var ctaEl = document.getElementById("cta");
  var zipLink = document.getElementById("zipLink");
  var headBody = document.getElementById("headBody");
  var footEl = document.getElementById("foot");

  zipLink.href = ZIP_URL;

  /* ----------------------------------------------------------- estado --- */

  var mode = "loading";        // loading | files | empty | expired | error
  var lastSignature = "";
  var pollTimer = null;
  var pingTimer = null;
  var stopped = false;         // true cuando el enlace ha caducado
  var inFlight = false;

  function setStage(node) {
    stage.textContent = "";
    stage.appendChild(node);
  }

  function setBusy(busy) {
    stage.setAttribute("aria-busy", busy ? "true" : "false");
  }

  function showHint(on) {
    if (on) hintEl.removeAttribute("hidden");
    else hintEl.setAttribute("hidden", "");
  }

  /* ------------------------------------------------------ construcción --- */

  function extTile(ext, isFolder) {
    var t = el("span", "tile");
    if (isFolder) {
      t.className = "tile tile-folder";
      t.appendChild(icon("folder"));
      return t;
    }
    var e = (ext || "").replace(/^\./, "").trim();
    if (!e) {
      t.appendChild(icon("file"));
      return t;
    }
    e = e.toUpperCase().slice(0, 4);
    t.textContent = e;
    t.setAttribute("data-len", String(e.length));
    return t;
  }

  function fileRow(f) {
    var name = f && f.name ? String(f.name) : "Archivo";
    var li = el("li", "row");

    li.appendChild(extTile(f && f.ext, false));

    var txt = el("span", "row-text");
    var nameEl = el("span", "row-name", name);
    nameEl.title = name;
    txt.appendChild(nameEl);
    txt.appendChild(el("span", "row-meta",
      joinDot([f && f.sizeText, f && f.modifiedText]) || "—"));
    txt.appendChild(el("span", "row-flash", "Descarga iniciada"));
    li.appendChild(txt);

    if (f.locked) {
      var unlock = el('button', 'unlock-button', 'Desbloquear'); unlock.type = 'button';
      unlock.setAttribute('aria-label', 'Desbloquear ' + name);
      unlock.addEventListener('click', function () { openUnlock(f); });
      li.appendChild(unlock); return li;
    }
    if (f.protected) txt.appendChild(el('span', 'locked-badge', 'Desbloqueado'));
    var a = el("a", "icon-btn");
    a.href = BASE + "/download/" + encodeURIComponent(f && f.id != null ? f.id : "");
    a.setAttribute("download", name);
    a.setAttribute("data-dl", "");
    a.setAttribute("data-id", String(f.id));
    a.setAttribute("aria-label", "Descargar " + name);
    a.appendChild(icon("download", "ic ic-dl"));
    a.appendChild(icon("check", "ic ic-ok"));
    a.appendChild(el("span", "dl-label", "Descargar"));
    li.appendChild(a);

    return li;
  }

  function rowsList(files) {
    var ul = el("ul", "rows");
    for (var i = 0; i < files.length; i++) ul.appendChild(fileRow(files[i]));
    return ul;
  }

  function folderGroup(group) {
    var d = el("details", "group folder");
    d.open = true;

    var s = el("summary", "folder-head");
    s.appendChild(extTile("", true));

    var txt = el("span", "row-text");
    var nameEl = el("span", "folder-name", group.name);
    nameEl.title = group.name;
    txt.appendChild(nameEl);
    txt.appendChild(el("span", "folder-meta",
      joinDot([filesText(group.count), group.sizeText])));
    s.appendChild(txt);
    s.appendChild(icon("chevron", "ic chev"));
    d.appendChild(s);

    if (group.files.length) {
      d.appendChild(rowsList(group.files));
    } else {
      d.appendChild(el("p", "folder-note",
        "Los archivos de esta carpeta se incluyen en la descarga ZIP."));
    }
    return d;
  }

  function buildGroups(data) {
    var files = Array.isArray(data.files) ? data.files : [];
    var folders = Array.isArray(data.folders) ? data.folders : [];

    var loose = [];
    var byName = Object.create(null);
    var order = [];

    function bucket(name) {
      if (!byName[name]) {
        byName[name] = { name: name, files: [], bytes: 0, sizeText: "", count: 0 };
        order.push(name);
      }
      return byName[name];
    }

    // Las carpetas anunciadas por el servidor mandan en el orden.
    for (var i = 0; i < folders.length; i++) {
      var fo = folders[i];
      if (!fo || !fo.name) continue;
      var b = bucket(String(fo.name));
      b.declaredCount = typeof fo.fileCount === "number" ? fo.fileCount : null;
      b.declaredSize = fo.sizeText || "";
    }

    for (var j = 0; j < files.length; j++) {
      var f = files[j];
      if (!f) continue;
      var folderName = f.folder ? String(f.folder) : "";
      if (folderName === "") {
        loose.push(f);
      } else {
        var g = bucket(folderName);
        g.files.push(f);
        if (typeof f.size === "number") g.bytes += f.size;
      }
    }

    var groups = [];
    for (var k = 0; k < order.length; k++) {
      var grp = byName[order[k]];
      grp.count = grp.declaredCount != null ? grp.declaredCount : grp.files.length;
      grp.sizeText = grp.declaredSize || bytesText(grp.bytes);
      groups.push(grp);
    }
    return { loose: loose, groups: groups };
  }

  /* ----------------------------------------------------------- estados --- */

  function panel(opts) {
    var p = el("section", "panel" + (opts.accent ? " panel-accent" : "") +
      (opts.extra ? " " + opts.extra : ""));
    var ic = el("span", "panel-icon");
    ic.appendChild(icon(opts.icon));
    p.appendChild(ic);
    p.appendChild(el("h2", null, opts.title));
    if (opts.text) p.appendChild(el("p", null, opts.text));
    return p;
  }

  function renderFiles(data) {
    var totals = data.totals || {};
    var count = typeof totals.files === "number" ? totals.files : (data.files || []).length;

    summaryEl.textContent = joinDot([filesText(count), totals.bytesText]);

    var available = (data.files || []).filter(function (file) { return !file.locked; }).length;
    var label = zipLink.querySelector('span:last-child');
    if (label) label.textContent = available < count ? 'Descargar disponibles (ZIP)' : 'Descargar todo (ZIP)';
    if (available > 0) ctaEl.removeAttribute("hidden");
    else ctaEl.setAttribute("hidden", "");

    if (count === 0) {
      renderEmpty();
      return;
    }

    var built = buildGroups(data);
    var frag = document.createDocumentFragment();

    if (built.loose.length) {
      if (built.groups.length) frag.appendChild(el("h2", "sect", "Archivos sueltos"));
      var card = el("div", "group");
      card.appendChild(rowsList(built.loose));
      frag.appendChild(card);
    }

    for (var i = 0; i < built.groups.length; i++) {
      frag.appendChild(folderGroup(built.groups[i]));
    }

    var wrap = el("div", "list");
    wrap.appendChild(frag);
    setStage(wrap);
    setBusy(false);
    mode = "files";
  }

  function renderEmpty() {
    summaryEl.textContent = "Sin archivos";
    ctaEl.setAttribute("hidden", "");

    var p = panel({
      icon: "inbox",
      accent: true,
      title: "Sin archivos",
      text: publicOptions.uploadsEnabled ? "Puedes enviar archivos desde esta página." : "Todavía no hay archivos compartidos."
    });
    var live = el("span", "live");
    live.appendChild(el("span", "live-dot"));
    live.appendChild(el("span", null, "Esta página se actualiza sola"));
    p.appendChild(live);

    setStage(p);
    setBusy(false);
    mode = "empty";
  }

  function renderExpired() {
    if (mode === "expired") return;
    stopTimers();
    stopped = true;
    lastSignature = "";

    headBody.setAttribute("hidden", "");
    footEl.setAttribute("hidden", "");

    setStage(panel({
      icon: "clock",
      extra: "panel-expired",
      title: "Enlace no disponible",
      text: "El remitente ha dejado de compartir. Solicita un enlace nuevo."
    }));
    setBusy(false);
    showHint(false);
    document.title = "Enlace no disponible · File Transfer Easy";
    mode = "expired";
  }

  function renderError(message) {
    summaryEl.textContent = "No se pudo cargar la lista";
    ctaEl.setAttribute("hidden", "");

    var p = panel({
      icon: "retry",
      title: "No se ha podido conectar",
      text: errorText(message || 'No se pudo conectar con el remitente. Comprueba tu conexión e inténtalo de nuevo.')
    });

    var btn = el("button", "btn btn-secondary");
    btn.type = "button";
    btn.appendChild(icon("retry", "ic ic-20"));
    btn.appendChild(el("span", null, "Reintentar"));
    btn.addEventListener("click", function () {
      btn.disabled = true;
      renderLoading();
      load(true);
    });
    p.appendChild(btn);

    setStage(p);
    setBusy(false);
    mode = "error";
  }

  function renderLoading() {
    var card = el("div", "group");
    var ul = el("ul", "rows");
    var widths = [["w-58", "w-30"], ["w-72", "w-24"], ["w-44", "w-34"],
      ["w-64", "w-24"], ["w-50", "w-30"]];
    for (var i = 0; i < widths.length; i++) {
      var li = el("li", "row");
      li.appendChild(el("span", "sk sk-tile"));
      var txt = el("span", "row-text");
      txt.appendChild(el("span", "sk sk-line " + widths[i][0]));
      txt.appendChild(el("span", "sk sk-line sk-line-sm " + widths[i][1]));
      li.appendChild(txt);
      li.appendChild(el("span", "sk sk-btn"));
      ul.appendChild(li);
    }
    card.appendChild(ul);
    setStage(card);
    setBusy(true);
    showHint(false);
    mode = "loading";
  }

  var accessState = null, lastGate = '', publicOptions = {}, customError = '';
  var unlockTarget = null, unlockReturnFocus = null, selectedUploads = [], uploadRequest = null;

  function showMessage(message, error) {
    var node = document.getElementById('action-message');
    node.textContent = message || '';
    node.hidden = !message;
    node.classList.toggle('is-error', !!error);
  }
  function reason(data, fallback) { return data && (data.error || data.message) || fallback; }
  function requestJSON(url, options) {
    options = options || {}; options.credentials = 'same-origin'; options.cache = 'no-store';
    return fetch(url, options).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        return { ok: response.ok, code: response.status, data: data };
      });
    });
  }
  function postJSON(url, data) {
    return requestJSON(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data || {}) });
  }
  function applyPublicOptions(data) {
    var options = data.settings || data;
    var theme = options.theme || data.theme || 'light';
    document.documentElement.setAttribute('data-theme', theme === 'dark' ? 'dark' : 'light');
    var title = options.pageTitle || data.title || 'Archivos compartidos';
    document.getElementById('page-title').textContent = title;
    document.title = title + ' · File Transfer Easy';
    customError = options.errorMessage || '';
    publicOptions.uploadsEnabled = options.uploadsEnabled === true || data.uploadsEnabled === true;
    publicOptions.maxUploadMB = Number(options.maxUploadMB || data.maxUploadMB) || 100;
    var section = document.getElementById('upload-section');
    section.hidden = !(accessState && accessState.status === 'allowed' && publicOptions.uploadsEnabled);
    document.getElementById('upload-limit').textContent = 'Máximo ' + publicOptions.maxUploadMB + ' MB por envío.';
  }
  function errorText(message) {
    return customError && message.indexOf(customError) < 0 ? message + '\n' + customError : message;
  }

  function renderGate(data) {
    accessState = data; applyPublicOptions(data);
    ctaEl.hidden = true;
    summaryEl.textContent = '';
    if (uploadRequest) uploadRequest.abort();
    var signature = [data.status, data.message, data.requestId].join('|');
    if (lastGate === signature) return;
    lastGate = signature; lastSignature = '';
    var titles = { password: 'Acceso con contraseña', pending: 'Esperando autorización', denied: 'Acceso rechazado', blocked: 'Acceso bloqueado' };
    var defaults = { password: 'Introduce la contraseña de esta página.', pending: 'Tu solicitud se ha enviado. La página se abrirá cuando el remitente autorice el acceso.', denied: 'El remitente ha rechazado la solicitud.', blocked: 'El remitente ha bloqueado el acceso desde este dispositivo.' };
    var gate = el('section', 'gate'); gate.appendChild(el('h2', '', titles[data.status] || 'Acceso no disponible'));
    gate.appendChild(el('p', '', data.message || defaults[data.status] || 'No se ha autorizado el acceso.'));
    if (data.status === 'password' || data.status === 'pending') {
      var form = el('form'), password, name;
      if (data.status === 'password') {
        var passwordLabel = el('label', '', 'Contraseña'); password = el('input'); password.type = 'password'; password.autocomplete = 'current-password'; password.required = true; passwordLabel.appendChild(password); form.appendChild(passwordLabel);
      }
      var nameLabel = el('label', '', 'Tu nombre (opcional)'); name = el('input'); name.type = 'text'; name.autocomplete = 'nickname'; name.maxLength = 80; nameLabel.appendChild(name); form.appendChild(nameLabel);
      var error = el('p', 'form-error'); error.hidden = true; error.setAttribute('role', 'alert'); form.appendChild(error);
      var submit = el('button', 'btn btn-primary', data.status === 'password' ? 'Continuar' : 'Actualizar nombre'); submit.type = 'submit'; form.appendChild(submit);
      form.addEventListener('submit', function (event) {
        event.preventDefault(); submit.disabled = true; error.hidden = true;
        var body = { name: name.value.trim() }; if (password) body.password = password.value;
        postJSON(BASE + '/api/access', body).then(function (result) {
          submit.disabled = false;
          if (['allowed', 'password', 'pending', 'denied', 'blocked'].indexOf(result.data.status) < 0) { error.textContent = errorText(reason(result.data, 'No se pudo comprobar el acceso (HTTP ' + result.code + ').')); error.hidden = false; return; }
          if (result.data.status === 'password') { error.textContent = errorText(reason(result.data, 'La contraseña no es correcta.')); error.hidden = false; return; }
          if (result.data.status === 'allowed') { lastGate = ''; load(true); }
          else { lastGate = ''; renderGate(result.data); }
        }).catch(function () { submit.disabled = false; error.textContent = 'No se pudo conectar con el remitente.'; error.hidden = false; });
      });
      gate.appendChild(form);
    } else {
      var retry = el('button', 'btn btn-secondary', 'Comprobar acceso'); retry.type = 'button'; retry.addEventListener('click', function () { load(true); }); gate.appendChild(retry);
    }
    setStage(gate); setBusy(false); showHint(false); mode = data.status;
  }

  function openUnlock(file) {
    unlockTarget = file; unlockReturnFocus = document.activeElement;
    var dialog = document.getElementById('unlock-dialog');
    var kind = file.protectionKind || (file.folder ? 'folder' : 'file');
    document.getElementById('unlock-title').textContent = kind === 'folder' ? 'Desbloquear carpeta' : 'Desbloquear archivo';
    document.getElementById('unlock-name').textContent = file.protectionName || (kind === 'folder' ? file.folder || file.name : file.name);
    document.getElementById('unlock-password').value = '';
    document.getElementById('unlock-error').hidden = true;
    if (dialog.showModal) dialog.showModal(); else dialog.setAttribute('open', '');
    setTimeout(function () { document.getElementById('unlock-password').focus(); }, 0);
  }
  function closeUnlock() {
    var dialog = document.getElementById('unlock-dialog');
    if (dialog.close) dialog.close(); else dialog.removeAttribute('open');
    if (unlockReturnFocus && unlockReturnFocus.focus) unlockReturnFocus.focus();
  }
  document.getElementById('unlock-cancel').addEventListener('click', closeUnlock);
  document.getElementById('unlock-form').addEventListener('submit', function (event) {
    event.preventDefault(); if (!unlockTarget) return;
    var button = document.getElementById('unlock-submit'), error = document.getElementById('unlock-error');
    button.disabled = true; error.hidden = true;
    postJSON(BASE + '/api/unlock', { id: unlockTarget.id, password: document.getElementById('unlock-password').value }).then(function (result) {
      button.disabled = false;
      if (!result.ok || result.data.ok === false) { error.textContent = errorText(reason(result.data, 'No se pudo desbloquear el archivo (HTTP ' + result.code + ').')); error.hidden = false; return; }
      closeUnlock(); load(true);
    }).catch(function () { button.disabled = false; error.textContent = 'No se pudo conectar con el remitente.'; error.hidden = false; });
  });

  function paintUploads() {
    var list = document.getElementById('upload-selection'); list.textContent = '';
    selectedUploads.forEach(function (file) { var row = el('li'); row.appendChild(el('span', '', file.name)); row.appendChild(el('small', '', bytesText(file.size) || '0 B')); list.appendChild(row); });
    document.getElementById('upload-actions').hidden = selectedUploads.length === 0 && !uploadRequest;
    document.getElementById('upload-start').disabled = !!uploadRequest || selectedUploads.length === 0;
    document.getElementById('upload-cancel').hidden = !uploadRequest;
    document.getElementById('upload-files').disabled = !!uploadRequest;
  }
  document.getElementById('upload-files').addEventListener('change', function () {
    selectedUploads = Array.prototype.slice.call(this.files || []);
    document.getElementById('upload-status').textContent = ''; document.getElementById('upload-progress').hidden = true;
    showMessage(''); paintUploads();
  });
  document.getElementById('upload-cancel').addEventListener('click', function () { if (uploadRequest) uploadRequest.abort(); });
  document.getElementById('upload-start').addEventListener('click', function () {
    if (uploadRequest || !selectedUploads.length) return;
    var maximum = publicOptions.maxUploadMB * 1024 * 1024;
    if (selectedUploads.length > 64) { showMessage('Selecciona como máximo 64 archivos por envío.', true); return; }
    var total = selectedUploads.reduce(function (sum, file) { return sum + file.size; }, 0);
    if (total > maximum) { showMessage('El envío supera el límite de ' + publicOptions.maxUploadMB + ' MB. Selecciona menos archivos.', true); return; }
    var tooLarge = selectedUploads.filter(function (file) { return file.size > maximum; });
    if (tooLarge.length) { showMessage('«' + tooLarge[0].name + '» supera el límite de ' + publicOptions.maxUploadMB + ' MB.', true); return; }
    var payload = new FormData(); selectedUploads.forEach(function (file) { payload.append('files', file, file.name); });
    var xhr = new XMLHttpRequest(), progress = document.getElementById('upload-progress'), status = document.getElementById('upload-status');
    uploadRequest = xhr; progress.value = 0; progress.hidden = false; status.textContent = 'Enviando…'; showMessage(''); paintUploads();
    xhr.open('POST', BASE + '/upload'); xhr.withCredentials = true;
    xhr.upload.addEventListener('progress', function (event) { if (event.lengthComputable) { progress.value = Math.round(event.loaded / event.total * 100); status.textContent = 'Enviando… ' + progress.value + '%'; } });
    function finish() { uploadRequest = null; paintUploads(); }
    xhr.addEventListener('load', function () {
      var data; try { data = JSON.parse(xhr.responseText); } catch (e) { data = {}; }
      if (xhr.status >= 200 && xhr.status < 300 && data.ok !== false) {
        var count = data.files ? data.files.length : selectedUploads.length;
        selectedUploads = []; document.getElementById('upload-files').value = ''; progress.value = 100; status.textContent = 'Envío completado'; finish(); showMessage(count + ' ' + plural(count, 'archivo enviado', 'archivos enviados')); load(true);
      } else { finish(); status.textContent = 'No se completó el envío'; showMessage(errorText(reason(data, xhr.responseText || 'Error al enviar los archivos (HTTP ' + xhr.status + ').')), true); if (xhr.status === 401 || xhr.status === 403) load(true); }
    });
    xhr.addEventListener('error', function () { finish(); status.textContent = 'Envío interrumpido'; showMessage('La conexión se ha interrumpido durante la subida. Puedes reintentarlo.', true); });
    xhr.addEventListener('abort', function () { finish(); status.textContent = 'Envío cancelado'; progress.hidden = true; });
    xhr.send(payload);
  });


  /* ------------------------------------------------------------- datos --- */

  function load(force) {
    if (stopped || inFlight) return;
    inFlight = true;
    requestJSON(BASE + '/api/access').then(function (result) {
      if (result.code === 410 || result.code === 404) { renderExpired(); return null; }
      var data = result.data;
      if (!data || ['allowed', 'password', 'pending', 'denied', 'blocked'].indexOf(data.status) < 0) throw new Error(reason(data, 'No se pudo comprobar el acceso (HTTP ' + result.code + ').'));
      accessState = data; applyPublicOptions(data);
      if (data.status !== 'allowed') { renderGate(data); return null; }
      lastGate = '';
      return requestJSON(MANIFEST_URL).then(function (manifestResult) {
        if (manifestResult.code === 410 || manifestResult.code === 404 || manifestResult.data.expired) { renderExpired(); return; }
        if (!manifestResult.ok) {
          if (manifestResult.data.status) { renderGate(manifestResult.data); return; }
          throw new Error(reason(manifestResult.data, 'No se pudo cargar la lista (HTTP ' + manifestResult.code + ').'));
        }
        var manifest = manifestResult.data;
        applyPublicOptions(manifest); showHint(false);
        var signature = JSON.stringify(manifest);
        if (!force && signature === lastSignature && (mode === 'files' || mode === 'empty')) return;
        lastSignature = signature; renderFiles(manifest);
      });
    }).catch(function (error) {
      if (stopped) return;
      if (mode === 'files' || mode === 'empty') { showHint(true); showMessage(errorText(error.message), true); }
      else renderError(error.message);
    }).then(function () { inFlight = false; });
  }

  function ping() {
    if (stopped || !accessState || accessState.status !== 'allowed') return;
    fetch(PING_URL, {
      method: "POST",
      cache: "no-store",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: "{}",
      keepalive: true
    }).then(function (res) {
      if (res && res.status === 410) renderExpired();
    }).catch(function () { /* fire and forget */ });
  }

  /* ----------------------------------------------------------- timers --- */

  function startTimers() {
    stopTimers();
    if (stopped) return;
    pollTimer = window.setInterval(function () {
      if (document.visibilityState === "visible") load(false);
    }, POLL_MS);
    pingTimer = window.setInterval(function () {
      if (document.visibilityState === "visible") ping();
    }, PING_MS);
  }

  function stopTimers() {
    if (pollTimer) { window.clearInterval(pollTimer); pollTimer = null; }
    if (pingTimer) { window.clearInterval(pingTimer); pingTimer = null; }
  }

  document.addEventListener("visibilitychange", function () {
    if (stopped) return;
    if (document.visibilityState === "visible") {
      load(false);
      ping();
    }
  });

  /* ------------------------------------------- feedback en la descarga --- */

  function flash(row) {
    if (!row) return;
    row.classList.add("is-dl");
    if (row._fteTimer) window.clearTimeout(row._fteTimer);
    row._fteTimer = window.setTimeout(function () {
      row.classList.remove("is-dl");
      row._fteTimer = null;
    }, FLASH_MS);
  }

  function beginDownload(link, checkURL, row) {
    if (link.dataset.downloadBusy) return;
    link.dataset.downloadBusy = 'true'; link.setAttribute('aria-busy', 'true'); showMessage('');
    requestJSON(checkURL).then(function (result) {
      if (!result.ok || result.data.ok === false) {
        showMessage(errorText(reason(result.data, 'No se pudo iniciar la descarga (HTTP ' + result.code + ').')), true);
        if (result.code === 401 || result.code === 403) load(true);
        return;
      }
      // Keep the stream in the browser's download manager; large files never
      // accumulate in a JavaScript Blob. The streaming endpoint validates again.
      var download = el('a');
      download.href = typeof result.data.url === 'string' && result.data.url.indexOf(BASE + '/') === 0 ? result.data.url : link.href;
      download.setAttribute('download', link.getAttribute('download') || '');
      download.hidden = true; document.body.appendChild(download); download.click(); document.body.removeChild(download);
      if (row) flash(row);
    }).catch(function (error) { showMessage('No se pudo comprobar la descarga' + (error.message ? ': ' + error.message : '.'), true); })
      .then(function () { delete link.dataset.downloadBusy; link.removeAttribute('aria-busy'); });
  }
  stage.addEventListener('click', function (event) {
    var link = event.target && event.target.closest ? event.target.closest('a[data-dl]') : null;
    if (!link) return;
    event.preventDefault();
    beginDownload(link, BASE + '/api/download/' + encodeURIComponent(link.dataset.id), link.closest('.row'));
  });
  zipLink.addEventListener('click', function (event) {
    event.preventDefault(); beginDownload(zipLink, BASE + '/api/zip');
  });

  /* ------------------------------------------------------------ arranque --- */

  renderLoading();
  load(true);
  ping();
  startTimers();
})();
