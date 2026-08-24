(() => {
  if (window.__materialManagementInstalled) return;
  window.__materialManagementInstalled = true;

  const body = document.querySelector("#materialsBody");
  const panel = document.querySelector("#materialsView .material-panel");
  const header = panel?.querySelector(".panel-header");
  const headingRow = panel?.querySelector("thead tr");
  if (!body || !header || !headingRow) return;

  let bulkMode = false;
  const selectedIds = new Set();
  const latestMaterials = new Map();

  const selectHeading = document.createElement("th");
  selectHeading.className = "material-select-column hidden";
  selectHeading.innerHTML = `<input id="selectAllMaterials" type="checkbox" aria-label="选择当前列表全部物料">`;
  headingRow.prepend(selectHeading);
  headingRow.lastElementChild.textContent = "操作";
  headingRow.lastElementChild.classList.add("material-actions-heading");

  const controls = document.createElement("div");
  controls.className = "material-bulk-controls";
  controls.innerHTML = `
    <button id="materialBulkModeButton" class="button secondary compact" type="button">批量管理</button>
    <div id="materialBulkBar" class="material-bulk-bar hidden">
      <strong id="materialSelectedCount">已选 0 项</strong>
      <button id="deleteSelectedMaterials" class="button danger compact" type="button" disabled>删除选中</button>
      <button id="exitMaterialBulkMode" class="button ghost compact" type="button">退出</button>
    </div>`;
  header.append(controls);

  const bulkButton = controls.querySelector("#materialBulkModeButton");
  const bulkBar = controls.querySelector("#materialBulkBar");
  const selectedCount = controls.querySelector("#materialSelectedCount");
  const deleteSelected = controls.querySelector("#deleteSelectedMaterials");
  const exitBulk = controls.querySelector("#exitMaterialBulkMode");
  const selectAll = selectHeading.querySelector("#selectAllMaterials");

  function updateBulkControls() {
    const visibleIds = [...latestMaterials.keys()];
    const visibleSelected = visibleIds.filter(id => selectedIds.has(id));
    selectedCount.textContent = `已选 ${selectedIds.size} 项`;
    deleteSelected.disabled = selectedIds.size === 0;
    selectAll.checked = visibleIds.length > 0 && visibleSelected.length === visibleIds.length;
    selectAll.indeterminate = visibleSelected.length > 0 && visibleSelected.length < visibleIds.length;
  }

  function setBulkMode(enabled) {
    bulkMode = enabled;
    if (!enabled) selectedIds.clear();
    bulkButton.classList.toggle("hidden", enabled);
    bulkBar.classList.toggle("hidden", !enabled);
    selectHeading.classList.toggle("hidden", !enabled);
    document.querySelector("#materialsView .material-panel")?.classList.toggle("bulk-mode", enabled);
    loadMaterials();
  }

  loadMaterials = async function managedLoadMaterials() {
    const params = new URLSearchParams();
    if (state.query) params.set("q", state.query);
    if (state.categoryId) params.set("category_id", state.categoryId);
    if (state.lowStock) params.set("low_stock", "1");
    const materials = await api(`/api/materials?${params}`);
    latestMaterials.clear();
    materials.forEach(item => latestMaterials.set(Number(item.id), item));
    for (const id of [...selectedIds]) {
      if (!latestMaterials.has(id)) selectedIds.delete(id);
    }
    document.querySelector("#resultCount").textContent = `共 ${materials.length} 种`;
    body.innerHTML = materials.map(item => {
      const low = Number(item.stock) <= Number(item.min_stock);
      const thumb = item.image_url
        ? `<img class="material-thumb" src="${esc(item.image_url)}" alt="" referrerpolicy="no-referrer">`
        : `<span class="material-thumb material-placeholder">${esc((item.name || "M")[0])}</span>`;
      return `<tr data-material-id="${item.id}">
        <td class="material-select-cell ${bulkMode ? "" : "hidden"}"><input type="checkbox" data-material-select="${item.id}" ${selectedIds.has(Number(item.id)) ? "checked" : ""} aria-label="选择 ${esc(item.name)}"></td>
        <td><div class="material-cell">${thumb}<span><span class="cell-title">${esc(item.name)}</span><span class="cell-subtitle">${esc(item.brand || item.internal_code)}</span></span></div></td>
        <td><span class="cell-title">${esc(item.manufacturer_part || "—")}</span><span class="sku">${esc(item.supplier_sku || "")}</span></td>
        <td>${item.category_name ? `<span class="category-pill">${esc(item.category_name)}</span>` : "—"}</td>
        <td>${esc(item.package || "—")}</td>
        <td>${esc(item.primary_location || "—")}</td>
        <td class="number"><span class="stock-value ${low ? "stock-low" : ""}">${number(item.stock)}</span> <small>${esc(item.unit)}</small></td>
        <td class="material-row-actions">
          <button class="row-action material-view-action" data-material-action="view" type="button" aria-label="查看详情">›</button>
          <button class="material-delete-action" data-material-action="delete" type="button">删除</button>
        </td>
      </tr>`;
    }).join("");
    document.querySelector("#materialsEmpty").classList.toggle("hidden", materials.length > 0);
    updateBulkControls();
  };

  async function refreshAfterChange() {
    const [categories] = await Promise.all([api("/api/categories"), loadDashboard()]);
    state.categories = categories.categories;
    state.relations = categories.relations;
    renderCategoryTree();
    renderCategoryOptions();
    await loadMaterials();
  }

  async function deleteMaterials(ids) {
    const items = ids.map(id => latestMaterials.get(id)).filter(Boolean);
    const names = items.slice(0, 3).map(item => item.name).join("、");
    const suffix = items.length > 3 ? ` 等 ${items.length} 种物料` : "";
    const operation = ids.length > 1 ? "material_batch_delete" : "material_single_delete";
    const safetyMessage = window.autoSafetyBackupMessage?.(operation) || "系统会先自动生成安全备份。";
    if (!confirm(
      `确定删除 ${names}${suffix} 吗？\n\n物料档案、库存和该物料全部流水都会删除。${safetyMessage}`
    )) return;
    const result = await api("/api/materials/delete-batch", {
      method: "POST",
      body: { material_ids: ids },
    });
    ids.forEach(id => selectedIds.delete(id));
    toast(result.safety_backup
      ? `已删除 ${result.deleted_count} 种物料，删除前数据已自动备份`
      : `已删除 ${result.deleted_count} 种物料，本次未生成自动安全备份`);
    await refreshAfterChange();
  }

  body.addEventListener("click", event => {
    const row = event.target.closest("[data-material-id]");
    if (!row) return;
    const id = Number(row.dataset.materialId);
    const action = event.target.closest("[data-material-action]")?.dataset.materialAction;
    if (action === "delete") {
      event.stopPropagation();
      deleteMaterials([id]).catch(error => toast(error.message, true));
      return;
    }
    if (action === "view") {
      event.stopPropagation();
      openDetail(id);
      return;
    }
    const checkbox = event.target.closest("[data-material-select]");
    if (checkbox) {
      checkbox.checked ? selectedIds.add(id) : selectedIds.delete(id);
      updateBulkControls();
      return;
    }
    if (bulkMode) {
      const input = row.querySelector("[data-material-select]");
      input.checked = !input.checked;
      input.checked ? selectedIds.add(id) : selectedIds.delete(id);
      updateBulkControls();
    } else {
      openDetail(id);
    }
  });

  bulkButton.addEventListener("click", () => setBulkMode(true));
  exitBulk.addEventListener("click", () => setBulkMode(false));
  deleteSelected.addEventListener("click", () => {
    deleteMaterials([...selectedIds]).catch(error => toast(error.message, true));
  });
  selectAll.addEventListener("change", () => {
    for (const id of latestMaterials.keys()) {
      selectAll.checked ? selectedIds.add(id) : selectedIds.delete(id);
    }
    body.querySelectorAll("[data-material-select]").forEach(input => {
      input.checked = selectAll.checked;
    });
    updateBulkControls();
  });

  window.uploadMaterialImage = async function uploadMaterialImage(materialId, file) {
    const response = await fetch(`/api/materials/${materialId}/image`, {
      method: "POST",
      headers: { "Content-Type": file.type || "application/octet-stream" },
      body: file,
    });
    let result;
    try { result = await response.json(); }
    catch (_) { result = {}; }
    if (!response.ok) throw new Error(result.error || "图片上传失败");
    return result;
  };

  const editDialog = document.createElement("dialog");
  editDialog.id = "materialEditDialog";
  editDialog.className = "modal material-edit-dialog";
  document.body.append(editDialog);

  function categoryOptionHtml(selectedId) {
    return `<option value="">未分类</option>${categoryPaths().map(category =>
      `<option value="${category.id}" ${Number(selectedId) === Number(category.id) ? "selected" : ""}>${esc(category.path)}</option>`
    ).join("")}`;
  }

  async function openMaterialEditor(item) {
    const primaryCategory = item.categories.find(category => category.is_primary);
    editDialog.innerHTML = `
      <form id="materialEditForm">
        <div class="modal-header"><div><h2>修改物料详情</h2><p>${esc(item.internal_code)} · 非立创来源物料</p></div><button type="button" class="icon-button" data-edit-close>×</button></div>
        <div class="form-grid material-edit-grid">
          <label class="wide">物料名称<input name="name" value="${esc(item.name)}" required></label>
          <label>制造商型号<input name="manufacturer_part" value="${esc(item.manufacturer_part)}"></label>
          <label>品牌<input name="brand" value="${esc(item.brand)}"></label>
          <label>封装<input name="package" value="${esc(item.package)}"></label>
          <label>单位<select name="unit">${["个","片","只","米","卷","盒"].map(unit => `<option ${item.unit === unit ? "selected" : ""}>${unit}</option>`).join("")}</select></label>
          <label>最低库存<input name="min_stock" type="number" min="0" step="any" value="${esc(item.min_stock)}"></label>
          <label class="wide">分类<select name="category_id">${categoryOptionHtml(primaryCategory?.id)}</select></label>
          <label class="wide">物料描述<textarea name="description" rows="3">${esc(item.description)}</textarea></label>
          <label class="wide">元器件备注<textarea name="notes" rows="3" placeholder="长期保存在元器件档案中的备注">${esc(item.notes)}</textarea></label>
          <label class="wide material-image-input">更换物料图片<input name="image" type="file" accept="image/jpeg,image/png,image/webp,image/gif"><small>支持 JPG、PNG、WEBP、GIF，最大 8MB；不选择则保留原图。</small></label>
        </div>
        <div class="modal-actions"><button type="button" class="button ghost" data-edit-close>取消</button><button class="button primary" type="submit">保存修改</button></div>
      </form>`;
    editDialog.querySelectorAll("[data-edit-close]").forEach(button => {
      button.addEventListener("click", () => editDialog.close());
    });
    editDialog.querySelector("#materialEditForm").addEventListener("submit", async event => {
      event.preventDefault();
      const submit = event.submitter;
      submit.disabled = true;
      const form = new FormData(event.currentTarget);
      const imageFile = form.get("image");
      const payload = Object.fromEntries([...form.entries()].filter(([, value]) => !(value instanceof File)));
      payload.min_stock = Number(payload.min_stock || 0);
      payload.category_id = payload.category_id ? Number(payload.category_id) : null;
      try {
        await api(`/api/materials/${item.id}`, { method: "PUT", body: payload });
        if (imageFile instanceof File && imageFile.size) {
          await window.uploadMaterialImage(item.id, imageFile);
        }
        editDialog.close();
        document.querySelector("#detailDialog")?.close();
        await refreshAfterChange();
        toast("物料详情已保存");
        await openDetail(item.id);
      } catch (error) {
        toast(error.message, true);
      } finally {
        submit.disabled = false;
      }
    });
    editDialog.showModal();
  }

  const baseOpenDetail = openDetail;
  openDetail = async function materialManagedOpenDetail(id) {
    const detailRequest = api(`/api/materials/${id}`);
    await baseOpenDetail(id);
    try {
      const item = await detailRequest;
      const content = document.querySelector("#detailContent");
      const sections = content?.querySelector(".detail-sections");
      if (sections && item.notes) {
        const notes = document.createElement("section");
        notes.className = "detail-section material-notes-section";
        notes.innerHTML = `<h3>元器件备注</h3><p>${esc(item.notes)}</p>`;
        sections.prepend(notes);
      }
      if (content && item.editable) {
        const headerActions = content.querySelector(".modal-header");
        const closeButton = headerActions?.querySelector("#closeDetail");
        if (headerActions && closeButton && !headerActions.querySelector("[data-edit-material]")) {
          const editButton = document.createElement("button");
          editButton.type = "button";
          editButton.className = "button secondary compact detail-edit-material";
          editButton.dataset.editMaterial = "";
          editButton.textContent = "修改物料详情";
          editButton.addEventListener("click", () => openMaterialEditor(item));
          headerActions.insertBefore(editButton, closeButton);
        }
      }
    } catch (error) {
      toast(error.message, true);
    }
  };
})();
