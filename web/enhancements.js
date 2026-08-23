(() => {
  const settingsGrid = document.querySelector(".settings-grid");
  if (!settingsGrid || document.querySelector("#categoryOrderCard")) return;

  const card = document.createElement("div");
  card.id = "categoryOrderCard";
  card.className = "panel settings-card category-order-card";
  card.innerHTML = `
    <h2>分类显示顺序</h2>
    <p>选择一个父分类，然后用上移、下移调整其子分类在左侧分类树中的顺序。</p>
    <label>父分类<select id="categoryOrderParent"></select></label>
    <div id="categoryOrderList" class="category-order-list"></div>`;
  settingsGrid.append(card);

  const parentSelect = card.querySelector("#categoryOrderParent");
  const orderList = card.querySelector("#categoryOrderList");

  function childMap() {
    const result = new Map();
    for (const relation of state.relations) {
      if (!result.has(relation.parent_id)) result.set(relation.parent_id, []);
      result.get(relation.parent_id).push(relation.child_id);
    }
    return result;
  }

  function parentOptions() {
    const children = childMap();
    const byId = new Map(state.categories.map(item => [item.id, item]));
    return [...children.entries()]
      .filter(([, ids]) => ids.length >= 2)
      .map(([parentId, ids]) => ({ parent: byId.get(parentId), count: ids.length }))
      .filter(item => item.parent)
      .sort((a, b) => a.parent.name.localeCompare(b.parent.name, "zh-CN"));
  }

  function renderParents(preferredId = null) {
    const previous = preferredId || Number(parentSelect.value) || null;
    const options = parentOptions();
    parentSelect.innerHTML = options.map(item =>
      `<option value="${item.parent.id}">${esc(item.parent.name)}（${item.count}项）</option>`
    ).join("");
    if (previous && options.some(item => item.parent.id === previous)) parentSelect.value = String(previous);
    renderChildren();
  }

  function orderedChildren(parentId) {
    const byId = new Map(state.categories.map(item => [item.id, item]));
    return state.relations
      .filter(item => item.parent_id === parentId)
      .map(item => byId.get(item.child_id))
      .filter(Boolean)
      .sort((a, b) => (Number(a.sort_order) - Number(b.sort_order)) || a.name.localeCompare(b.name, "zh-CN"));
  }

  function renderChildren() {
    const parentId = Number(parentSelect.value);
    const children = orderedChildren(parentId);
    if (!children.length) {
      orderList.innerHTML = `<div class="category-order-empty">没有可排序的子分类</div>`;
      return;
    }
    orderList.innerHTML = children.map((item, index) => `
      <div class="category-order-row" data-category-id="${item.id}">
        <span class="category-order-index">${index + 1}</span>
        <span class="category-order-name" title="${esc(item.name)}">${esc(item.name)}</span>
        <button type="button" data-move="up" ${index === 0 ? "disabled" : ""} title="上移">↑</button>
        <button type="button" data-move="down" ${index === children.length - 1 ? "disabled" : ""} title="下移">↓</button>
      </div>`).join("");
  }

  async function moveCategory(categoryId, direction, button) {
    const parentId = Number(parentSelect.value);
    const children = orderedChildren(parentId);
    const index = children.findIndex(item => item.id === categoryId);
    const target = direction === "up" ? index - 1 : index + 1;
    if (index < 0 || target < 0 || target >= children.length) return;
    [children[index], children[target]] = [children[target], children[index]];
    button.disabled = true;
    try {
      const result = await api("/api/categories/reorder", {
        method: "POST",
        body: { parent_id: parentId, child_ids: children.map(item => item.id) },
      });
      state.categories = result.categories;
      state.relations = result.relations;
      renderChildren();
      renderCategoryTree();
      renderCategoryOptions();
      toast("分类顺序已保存");
    } catch (error) {
      button.disabled = false;
      toast(error.message, true);
    }
  }

  parentSelect.addEventListener("change", renderChildren);
  orderList.addEventListener("click", event => {
    const button = event.target.closest("[data-move]");
    if (!button) return;
    const row = button.closest("[data-category-id]");
    moveCategory(Number(row.dataset.categoryId), button.dataset.move, button);
  });

  document.querySelector('[data-view="settings"]')?.addEventListener("click", () => {
    setTimeout(() => renderParents(), 30);
  });
  document.querySelector("#syncCategoriesButton")?.addEventListener("click", () => {
    setTimeout(() => renderParents(), 1500);
  });
  document.querySelector("#refreshCategories")?.addEventListener("click", () => {
    setTimeout(() => renderParents(), 100);
  });
  setTimeout(() => renderParents(), 500);
})();
