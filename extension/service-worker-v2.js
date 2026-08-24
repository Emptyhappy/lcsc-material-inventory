const DEFAULT_URL = "http://127.0.0.1:8765";

async function getSettings() {
  const value = await chrome.storage.local.get(["serviceUrl", "token"]);
  return {
    serviceUrl: (value.serviceUrl || DEFAULT_URL).replace(/\/$/, ""),
    token: value.token || "",
  };
}

async function localRequest(path, options = {}) {
  const config = await getSettings();
  if (!config.token) throw new Error("尚未配置连接密钥");
  const response = await fetch(config.serviceUrl + path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Inventory-Token": config.token,
      ...(options.headers || {}),
    },
  });
  let payload;
  try { payload = await response.json(); }
  catch { payload = { error: `本地服务返回异常 (${response.status})` }; }
  if (!response.ok) throw new Error(payload.error || `请求失败 (${response.status})`);
  return payload;
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "IMPORT_LCSC") {
    localRequest("/api/import/lcsc", { method: "POST", body: JSON.stringify(message.payload) })
      .then(data => sendResponse({ ok: true, data }))
      .catch(error => sendResponse({ ok: false, error: error.message }));
    return true;
  }
  if (message.type === "GET_IMPORT_OPTIONS") {
    localRequest("/api/extension/status")
      .then(data => sendResponse({ ok: true, data }))
      .catch(error => sendResponse({ ok: false, error: error.message }));
    return true;
  }
  if (message.type === "CREATE_LOCATION") {
    localRequest("/api/locations", { method: "POST", body: JSON.stringify({ name: message.name }) })
      .then(data => sendResponse({ ok: true, data }))
      .catch(error => sendResponse({ ok: false, error: error.message }));
    return true;
  }
  if (message.type === "UNDO_TRANSACTION") {
    localRequest(`/api/transactions/${message.transactionId}/undo`, {
      method: "POST", body: "{}",
    })
      .then(data => sendResponse({ ok: true, data }))
      .catch(error => sendResponse({ ok: false, error: error.message }));
    return true;
  }
  if (message.type === "OPEN_OPTIONS") {
    chrome.runtime.openOptionsPage();
  }
});
