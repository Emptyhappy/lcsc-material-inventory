(() => {
  const csvButton = document.querySelector("#settingsExportButton");
  const card = csvButton?.closest(".settings-card");
  if (!card || document.querySelector("#fullBackupExportButton")) return;

  card.classList.add("backup-card");
  const title = card.querySelector("h2");
  const description = card.querySelector("p");
  title.textContent = "完整数据备份";
  description.textContent = "备份包含物料、库存、全部流水、仓位、设置、完整分类与本地元器件图片。";

  const actions = document.createElement("div");
  actions.className = "backup-actions";
  actions.innerHTML = `
    <button id="fullBackupExportButton" class="button primary" type="button">导出完整备份</button>
    <button id="fullBackupRestoreButton" class="button danger-outline" type="button">恢复完整备份</button>
    <input id="fullBackupFile" type="file" accept=".zip,application/zip" hidden>`;
  actions.append(csvButton);
  card.append(actions);

  const note = document.createElement("div");
  note.className = "backup-note";
  note.innerHTML = `<strong>安全恢复</strong><span>恢复前会自动导出当前数据到 <code>data/backups</code>，并校验备份数据库和每张图片。</span>`;
  card.append(note);

  const status = document.createElement("div");
  status.id = "backupStatus";
  status.className = "backup-status";
  status.setAttribute("role", "status");
  card.append(status);

  const exportButton = actions.querySelector("#fullBackupExportButton");
  const restoreButton = actions.querySelector("#fullBackupRestoreButton");
  const fileInput = actions.querySelector("#fullBackupFile");

  exportButton.addEventListener("click", () => {
    status.textContent = "正在生成完整备份…";
    location.href = `/api/backup/export?t=${Date.now()}`;
    setTimeout(() => { status.textContent = "完整备份已生成，请妥善保存 ZIP 文件。"; }, 700);
  });

  restoreButton.addEventListener("click", () => {
    fileInput.value = "";
    fileInput.click();
  });

  fileInput.addEventListener("change", async () => {
    const file = fileInput.files?.[0];
    if (!file) return;
    const approved = confirm(
      `确定恢复“${file.name}”吗？\n\n当前物料、库存、流水、分类、设置和图片将被备份包替换。${
        window.autoSafetyBackupMessage?.("backup_restore") || "系统会先自动生成安全备份。"}`
    );
    if (!approved) return;

    restoreButton.disabled = true;
    exportButton.disabled = true;
    status.classList.remove("error");
    status.textContent = `正在校验并恢复 ${file.name}，请勿关闭页面…`;
    try {
      const response = await fetch("/api/backup/restore", {
        method: "POST",
        headers: { "Content-Type": "application/zip" },
        body: file,
      });
      let result;
      try { result = await response.json(); }
      catch (_) { result = {}; }
      if (!response.ok) throw new Error(result.error || "备份恢复失败");
      status.textContent = `恢复完成：${result.counts?.materials ?? 0} 种物料、${result.image_count ?? 0} 张图片。正在刷新系统…`;
      toast("完整备份已恢复，页面即将刷新");
      setTimeout(() => location.reload(), 900);
    } catch (error) {
      status.classList.add("error");
      status.textContent = error.message;
      toast(error.message, true);
      restoreButton.disabled = false;
      exportButton.disabled = false;
    }
  });
})();
