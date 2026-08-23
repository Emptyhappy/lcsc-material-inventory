const serviceUrl = document.querySelector("#serviceUrl");
const token = document.querySelector("#token");
const status = document.querySelector("#status");

chrome.storage.local.get(["serviceUrl", "token"]).then(value => {
  serviceUrl.value = value.serviceUrl || "http://127.0.0.1:8765";
  token.value = value.token || "";
});

document.querySelector("#save").addEventListener("click", async event => {
  const button = event.currentTarget;
  const url = serviceUrl.value.trim().replace(/\/$/, "");
  const key = token.value.trim();
  status.className = "";
  if (!url || !key) { status.textContent = "请填写服务地址和连接密钥。"; status.className = "error"; return; }
  button.disabled = true; status.textContent = "正在测试连接……";
  try {
    await chrome.storage.local.set({ serviceUrl: url, token: key });
    const response = await fetch(`${url}/api/extension/status`, { headers: { "X-Inventory-Token": key } });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `连接失败 (${response.status})`);
    status.textContent = `连接成功。默认数量 ${data.default_quantity}，默认仓位：${data.default_location_name}`;
  } catch (error) {
    status.textContent = `${error.message}。请确认物料系统正在运行。`;
    status.className = "error";
  } finally { button.disabled = false; }
});
