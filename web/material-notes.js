(() => {
  if (window.__materialNotesInstalled) return;
  window.__materialNotesInstalled = true;

  const dialog = document.createElement("dialog");
  dialog.id = "materialNotesDialog";
  dialog.className = "modal material-notes-dialog";
  document.body.append(dialog);

  function openNotesEditor(item) {
    dialog.innerHTML = `
      <form id="materialNotesForm">
        <div class="modal-header">
          <div><h2>修改元器件备注</h2><p>${esc(item.internal_code)} · ${esc(item.name)}</p></div>
          <button type="button" class="icon-button" data-notes-close>×</button>
        </div>
        <div class="material-notes-editor">
          <label>元器件备注
            <textarea name="notes" rows="1" maxlength="4000" placeholder="长期保存在这个元器件档案中；留空时详情显示“无”">${esc(item.notes || "")}</textarea>
          </label>
        </div>
        <div class="modal-actions">
          <button type="button" class="button ghost" data-notes-close>取消</button>
          <button class="button primary" type="submit">保存备注</button>
        </div>
      </form>`;
    dialog.querySelectorAll("[data-notes-close]").forEach(button => {
      button.addEventListener("click", () => dialog.close());
    });
    dialog.querySelector("form").addEventListener("submit", async event => {
      event.preventDefault();
      const button = event.submitter;
      button.disabled = true;
      try {
        await api(`/api/materials/${item.id}`, {
          method: "PUT",
          body: { notes: new FormData(event.currentTarget).get("notes") },
        });
        dialog.close();
        document.querySelector("#detailDialog")?.close();
        await Promise.all([loadMaterials(), loadDashboard()]);
        toast("元器件备注已保存");
        await openDetail(item.id);
      } catch (error) {
        toast(error.message, true);
      } finally {
        button.disabled = false;
      }
    });
    dialog.showModal();
    const textarea = dialog.querySelector("textarea");
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
    textarea.focus();
  }

  const baseOpenDetail = openDetail;
  openDetail = async function openDetailWithEditableNotes(id) {
    const detailRequest = api(`/api/materials/${id}`);
    await baseOpenDetail(id);
    try {
      const item = await detailRequest;
      const sections = document.querySelector("#detailContent .detail-sections");
      if (!sections) return;
      let section = sections.querySelector(".material-notes-section");
      if (!section) {
        section = document.createElement("section");
        section.className = "detail-section material-notes-section";
        sections.prepend(section);
      }
      section.innerHTML = `
        <div class="material-notes-heading">
          <h3>元器件备注</h3>
          <button type="button" class="button secondary compact">修改备注</button>
        </div>
        <p>${esc(item.notes || "无")}</p>`;
      section.querySelector("button").addEventListener("click", () => openNotesEditor(item));
    } catch (error) {
      toast(error.message, true);
    }
  };
})();
