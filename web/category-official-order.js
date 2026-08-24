(() => {
  const card = document.querySelector("#categoryOrderCard");
  const parentSelect = document.querySelector("#categoryOrderParent");
  if (!card || !parentSelect || document.querySelector("#resetCategoryOrderButton")) return;
  const actions = document.createElement("div");
  actions.className = "category-order-actions";
  actions.innerHTML = `<button id="resetCategoryOrderButton" type="button" class="button secondary compact">重新同步并恢复全部立创顺序</button><span>会清除所有立创父级和子级的自定义调序，一级分类首项恢复为“电容”</span>`;
  card.insertBefore(actions, document.querySelector("#categoryOrderList"));
  actions.querySelector("#resetCategoryOrderButton").addEventListener("click", async event => {
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = "正在同步并恢复…";
    try {
      const result = await api("/api/categories/order/restore-lcsc", {
        method: "POST",
        body: {},
      });
      state.categories = result.categories;
      state.relations = result.relations;
      renderCategoryTree();
      renderCategoryOptions();
      parentSelect.dispatchEvent(new Event("change"));
      toast(`已恢复全部立创分类顺序${result.first_category ? `，首项为“${result.first_category}”` : ""}`);
    } catch (error) {
      toast(error.message, true);
    } finally {
      button.disabled = false;
      button.textContent = "重新同步并恢复全部立创顺序";
    }
  });
})();
