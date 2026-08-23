(() => {
  if (window.__materialImageViewerInstalled) return;
  window.__materialImageViewerInstalled = true;

  const viewer = document.createElement("dialog");
  viewer.id = "materialImageViewer";
  viewer.className = "image-viewer";
  viewer.setAttribute("aria-label", "元器件图片预览");
  viewer.innerHTML = `
    <div class="image-viewer-toolbar">
      <button type="button" data-action="zoom-out" title="缩小">−</button>
      <button type="button" data-action="reset" class="image-viewer-scale">100%</button>
      <button type="button" data-action="zoom-in" title="放大">＋</button>
      <button type="button" data-action="close" class="image-viewer-close" title="关闭">×</button>
    </div>
    <div class="image-viewer-stage">
      <img alt="元器件图片">
    </div>`;
  document.body.append(viewer);

  const stage = viewer.querySelector(".image-viewer-stage");
  const preview = stage.querySelector("img");
  const scaleLabel = viewer.querySelector(".image-viewer-scale");
  let scale = 1;

  function updateScale() {
    preview.style.transform = `scale(${scale})`;
    scaleLabel.textContent = `${Math.round(scale * 100)}%`;
  }

  function changeScale(delta) {
    scale = Math.min(4, Math.max(0.5, scale + delta));
    updateScale();
  }

  function open(trigger) {
    scale = 1;
    preview.src = trigger.currentSrc || trigger.src;
    preview.alt = trigger.alt || "元器件图片";
    updateScale();
    if (!viewer.open) viewer.showModal();
    viewer.querySelector("[data-action='close']").focus();
  }

  function close() {
    if (viewer.open) viewer.close();
    preview.removeAttribute("src");
  }

  document.addEventListener("click", event => {
    const trigger = event.target.closest?.("img.material-thumb, img.detail-image");
    if (!trigger) return;
    event.preventDefault();
    event.stopPropagation();
    open(trigger);
  }, true);

  viewer.addEventListener("click", event => {
    const action = event.target.closest?.("[data-action]")?.dataset.action;
    if (action === "close") close();
    if (action === "zoom-in") changeScale(0.25);
    if (action === "zoom-out") changeScale(-0.25);
    if (action === "reset") { scale = 1; updateScale(); }
    if (event.target === viewer) close();
  });

  stage.addEventListener("wheel", event => {
    event.preventDefault();
    changeScale(event.deltaY < 0 ? 0.15 : -0.15);
  }, { passive: false });

  viewer.addEventListener("keydown", event => {
    if (event.key === "Escape") close();
    if (event.key === "+" || event.key === "=") changeScale(0.25);
    if (event.key === "-") changeScale(-0.25);
    if (event.key === "0") { scale = 1; updateScale(); }
  });
})();
