/* Mini-capa sobre la API de CEP de Adobe (sin dependencias externas). */
window.CEP = (function () {
  var cep = window.__adobe_cep__;
  function evalScript(script) {
    return new Promise(function (resolve, reject) {
      if (!cep) return reject(new Error("No estamos dentro de una app de Adobe"));
      cep.evalScript(script, function (res) {
        if (res === "EvalScript error.") return reject(new Error("EvalScript error"));
        resolve(res);
      });
    });
  }
  function call(fn, args) {
    // Llama a una función del host.jsx pasando los argumentos como JSON.
    var payload = JSON.stringify(args || {}).replace(/\\/g, "\\\\").replace(/'/g, "\\'");
    return evalScript(fn + "('" + payload + "')").then(function (r) {
      try { return JSON.parse(r); } catch (e) { return { error: "Respuesta inválida del host: " + r }; }
    });
  }
  function hostEnv() {
    try { return JSON.parse(cep.getHostEnvironment()); } catch (e) { return {}; }
  }
  function extensionPath() {
    try { return cep.getSystemPath("extension"); } catch (e) { return ""; }
  }
  function openURL(url) {
    try { cep.invokeSync ? cep.invokeSync("openURLInDefaultBrowser", url) : window.open(url); } catch (e) { window.open(url); }
  }
  return { evalScript: evalScript, call: call, hostEnv: hostEnv, extensionPath: extensionPath, openURL: openURL, available: !!cep };
})();
