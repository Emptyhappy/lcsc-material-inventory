(() => {
  if (window.__transactionDeletionInstalled) return;
  window.__transactionDeletionInstalled = true;

  const manager = document.querySelector("#transactionManager");
  if (!manager) return;

  function enhanceManager() {
    const actions = manager.querySelector(".transaction-manager-actions");
    if (actions && !actions.querySelector("[data-delete-action='all']")) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "button danger compact transaction-delete-all";
      button.dataset.deleteAction = "all";
      button.textContent = "全部删除";
      actions.append(button);
    }
    manager.querySelectorAll(".transaction-manager-editor").forEach(editor => {
      if (editor.querySelector("[data-delete-action='one']")) return;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "button danger compact";
      button.dataset.deleteAction = "one";
      button.textContent = "删除";
      editor.append(button);
    });
  }

  new MutationObserver(enhanceManager).observe(manager, { childList: true, subtree: true });

  async function refreshPages() {
    await Promise.all([loadDashboard(), loadMaterials()]);
    if (state.view === "transactions") await loadTransactions();
  }

  manager.addEventListener("click", async event => {
    const button = event.target.closest?.("[data-delete-action]");
    if (!button) return;
    event.preventDefault();
    event.stopPropagation();

    try {
      if (button.dataset.deleteAction === "one") {
        const item = button.closest("[data-transaction-id]");
        const transactionId = Number(item.dataset.transactionId);
        if (!confirm("确定删除这条流水吗？删除后不会改变当前库存，但无法在管理界面恢复。")) return;
        await api(`/api/transactions/${transactionId}/delete`, { method: "POST", body: {} });
        item.remove();
        toast("流水已删除，库存保持不变");
      } else {
        const materialId = manager.dataset.materialId;
        const scope = materialId ? "该物料的全部流水" : "全部库存流水";
        if (!confirm(`确定删除${scope}吗？删除后库存保持不变，且无法在管理界面恢复。`)) return;
        const path = materialId
          ? `/api/materials/${materialId}/transactions/delete-all`
          : "/api/transactions/delete-all";
        const result = await api(path, { method: "POST", body: {} });
        toast(`已删除 ${result.deleted_count} 条流水，库存保持不变`);
        manager.close();
      }
      await refreshPages();
    } catch (error) {
      toast(error.message, true);
    }
  });
})();
