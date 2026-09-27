/* Streamlit component protocol; no external scripts or network requests. */
(() => {
  const names = new Set(["sf_auth", "sf_auth_persist", "sf_last_username"]);
  let lastResponse = "";
  const send = (type, fields = {}) => window.parent.postMessage(
    {isStreamlitMessage: true, type, ...fields}, "*"
  );
  function readCookies() {
    const values = {};
    for (const part of document.cookie.split(";")) {
      const index = part.indexOf("=");
      if (index < 0) continue;
      const name = part.slice(0, index).trim();
      if (!names.has(name)) continue;
      try { values[name] = decodeURIComponent(part.slice(index + 1)); }
      catch (_) { /* Ignore malformed cookies. */ }
    }
    return values;
  }
  window.addEventListener("message", event => {
    if (event.source !== window.parent || event.data.type !== "streamlit:render") return;
    const {operations = {}, revision} = event.data.args;
    let error = "";
    let cookies = {};
    try {
      for (const [name, operation] of Object.entries(operations)) {
        if (!names.has(name)) continue;
        const secure = window.location.protocol === "https:" ? "; Secure" : "";
        const expiry = operation.value === null
          ? "; Max-Age=0"
          : `; Expires=${new Date(operation.expires).toUTCString()}`;
        document.cookie = `${name}=${encodeURIComponent(operation.value ?? "")}; Path=/; SameSite=Lax${expiry}${secure}`;
      }
      cookies = readCookies();
      for (const [name, operation] of Object.entries(operations)) {
        if (!names.has(name)) continue;
        if (operation.value === null ? name in cookies : cookies[name] !== operation.value) {
          error = "Your browser could not save the sign-in change. Please allow cookies for this site.";
        }
      }
    } catch (_) {
      error = "Your browser could not access saved sign-in cookies. Please allow cookies for this site.";
    }
    const value = {revision, cookies, error};
    const response = JSON.stringify(value);
    if (response !== lastResponse) {
      lastResponse = response;
      send("streamlit:setComponentValue", {value, dataType: "json"});
    }
    send("streamlit:setFrameHeight", {height: 0});
  });
  send("streamlit:componentReady", {apiVersion: 1});
})();
