/* Puente entre la interfaz de LoClip (iframe) y Premiere (ExtendScript). Arranca el motor si hace falta. */
(function () {
  var PORT = 47821;
  var BASE = "http://127.0.0.1:" + PORT;
  var ui = document.getElementById("ui");
  var wait = document.getElementById("wait");
  var msg = document.getElementById("msg");
  var hint = document.getElementById("hint");
  var env = CEP.hostEnv();
  var lang = (env.appUILocale || "es").slice(0, 2) === "en" ? "en" : "es";
  var T = {
    es: { connecting: "Conectando con el motor de LoClip…", notRunning: "El motor de LoClip no está corriendo.", starting: "Iniciando el motor… (la primera vez puede tardar un minuto mientras carga los modelos)",
          hint: "Si no arranca solo, abre «Iniciar LoClip» desde el menú Inicio / Aplicaciones, o ejecuta el instalador de nuevo.", loading: "Cargando modelos…" },
    en: { connecting: "Connecting to the LoClip engine…", notRunning: "The LoClip engine is not running.", starting: "Starting the engine… (the first time may take a minute while models load)",
          hint: "If it does not start by itself, open “Start LoClip” from the Start menu / Applications, or run the installer again.", loading: "Loading models…" },
  }[lang];
  msg.textContent = T.connecting;
  document.getElementById("btnStart").textContent = lang === "en" ? "Start engine" : "Iniciar motor";
  document.getElementById("btnRetry").textContent = lang === "en" ? "Retry" : "Reintentar";

  var started = false;
  function tryStartEngine() {
    if (started) return;
    started = true;
    msg.textContent = T.starting;
    try {
      var fs = require("fs"), path = require("path"), cp = require("child_process");
      var cfg = path.join(CEP.extensionPath(), "engine.json");
      if (!fs.existsSync(cfg)) { hint.textContent = T.hint; return; }
      var c = JSON.parse(fs.readFileSync(cfg, "utf8"));
      // c.cmd = ejecutable, c.args = argumentos, c.cwd = carpeta del motor (lo escribe el instalador)
      var envv = {}; for (var k in process.env) envv[k] = process.env[k]; for (var k2 in (c.env || {})) envv[k2] = c.env[k2];
      var child = cp.spawn(c.cmd, c.args || [], { cwd: c.cwd, env: envv, detached: true, stdio: "ignore", windowsHide: true });
      child.unref();
    } catch (e) {
      hint.textContent = T.hint + " (" + e.message + ")";
    }
  }

  var polls = 0;
  function poll() {
    var x = new XMLHttpRequest();
    x.open("GET", BASE + "/api/health", true);
    x.timeout = 1500;
    x.onload = function () {
      try {
        var h = JSON.parse(x.responseText);
        if (h.ready) return show();
        msg.textContent = h.loading || T.loading;
      } catch (e) {}
      setTimeout(poll, 1500);
    };
    x.onerror = x.ontimeout = function () {
      polls++;
      if (polls === 2) tryStartEngine();
      if (polls > 2 && !started) msg.textContent = T.notRunning;
      setTimeout(poll, polls < 10 ? 1500 : 4000);
    };
    x.send();
  }
  function show() {
    if (!ui.src) ui.src = BASE + "/?host=ppro&lang=" + lang;
    ui.classList.remove("hidden");
    wait.classList.add("hidden");
  }
  document.getElementById("btnStart").onclick = function () { started = false; tryStartEngine(); };
  document.getElementById("btnRetry").onclick = function () { polls = 0; poll(); };

  // ---- mensajes desde la interfaz ------------------------------------------------
  var handlers = {
    ping: function () { return Promise.resolve({ ok: true, app: env.appName, version: env.appVersion, locale: env.appUILocale }); },
    insert: function (a) { return CEP.call("LC_insert", a); },
    openSource: function (a) { return CEP.call("LC_openSource", a); },
    sourceMonitor: function () { return CEP.call("LC_sourceMonitor", {}); },
    playhead: function () { return CEP.call("LC_playhead", {}); },
    openURL: function (a) { CEP.openURL(a.url); return Promise.resolve({ ok: true }); },
  };
  window.addEventListener("message", function (e) {
    var d = e.data;
    if (!d || !d.loclip || !d.action) return;
    var h = handlers[d.action];
    var reply = function (ok, payload) { ui.contentWindow.postMessage({ loclip: true, id: d.id, ok: ok, result: ok ? payload : undefined, error: ok ? undefined : String(payload) }, "*"); };
    if (!h) return reply(false, "Acción desconocida: " + d.action);
    h(d.args || {}).then(function (r) { if (r && r.error) reply(false, r.error); else reply(true, r); }).catch(function (err) { reply(false, err.message || err); });
  });

  poll();
})();
