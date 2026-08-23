(() => {
  if (window.__inventoryManagementInstalled) return;
  window.__inventoryManagementInstalled = true;

  const transactionLabels = {
    initial: "初始入库",
    inbound: "入库",
    outbound: "出库",
    adjust: "调整",
    reversal: "撤销",
  };
  const baseOpenDetail = openDetail;
  let currentDetailId = null;
  let managerMaterialId = null;
  let changeToken = null;
  let polling = false;

  function quantityHtml(transaction) {
    const value = Number(transaction.quantity_delta);
    const sign = value >= 0 ? "+" : "";
    const className = value >= 0 ? "delta-plus" : "delta-minus";
    return `<span class="${className}">${sign}${number(value)}</span>`;
  }

  async function refreshVisibleData() {
    await Promise.all([loadDashboard(), loadMaterials()]);
    if (state.view === "transactions") await loadTransactions();
  }

  loadTransactions = async function managedLoadTransactions() {
    const items = await api("/api/transactions?limit=200");
    const body = $("#transactionsBody");
    body.innerHTML = items.length
      ? items.map(item => `<tr data-material-id="${item.material_id}">
          <td>${esc(dateTime(item.created_at))}</td>
          <td><span class="cell-title">${esc(item.name)}</span><span class="cell-subtitle">${esc(item.manufacturer_part || item.internal_code)}</span></td>
          <td>${esc(transactionLabels[item.kind] || item.kind)}</td>
          <td>${esc(item.location_name)}</td>
          <td class="number">${quantityHtml(item)}</td>
          <td class="transaction-note" title="${esc(item.note || "")}">${esc(item.note || "—")}</td>
        </tr>`).join("")
      : `<tr><td colspan="6" class="managed-empty">暂无显示中的流水，可在“管理流水”中恢复已归档记录。</td></tr>`;
    $$('[data-material-id]', body).forEach(row => row.addEventListener("click", () => {
      openDetail(Number(row.dataset.materialId));
    }));
  };

  function recentTransactionsHtml(item) {
    if (!item.transactions.length) {
      return `<div class="managed-empty">暂无显示中的流水，可点击“管理流水”恢复已归档记录。</div>`;
    }
    return item.transactions.slice(0, 10).map(transaction => `
      <div class="managed-mini-transaction">
        <span>${esc(dateTime(transaction.created_at))}</span>
        <span>${esc(transactionLabels[transaction.kind] || transaction.kind)}</span>
        <span>${esc(transaction.location_name)}</span>
        ${quantityHtml(transaction)}
        <span class="managed-mini-note" title="${esc(transaction.note || "")}">备注：${esc(transaction.note || "无")}</span>
      </div>`).join("");
  }

  function enhanceDetail(item) {
    const sections = $("#detailContent .detail-sections");
    if (!sections) return;

    if (item.description) {
      const description = document.createElement("section");
      description.className = "detail-section material-description-section";
      description.innerHTML = `<h3>商品描述</h3><p>${esc(item.description)}</p>`;
      sections.prepend(description);
    }

    const recentHeading = [...sections.querySelectorAll("h3")]
      .find(heading => heading.textContent.trim() === "最近流水");
    const recentSection = recentHeading?.closest(".detail-section");
    if (!recentSection) return;
    recentSection.innerHTML = `
      <div class="managed-section-heading">
        <h3>最近流水</h3>
        <div>
          <button type="button" class="button ghost compact" data-detail-action="manage">管理流水</button>
          <button type="button" class="button danger compact" data-detail-action="clear">清空流水</button>
        </div>
      </div>
      <div class="managed-mini-transactions">${recentTransactionsHtml(item)}</div>`;
    recentSection.querySelector("[data-detail-action='manage']").addEventListener("click", () => {
      openTransactionManager(item.id);
    });
    recentSection.querySelector("[data-detail-action='clear']").addEventListener("click", async () => {
      if (!confirm("清空后流水会从列表隐藏，但不会改变当前库存，并可在管理流水中恢复。确定继续吗？")) return;
      const result = await api(`/api/materials/${item.id}/transactions/clear`, {
        method: "POST", body: {},
      });
      toast(`已清空 ${result.archived_count} 条流水，库存保持不变`);
      await refreshVisibleData();
      $("#detailDialog").close();
      await openDetail(item.id);
    });
  }

  openDetail = async function managedOpenDetail(id) {
    currentDetailId = Number(id);
    const detailRequest = api(`/api/materials/${id}`);
    await baseOpenDetail(id);
    try {
      enhanceDetail(await detailRequest);
    } catch (error) {
      toast(error.message, true);
    }
  };

  const manager = document.createElement("dialog");
  manager.id = "transactionManager";
  manager.className = "modal transaction-manager";
  document.body.append(manager);

  async function renderTransactionManager() {
    const query = new URLSearchParams({ limit: "500", include_archived: "1" });
    if (managerMaterialId != null) query.set("material_id", String(managerMaterialId));
    const items = await api(`/api/transactions?${query}`);
    const title = managerMaterialId == null ? "管理全部库存流水" : "管理该物料流水";
    manager.innerHTML = `
      <div class="modal-header">
        <div><h2>${title}</h2><p>可编辑备注、隐藏或恢复流水；隐藏不会改变库存。</p></div>
        <button type="button" class="icon-button" data-manager-action="close">×</button>
      </div>
      <div class="transaction-manager-actions">
        <span>共 ${items.length} 条（含已隐藏）</span>
        <button type="button" class="button danger compact" data-manager-action="clear">${managerMaterialId == null ? "清空全部显示流水" : "清空该物料流水"}</button>
      </div>
      <div class="transaction-manager-list">
        ${items.length ? items.map(transaction => `
          <article class="transaction-manager-item ${transaction.archived ? "archived" : ""}" data-transaction-id="${transaction.id}">
            <div class="transaction-manager-summary">
              <span>${esc(dateTime(transaction.created_at))}</span>
              <strong>${esc(transaction.name)}</strong>
              <span>${esc(transactionLabels[transaction.kind] || transaction.kind)} · ${esc(transaction.location_name)}</span>
              ${quantityHtml(transaction)}
              <em>${transaction.archived ? "已隐藏" : "显示中"}</em>
            </div>
            <div class="transaction-manager-editor">
              <input data-note value="${esc(transaction.note || "")}" placeholder="填写流水备注">
              <button type="button" class="button secondary compact" data-manager-action="save">保存备注</button>
              <button type="button" class="button ghost compact" data-manager-action="toggle" data-archived="${transaction.archived ? "1" : "0"}">${transaction.archived ? "恢复显示" : "隐藏流水"}</button>
            </div>
          </article>`).join("") : `<div class="managed-empty">还没有库存流水。</div>`}
      </div>`;
  }

  async function openTransactionManager(materialId = null) {
    managerMaterialId = materialId == null ? null : Number(materialId);
    manager.dataset.materialId = managerMaterialId == null ? "" : String(managerMaterialId);
    await renderTransactionManager();
    if (!manager.open) manager.showModal();
  }

  manager.addEventListener("click", async event => {
    if (event.target === manager) { manager.close(); return; }
    const actionButton = event.target.closest?.("[data-manager-action]");
    if (!actionButton) return;
    const action = actionButton.dataset.managerAction;
    if (action === "close") { manager.close(); return; }
    if (action === "clear") {
      const scope = managerMaterialId == null ? "全部" : "该物料";
      if (!confirm(`确定清空${scope}显示中的流水吗？库存不会改变，之后仍可恢复。`)) return;
      const path = managerMaterialId == null
        ? "/api/transactions/clear"
        : `/api/materials/${managerMaterialId}/transactions/clear`;
      const result = await api(path, { method: "POST", body: {} });
      toast(`已清空 ${result.archived_count} 条流水，库存保持不变`);
      await Promise.all([renderTransactionManager(), refreshVisibleData()]);
      return;
    }
    const item = actionButton.closest("[data-transaction-id]");
    const transactionId = Number(item.dataset.transactionId);
    if (action === "save") {
      await api(`/api/transactions/${transactionId}`, {
        method: "PUT", body: { note: item.querySelector("[data-note]").value },
      });
      toast("流水备注已保存");
    }
    if (action === "toggle") {
      await api(`/api/transactions/${transactionId}`, {
        method: "PUT", body: { archived: actionButton.dataset.archived !== "1" },
      });
      toast(actionButton.dataset.archived === "1" ? "流水已恢复显示" : "流水已隐藏");
    }
    await Promise.all([renderTransactionManager(), refreshVisibleData()]);
  });

  manager.addEventListener("close", async () => {
    const materialId = managerMaterialId;
    managerMaterialId = null;
    if (materialId != null && $("#detailDialog").open) {
      $("#detailDialog").close();
      await openDetail(materialId);
    }
  });

  const transactionsHeader = $("#transactionsView .panel-header");
  const globalManagerButton = document.createElement("button");
  globalManagerButton.type = "button";
  globalManagerButton.className = "button secondary compact transaction-global-manage";
  globalManagerButton.textContent = "管理流水";
  globalManagerButton.addEventListener("click", () => openTransactionManager());
  transactionsHeader.append(globalManagerButton);

  const manualDescription = document.createElement("label");
  manualDescription.className = "wide";
  manualDescription.innerHTML = `物料描述<textarea name="description" rows="3" placeholder="手动物料可以填写用途、参数摘要或采购说明"></textarea>`;
  $("#manualForm .form-grid").append(manualDescription);

  async function pollChanges() {
    if (polling) return;
    polling = true;
    try {
      const changes = await api("/api/changes");
      if (changeToken !== null && changes.token !== changeToken) {
        changeToken = changes.token;
        await refreshVisibleData();
        if (currentDetailId != null && $("#detailDialog").open && !manager.open) {
          $("#detailDialog").close();
          await openDetail(currentDetailId);
        }
      } else {
        changeToken = changes.token;
      }
    } catch {
      // The next poll retries automatically when the local server is available again.
    } finally {
      polling = false;
    }
  }

  pollChanges();
  setInterval(pollChanges, 750);
})();
