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

    var a = el("a", "icon-btn");
    a.href = BASE + "/download/" + encodeURIComponent(f && f.id != null ? f.id : "");
    a.setAttribute("download", name);
    a.setAttribute("data-dl", "");
    a.setAttribute("aria-label", "Descargar " + name);
    a.appendChild(icon("download", "ic ic-dl"));
    a.appendChild(icon("check", "ic ic-ok"));
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

    if (count > 0) ctaEl.removeAttribute("hidden");
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
    summaryEl.textContent = "Sin archivos por ahora";
    ctaEl.setAttribute("hidden", "");

    var p = panel({
      icon: "inbox",
      accent: true,
      title: "Todavía no hay archivos aquí",
      text: "Quien comparte este enlace aún no ha añadido nada, o acaba de retirarlo. " +
        "Puede añadir archivos en cualquier momento."
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
      title: "Este enlace ya no está disponible",
      text: "Quien te lo envió ha dejado de compartir estos archivos. " +
        "Pídele un enlace nuevo si todavía los necesitas."
    }));
    setBusy(false);
    showHint(false);
    document.title = "Enlace no disponible · File Transfer Easy";
    mode = "expired";
  }

  function renderError() {
    summaryEl.textContent = "No hemos podido cargar la lista";
    ctaEl.setAttribute("hidden", "");

    var p = panel({
      icon: "retry",
      title: "No se ha podido conectar",
      text: "Comprueba tu conexión. El equipo que comparte los archivos también " +
        "puede estar apagado o sin red en este momento."
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

  /* ------------------------------------------------------------- datos --- */

  function load(force) {
    if (stopped || inFlight) return;
    inFlight = true;

    fetch(MANIFEST_URL, {
      method: "GET",
      cache: "no-store",
      credentials: "same-origin",
      headers: { "Accept": "application/json" }
    }).then(function (res) {
      if (res.status === 410) {
        renderExpired();
        return null;
      }
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    }).then(function (data) {
      if (data == null || stopped) return;
      if (data.expired === true) {
        renderExpired();
        return;
      }
      showHint(false);

      var sig = JSON.stringify(data);
      if (!force && sig === lastSignature && (mode === "files" || mode === "empty")) return;
      lastSignature = sig;
      renderFiles(data);
    }).catch(function () {
      if (stopped) return;
      if (mode === "files" || mode === "empty") {
        // Ya hay contenido en pantalla: no lo destruimos por un fallo puntual.
        showHint(true);
      } else if (mode !== "error") {
        // Sólo pintamos el panel una vez: los reintentos no deben repetir el aviso.
        renderError();
      }
    }).then(function () {
      inFlight = false;
    });
  }

  function ping() {
    if (stopped) return;
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

  stage.addEventListener("click", function (ev) {
    var target = ev.target;
    if (!target || !target.closest) return;
    var link = target.closest("a[data-dl]");
    if (!link) return;
    flash(link.closest(".row"));
  });

  zipLink.addEventListener("click", function () {
    zipLink.classList.add("is-dl");
    window.setTimeout(function () { zipLink.classList.remove("is-dl"); }, FLASH_MS);
  });

  /* ------------------------------------------------------------ arranque --- */

  renderLoading();
  load(true);
  ping();
  startTimers();
})();
