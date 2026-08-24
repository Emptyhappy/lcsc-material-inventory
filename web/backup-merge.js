(() => {
  const actions = document.querySelector(".backup-actions");
  const restoreButton = document.querySelector("#fullBackupRestoreButton");
  const status = document.querySelector("#backupStatus");
  if (!actions || !restoreButton || !status || document.querySelector("#fullBackupMergeButton")) return;

  const mergeButton = document.createElement("button");
  mergeButton.id = "fullBackupMergeButton";
  mergeButton.type = "button";
  mergeButton.className = "button secondary";
  mergeButton.textContent = "添加备份中的物料";
  const input = document.createElement("input");
  input.type = "file";
  input.accept = ".zip,application/zip";
  input.hidden = true;
  actions.insertBefore(mergeButton, restoreButton);
  actions.append(input);

  const note = document.querySelector(".backup-note span");
  if (note) {
    note.textContent = "“添加备份”会保留当前数据，只加入备份中没有的物料；相同 C 编号或完全相同的手动物料会跳过，避免库存重复。完整恢复则会替换当前数据。两种操作都会先自动安全备份。";
  }

  mergeButton.addEventListener("click", () => {
    input.value = "";
    input.click();
  });
  input.addEventListener("change", async () => {
    const file = input.files?.[0];
    if (!file) return;
    if (!confirm(
      `把“${file.name}”中的物料添加到当前系统吗？\n\n当前物料不会删除；重复的 C 编号或相同手动物料会跳过，备份独有物料会连同库存、流水、分类和图片一起加入。${
        window.autoSafetyBackupMessage?.("backup_merge") || "系统会先自动生成安全备份。"}`
    )) return;
    mergeButton.disabled = true;
    restoreButton.disabled = true;
    status.classList.remove("error");
    status.textContent = `正在校验并添加 ${file.name} 中的物料…`;
    try {
      const response = await fetch("/api/backup/merge", {
        method: "POST",
        headers: { "Content-Type": "application/zip" },
        body: file,
      });
      let result;
      try { result = await response.json(); }
      catch (_) { result = {}; }
      if (!response.ok) throw new Error(result.error || "添加备份失败");
      status.textContent = `添加完成：新增 ${result.added_materials} 种物料、${result.added_transactions} 条流水、${result.added_images} 张图片；跳过 ${result.skipped_duplicates} 种重复物料。`;
      toast(`已从备份加入 ${result.added_materials} 种物料`);
      setTimeout(() => location.reload(), 1100);
    } catch (error) {
      status.classList.add("error");
      status.textContent = error.message;
      toast(error.message, true);
      mergeButton.disabled = false;
      restoreButton.disabled = false;
    }
  });
})();
