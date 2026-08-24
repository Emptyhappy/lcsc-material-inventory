(() => {
  const card = document.querySelector("#categoryOrderCard");
  const parentSelect = document.querySelector("#categoryOrderParent");
  if (!card || !parentSelect || document.querySelector("#resetCategoryOrderButton")) return;
  const actions = document.createElement("div");
  actions.className = "category-order-actions";
  actions.innerHTML = `<button id="resetCategoryOrderButton" type="button" class="button secondary compact">恢复立创商城顺序</button><span>立创页面一级分类首项为“电容”</span>`;
  card.insertBefore(actions, document.querySelector("#categoryOrderList"));
  actions.querySelector("#resetCategoryOrderButton").addEventListener("click", async event => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const result = await api("/api/categories/reorder/reset", {
        method: "POST",
        body: { parent_id: Number(parentSelect.value) },
      });
      state.categories = result.categories;
      state.relations = result.relations;
      renderCategoryTree();
      renderCategoryOptions();
      parentSelect.dispatchEvent(new Event("change"));
      toast("已恢复立创商城同步顺序");
    } catch (error) {
      toast(error.message, true);
    } finally {
      button.disabled = false;
    }
  });
})();
