const state = {
  view: "materials",
  categoryId: null,
  categoryName: "全部物料",
  lowStock: false,
  query: "",
  categories: [],
  relations: [],
  locations: [],
  settings: {},
  expanded: new Set(),
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function number(value) {
  const n = Number(value || 0);
  return Number.isInteger(n) ? String(n) : n.toLocaleString("zh-CN", { maximumFractionDigits: 3 });
}

function dateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

async function api(path, options = {}) {
  const request = { ...options, headers: { ...(options.headers || {}) } };
  if (request.body && typeof request.body !== "string") {
    request.headers["Content-Type"] = "application/json";
    request.body = JSON.stringify(request.body);
  }
  const response = await fetch(path, request);
  const type = response.headers.get("content-type") || "";
  const payload = type.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) throw new Error(payload.error || `请求失败 (${response.status})`);
  return payload;
}

let toastTimer;
function toast(message, error = false) {
  const element = $("#toast");
  element.textContent = message;
  element.className = `toast show${error ? " error" : ""}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { element.className = "toast"; }, 2600);
}

async function loadBootstrap() {
  try {
    const [categories, locations, settings] = await Promise.all([
      api("/api/categories"), api("/api/locations"), api("/api/settings"),
    ]);
    state.categories = categories.categories;
    state.relations = categories.relations;
    state.locations = locations;
    state.settings = settings;
    const lcscRoot = state.categories.find(c => c.source === "lcsc" && c.external_id === "1");
    if (lcscRoot) state.expanded.add(lcscRoot.id);
    renderCategoryTree();
    renderCategoryOptions();
    renderSettings();
    await Promise.all([loadDashboard(), loadMaterials()]);
  } catch (error) {
    $("#serviceStatus").textContent = "本地服务连接失败";
    $(".status-dot").style.background = "#dc4150";
    toast(error.message, true);
  }
}

async function loadDashboard() {
  const data = await api("/api/dashboard");
  $("#materialCount").textContent = number(data.material_count);
  $("#stockTotal").textContent = number(data.stock_total);
  $("#lowStockCount").textContent = number(data.low_stock_count);
  $("#zeroStockCount").textContent = number(data.zero_stock_count);
}

function categoryGraph() {
  const byId = new Map(state.categories.map(item => [item.id, { ...item, children: [] }]));
  const childIds = new Set();
  for (const relation of state.relations) {
    const parent = byId.get(relation.parent_id);
    const child = byId.get(relation.child_id);
    if (parent && child) {
      parent.children.push(child);
      childIds.add(child.id);
    }
  }
  for (const item of byId.values()) {
    item.children.sort((a, b) => (a.sort_order - b.sort_order) || a.name.localeCompare(b.name, "zh-CN"));
  }
  const roots = [...byId.values()].filter(item => !childIds.has(item.id));
  roots.sort((a, b) => (a.source === "lcsc" ? -1 : 1) - (b.source === "lcsc" ? -1 : 1));
  return { byId, roots };
}

function aggregateCounts(node, trail = new Set()) {
  if (trail.has(node.id)) return { materials: 0, stock: 0, low: 0 };
  const nextTrail = new Set(trail).add(node.id);
  const total = {
    materials: Number(node.material_count || 0),
    stock: Number(node.stock_quantity || 0),
    low: Number(node.low_stock_count || 0),
  };
  for (const child of node.children) {
    const childTotal = aggregateCounts(child, nextTrail);
    total.materials += childTotal.materials;
    total.stock += childTotal.stock;
    total.low += childTotal.low;
  }
  node.total = total;
  return total;
}

function renderCategoryTree() {
  const container = $("#categoryTree");
  const search = $("#categorySearch").value.trim().toLowerCase();
  const { roots } = categoryGraph();
  roots.forEach(root => aggregateCounts(root));
  let html = `<div class="tree-row ${state.categoryId === null ? "active" : ""}" data-category="all">
    <button class="tree-toggle invisible">›</button><button class="tree-label">全部物料</button>
    <span class="tree-count">${esc($("#materialCount").textContent || "")}</span></div>`;

  function nodeHtml(node, depth, trail = new Set()) {
    if (trail.has(node.id)) return "";
    const nextTrail = new Set(trail).add(node.id);
    if (search) {
      const descendantsMatch = node.children.some(child => containsMatch(child, search));
      if (!node.name.toLowerCase().includes(search) && !descendantsMatch) return "";
    }
    const children = node.children.map(child => nodeHtml(child, depth + 1, nextTrail)).join("");
    const hasChildren = node.children.length > 0;
    const expanded = state.expanded.has(node.id) || Boolean(search);
    return `<div class="tree-node">
      <div class="tree-row ${state.categoryId === node.id ? "active" : ""}" data-category="${node.id}" style="padding-left:${Math.min(depth, 3) * 13}px">
        <button class="tree-toggle ${hasChildren ? "" : "invisible"}" data-toggle="${node.id}">${expanded ? "⌄" : "›"}</button>
        <button class="tree-label" title="${esc(node.name)}">${esc(node.name)}</button>
        <span class="tree-count">${number(node.total?.materials || 0)}</span>
      </div>
      <div class="tree-children ${expanded ? "" : "collapsed"}">${children}</div>
    </div>`;
  }

  function containsMatch(node, value, trail = new Set()) {
    if (trail.has(node.id)) return false;
    const nextTrail = new Set(trail).add(node.id);
    return node.name.toLowerCase().includes(value) || node.children.some(child => containsMatch(child, value, nextTrail));
  }

  html += roots.map(root => nodeHtml(root, 0)).join("");
  container.innerHTML = html;
  $$(".tree-row", container).forEach(row => row.addEventListener("click", event => {
    if (event.target.closest("[data-toggle]")) return;
    const value = row.dataset.category;
    if (value === "all") {
      state.categoryId = null;
      state.categoryName = "全部物料";
    } else {
      state.categoryId = Number(value);
      state.categoryName = state.categories.find(item => item.id === state.categoryId)?.name || "分类物料";
    }
    updateMaterialHeading();
    renderCategoryTree();
    loadMaterials();
  }));
  $$('[data-toggle]', container).forEach(button => button.addEventListener("click", event => {
    event.stopPropagation();
    const id = Number(button.dataset.toggle);
    state.expanded.has(id) ? state.expanded.delete(id) : state.expanded.add(id);
    renderCategoryTree();
  }));
}

function categoryPaths() {
  const { byId } = categoryGraph();
  const parents = new Map();
  for (const relation of state.relations) {
    if (!parents.has(relation.child_id)) parents.set(relation.child_id, relation.parent_id);
  }
  function pathFor(item) {
    const names = [item.name];
    const visited = new Set([item.id]);
    let parentId = parents.get(item.id);
    while (parentId && !visited.has(parentId)) {
      visited.add(parentId);
      const parent = byId.get(parentId);
      if (!parent) break;
      names.unshift(parent.name);
      parentId = parents.get(parent.id);
    }
    return names.join(" / ");
  }
  return state.categories
    .filter(item => item.external_id !== "1")
    .map(item => ({ ...item, path: pathFor(item) }))
    .sort((a, b) => a.path.localeCompare(b.path, "zh-CN"));
}

function renderCategoryOptions() {
  const options = categoryPaths().map(item => `<option value="${item.id}">${esc(item.path)}</option>`).join("");
  $("#manualCategory").innerHTML = `<option value="">未分类</option>${options}`;
  const locationOptions = state.locations.map(location => `<option value="${location.id}">${esc(location.name)}</option>`).join("");
  $("#manualLocation").innerHTML = `<option value="">使用默认仓位</option>${locationOptions}`;
}

function updateMaterialHeading() {
  $("#pageTitle").textContent = state.categoryName;
  $("#tableTitle").textContent = state.categoryName;
}

async function loadMaterials() {
  const params = new URLSearchParams();
  if (state.query) params.set("q", state.query);
  if (state.categoryId) params.set("category_id", state.categoryId);
  if (state.lowStock) params.set("low_stock", "1");
  const materials = await api(`/api/materials?${params}`);
  const body = $("#materialsBody");
  $("#resultCount").textContent = `共 ${materials.length} 种`;
  body.innerHTML = materials.map(item => {
    const low = Number(item.stock) <= Number(item.min_stock);
    const thumb = item.image_url
      ? `<img class="material-thumb" src="${esc(item.image_url)}" alt="" referrerpolicy="no-referrer">`
      : `<span class="material-thumb material-placeholder">${esc((item.name || "M")[0])}</span>`;
    return `<tr data-material-id="${item.id}">
      <td><div class="material-cell">${thumb}<span><span class="cell-title">${esc(item.name)}</span><span class="cell-subtitle">${esc(item.brand || item.internal_code)}</span></span></div></td>
      <td><span class="cell-title">${esc(item.manufacturer_part || "—")}</span><span class="sku">${esc(item.supplier_sku || "")}</span></td>
      <td>${item.category_name ? `<span class="category-pill">${esc(item.category_name)}</span>` : "—"}</td>
      <td>${esc(item.package || "—")}</td>
      <td>${esc(item.primary_location || "—")}</td>
      <td class="number"><span class="stock-value ${low ? "stock-low" : ""}">${number(item.stock)}</span> <small>${esc(item.unit)}</small></td>
      <td><button class="row-action" aria-label="查看详情">›</button></td>
    </tr>`;
  }).join("");
  $("#materialsEmpty").classList.toggle("hidden", materials.length > 0);
  $$('[data-material-id]', body).forEach(row => row.addEventListener("click", () => openDetail(Number(row.dataset.materialId))));
}

async function loadTransactions() {
  const items = await api("/api/transactions?limit=200");
  const labels = { initial: "初始入库", inbound: "入库", outbound: "出库", adjust: "调整", reversal: "撤销" };
  $("#transactionsBody").innerHTML = items.map(item => `<tr data-material-id="${item.material_id}">
    <td>${esc(dateTime(item.created_at))}</td><td><span class="cell-title">${esc(item.name)}</span><span class="cell-subtitle">${esc(item.manufacturer_part || item.internal_code)}</span></td>
    <td>${labels[item.kind] || esc(item.kind)}</td><td>${esc(item.location_name)}</td>
    <td class="number ${Number(item.quantity_delta) >= 0 ? "delta-plus" : "delta-minus"}">${Number(item.quantity_delta) >= 0 ? "+" : ""}${number(item.quantity_delta)}</td>
    <td>${esc(item.note || "—")}</td></tr>`).join("");
  $$('[data-material-id]', $("#transactionsBody")).forEach(row => row.addEventListener("click", () => openDetail(Number(row.dataset.materialId))));
}

async function openDetail(id) {
  try {
    const item = await api(`/api/materials/${id}`);
    const supplier = item.suppliers[0];
    const specs = Object.entries(item.specs || {}).slice(0, 30);
    const image = item.image_url
      ? `<img class="detail-image" src="${esc(item.image_url)}" alt="" referrerpolicy="no-referrer">`
      : `<div class="detail-image material-placeholder">${esc((item.name || "M")[0])}</div>`;
    const locationOptions = state.locations.map(location => `<option value="${location.id}">${esc(location.name)}</option>`).join("");
    const labels = { initial: "初始入库", inbound: "入库", outbound: "出库", adjust: "调整", reversal: "撤销" };
    $("#detailContent").innerHTML = `
      <div class="modal-header"><div><h2>物料详情</h2><p>${esc(item.internal_code)}</p></div><button type="button" class="icon-button" id="closeDetail">×</button></div>
      <div class="detail-hero">${image}<div><h2>${esc(item.name)}</h2>
        <div class="detail-meta"><span>型号：${esc(item.manufacturer_part || "—")}</span><span>品牌：${esc(item.brand || "—")}</span><span>封装：${esc(item.package || "—")}</span>${supplier ? `<span class="sku">${esc(supplier.supplier_sku)}</span>` : ""}</div>
        <div class="detail-stock"><strong>${number(item.stock)}</strong>${esc(item.unit)} · ${item.locations.map(loc => `${esc(loc.name)} ${number(loc.quantity)}`).join("，") || "暂无仓位库存"}</div>
        <div class="detail-links">${supplier?.product_url ? `<a href="${esc(supplier.product_url)}" target="_blank">立创商品页 ↗</a>` : ""}${item.datasheet_url ? `<a href="${esc(item.datasheet_url)}" target="_blank">数据手册 ↗</a>` : ""}</div>
      </div></div>
      <div class="detail-sections">
        <section class="detail-section"><h3>库存操作</h3><form id="stockForm" class="stock-form">
          <select name="kind"><option value="inbound">入库</option><option value="outbound">出库</option><option value="adjust">调整</option></select>
          <input name="quantity" type="number" step="any" placeholder="数量" required>
          <select name="location_id">${locationOptions}</select><input name="note" placeholder="备注（可选）"><button class="button primary">确认</button>
        </form></section>
        ${specs.length ? `<section class="detail-section"><h3>规格参数</h3><div class="spec-grid">${specs.map(([key, value]) => `<div class="spec-item"><small>${esc(key)}</small><span>${esc(value)}</span></div>`).join("")}</div></section>` : ""}
        <section class="detail-section"><h3>最近流水</h3><div class="mini-transactions">${item.transactions.slice(0, 10).map(tx => `<div class="mini-transaction"><span>${esc(dateTime(tx.created_at))}</span><span>${esc(labels[tx.kind] || tx.kind)}</span><span>${esc(tx.location_name)}</span><span class="${Number(tx.quantity_delta) >= 0 ? "delta-plus" : "delta-minus"}">${Number(tx.quantity_delta) >= 0 ? "+" : ""}${number(tx.quantity_delta)}</span></div>`).join("")}</div></section>
      </div>`;
    const dialog = $("#detailDialog");
    dialog.showModal();
    $("#closeDetail").addEventListener("click", () => dialog.close());
    $("#stockForm").addEventListener("submit", async event => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      const payload = Object.fromEntries(form.entries());
      payload.quantity = Number(payload.quantity);
      payload.location_id = Number(payload.location_id);
      try {
        await api(`/api/materials/${id}/stock`, { method: "POST", body: payload });
        toast("库存操作已保存");
        dialog.close();
        await Promise.all([loadMaterials(), loadDashboard()]);
        if (state.view === "transactions") loadTransactions();
      } catch (error) { toast(error.message, true); }
    });
  } catch (error) { toast(error.message, true); }
}

function renderSettings() {
  $("#defaultQuantity").value = state.settings.default_quantity ?? 1;
  $("#defaultLocation").innerHTML = state.locations.map(location => `<option value="${location.id}" ${location.id === state.settings.default_location_id ? "selected" : ""}>${esc(location.name)}</option>`).join("");
  $("#extensionToken").value = state.settings.extension_token || "";
  $("#lastCategorySync").textContent = state.settings.last_category_sync ? dateTime(state.settings.last_category_sync) : "尚未同步";
  $("#locationTags").innerHTML = state.locations.map(location => `<span class="tag">${esc(location.name)}</span>`).join("");
}

function showView(view) {
  state.view = view;
  $$(".nav-item").forEach(item => item.classList.toggle("active", item.dataset.view === view));
  $$(".view").forEach(item => item.classList.remove("active"));
  $(`#${view}View`).classList.add("active");
  const data = {
    materials: [state.categoryName, "管理你手头的电子元器件"],
    transactions: ["库存流水", "所有数量变化都有记录"],
    settings: ["系统设置", "默认值、仓位、分类同步与扩展连接"],
  }[view];
  $("#pageTitle").textContent = data[0];
  $("#pageSubtitle").textContent = data[1];
  $("#materialSearch").parentElement.classList.toggle("hidden", view !== "materials");
  $("#addMaterialButton").classList.toggle("hidden", view !== "materials");
  if (view === "transactions") loadTransactions();
}

function bindEvents() {
  $$(".nav-item").forEach(item => item.addEventListener("click", () => showView(item.dataset.view)));
  $("#addMaterialButton").addEventListener("click", () => $("#manualDialog").showModal());
  $$(".close-dialog").forEach(button => button.addEventListener("click", () => button.closest("dialog").close()));
  $("#manualForm").addEventListener("submit", async event => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    const form = new FormData(event.currentTarget);
    const imageFile = form.get("image");
    const payload = Object.fromEntries([...form.entries()].filter(([, value]) => value !== "" && !(value instanceof File)));
    for (const key of ["quantity", "min_stock", "category_id", "location_id"]) {
      if (key in payload) payload[key] = Number(payload[key]);
    }
    if (payload.source) payload.notes = `${payload.notes ? `${payload.notes}；` : ""}来源：${payload.source}`;
    try {
      const created = await api("/api/materials/manual", { method: "POST", body: payload });
      let imageError = "";
      if (imageFile instanceof File && imageFile.size) {
        try { await window.uploadMaterialImage(created.id, imageFile); }
        catch (error) { imageError = error.message; }
      }
      event.currentTarget.reset();
      $("#manualDialog").close();
      toast(imageError ? `物料已添加，但图片失败：${imageError}` : "物料已添加并入库", Boolean(imageError));
      await Promise.all([loadMaterials(), loadDashboard()]);
      const categories = await api("/api/categories");
      state.categories = categories.categories; state.relations = categories.relations; renderCategoryTree();
    } catch (error) { toast(error.message, true); }
    finally { button.disabled = false; }
  });
  let searchTimer;
  $("#materialSearch").addEventListener("input", event => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => { state.query = event.target.value.trim(); loadMaterials(); }, 250);
  });
  $("#categorySearch").addEventListener("input", renderCategoryTree);
  $("#lowStockOnly").addEventListener("change", event => { state.lowStock = event.target.checked; loadMaterials(); });
  $("#lowStockStat").addEventListener("click", () => { state.lowStock = true; $("#lowStockOnly").checked = true; showView("materials"); loadMaterials(); });
  $("#allStat").addEventListener("click", () => { state.categoryId = null; state.categoryName = "全部物料"; state.lowStock = false; $("#lowStockOnly").checked = false; showView("materials"); loadMaterials(); renderCategoryTree(); });
  $("#refreshCategories").addEventListener("click", async () => {
    const data = await api("/api/categories"); state.categories = data.categories; state.relations = data.relations; renderCategoryTree(); renderCategoryOptions();
  });
  $("#settingsForm").addEventListener("submit", async event => {
    event.preventDefault();
    try {
      state.settings = await api("/api/settings", { method: "PUT", body: { default_quantity: Number($("#defaultQuantity").value), default_location_id: Number($("#defaultLocation").value) } });
      renderSettings(); toast("默认设置已保存");
    } catch (error) { toast(error.message, true); }
  });
  $("#locationForm").addEventListener("submit", async event => {
    event.preventDefault();
    try {
      await api("/api/locations", { method: "POST", body: { name: $("#newLocationName").value } });
      $("#newLocationName").value = ""; state.locations = await api("/api/locations"); renderSettings(); renderCategoryOptions(); toast("仓位已添加");
    } catch (error) { toast(error.message, true); }
  });
  $("#syncCategoriesButton").addEventListener("click", async event => {
    const button = event.currentTarget; button.disabled = true; button.textContent = "正在同步…";
    try {
      const result = await api("/api/categories/sync", { method: "POST", body: {} });
      const data = await api("/api/categories"); state.categories = data.categories; state.relations = data.relations;
      state.settings = await api("/api/settings"); renderSettings(); renderCategoryTree(); renderCategoryOptions();
      toast(`已同步 ${result.categories} 个立创分类`);
    } catch (error) { toast(error.message, true); }
    finally { button.disabled = false; button.textContent = "同步立创分类"; }
  });
  $("#copyToken").addEventListener("click", async () => {
    await navigator.clipboard.writeText($("#extensionToken").value); toast("连接密钥已复制");
  });
  for (const id of ["exportButton", "settingsExportButton"]) $("#" + id).addEventListener("click", () => { location.href = "/api/export.csv"; });
  $("#manualDialog").addEventListener("click", event => { if (event.target === event.currentTarget) event.currentTarget.close(); });
  $("#detailDialog").addEventListener("click", event => { if (event.target === event.currentTarget) event.currentTarget.close(); });
}

bindEvents();
loadBootstrap();
