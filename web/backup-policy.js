(() => {
  if (window.__backupPolicyInstalled) return;
  window.__backupPolicyInstalled = true;

  const card = document.querySelector(".backup-card");
  const actions = document.querySelector(".backup-actions");
  const status = document.querySelector("#backupStatus");
  if (!card || !actions || !status) return;

  const levelDescriptions = {
    high: "高安全性：删除单个或批量物料、删除单条或批量流水、清空流水、恢复与添加备份前都自动保存安全备份。",
    medium: "中等安全性：仅在批量删除物料、批量删除或清空流水、恢复与添加备份前自动保存安全备份。",
    low: "低安全性：不生成自动安全备份；手动导出和正常备份仍可使用。",
  };

  window.autoSafetyBackupEnabled = operation => {
    const level = state.settings.auto_backup_level || "high";
    if (level === "high") return true;
    if (level === "low") return false;
    return new Set([
      "material_batch_delete", "transaction_clear", "transaction_bulk_delete",
      "backup_restore", "backup_merge",
    ]).has(operation);
  };
  window.autoSafetyBackupMessage = operation => window.autoSafetyBackupEnabled(operation)
    ? "系统会先自动生成安全备份。"
    : "按当前安全级别，本次操作不会生成自动安全备份。";

  const browserExport = document.querySelector("#fullBackupExportButton");
  if (browserExport) browserExport.textContent = "下载完整备份";

  const saveButton = document.createElement("button");
  saveButton.id = "saveNormalBackupButton";
  saveButton.className = "button secondary";
  saveButton.type = "button";
  saveButton.textContent = "保存正常备份";
  actions.insertBefore(saveButton, browserExport || actions.firstChild);

  const policy = document.createElement("form");
  policy.id = "backupPolicyForm";
  policy.className = "backup-policy-form";
  policy.innerHTML = `
    <h3>自动安全备份</h3>
    <label>安全级别
      <select id="autoBackupLevel">
        <option value="high">高安全性</option>
        <option value="medium">中等安全性</option>
        <option value="low">低安全性</option>
      </select>
    </label>
    <p id="backupLevelDescription" class="backup-level-description"></p>
    <label>安全备份地址
      <input id="safetyBackupDir" autocomplete="off" placeholder="例如 D:\\物料备份\\安全备份">
    </label>
    <label>正常备份地址
      <input id="normalBackupDir" autocomplete="off" placeholder="例如 D:\\物料备份\\正常备份">
    </label>
    <div class="backup-policy-actions">
      <button class="button primary" type="submit">保存备份设置</button>
    </div>`;
  card.insertBefore(policy, document.querySelector(".backup-note"));

  const levelSelect = policy.querySelector("#autoBackupLevel");
  const levelDescription = policy.querySelector("#backupLevelDescription");
  const safetyDir = policy.querySelector("#safetyBackupDir");
  const normalDir = policy.querySelector("#normalBackupDir");
  const note = document.querySelector(".backup-note");

  function renderBackupPolicy() {
    const level = state.settings.auto_backup_level || "high";
    levelSelect.value = level;
    safetyDir.value = state.settings.safety_backup_dir || "";
    normalDir.value = state.settings.normal_backup_dir || "";
    levelDescription.textContent = levelDescriptions[level] || levelDescriptions.high;
    if (note) {
      note.innerHTML = `<strong>${level === "low" ? "自动安全备份已关闭" : "安全备份策略"}</strong><span>${esc(levelDescriptions[level] || levelDescriptions.high)}</span>`;
      note.classList.toggle("backup-note-low", level === "low");
    }
  }

  levelSelect.addEventListener("change", () => {
    levelDescription.textContent = levelDescriptions[levelSelect.value];
  });

  policy.addEventListener("submit", async event => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    try {
      state.settings = await api("/api/settings", {
        method: "PUT",
        body: {
          auto_backup_level: levelSelect.value,
          safety_backup_dir: safetyDir.value.trim(),
          normal_backup_dir: normalDir.value.trim(),
        },
      });
      renderBackupPolicy();
      toast("备份安全级别和地址已保存");
    } catch (error) {
      toast(error.message, true);
    } finally {
      button.disabled = false;
    }
  });

  saveButton.addEventListener("click", async () => {
    saveButton.disabled = true;
    status.classList.remove("error");
    status.textContent = "正在保存正常备份…";
    try {
      const result = await api("/api/backup/save", { method: "POST", body: {} });
      status.textContent = `正常备份已保存：${result.path}`;
      toast("正常备份已保存到设置地址");
    } catch (error) {
      status.classList.add("error");
      status.textContent = error.message;
      toast(error.message, true);
    } finally {
      saveButton.disabled = false;
    }
  });

  const baseRenderSettings = renderSettings;
  renderSettings = function renderSettingsWithBackupPolicy() {
    baseRenderSettings();
    renderBackupPolicy();
  };
  renderBackupPolicy();
})();
