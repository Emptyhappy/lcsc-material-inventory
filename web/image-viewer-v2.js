(() => {
  if (window.__materialImageViewerInstalled) return;
  window.__materialImageViewerInstalled = true;

  const viewer = document.createElement("dialog");
  viewer.id = "materialImageViewer";
  viewer.className = "image-viewer image-viewer-v2";
  viewer.setAttribute("aria-label", "元器件图片预览");
  viewer.innerHTML = `
    <div class="image-viewer-toolbar">
      <button type="button" data-action="zoom-out" title="缩小">−</button>
      <button type="button" data-action="reset" class="image-viewer-scale">100%</button>
      <button type="button" data-action="zoom-in" title="放大">＋</button>
      <button type="button" data-action="close" class="image-viewer-close" title="关闭">×</button>
    </div>
    <div class="image-viewer-stage">
      <img alt="元器件图片" draggable="false">
      <span class="image-viewer-hint">放大后按住鼠标左键拖动</span>
    </div>`;
  document.body.append(viewer);

  const stage = viewer.querySelector(".image-viewer-stage");
  const preview = stage.querySelector("img");
  const scaleLabel = viewer.querySelector(".image-viewer-scale");
  let scale = 1;
  let translateX = 0;
  let translateY = 0;
  let dragging = false;
  let moved = false;
  let pointerStartX = 0;
  let pointerStartY = 0;
  let translateStartX = 0;
  let translateStartY = 0;

  function updateTransform() {
    preview.style.transform = `translate(${translateX}px, ${translateY}px) scale(${scale})`;
    scaleLabel.textContent = `${Math.round(scale * 100)}%`;
    preview.classList.toggle("can-pan", scale > 1);
  }

  function resetPosition() {
    translateX = 0;
    translateY = 0;
  }

  function setScale(nextScale) {
    scale = Math.min(6, Math.max(0.5, nextScale));
    if (scale <= 1) resetPosition();
    updateTransform();
  }

  function open(trigger) {
    scale = 1;
    resetPosition();
    preview.src = trigger.currentSrc || trigger.src;
    preview.alt = trigger.alt || "元器件图片";
    updateTransform();
    if (!viewer.open) viewer.showModal();
    viewer.querySelector("[data-action='close']").focus();
  }

  function close() {
    dragging = false;
    preview.classList.remove("dragging");
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
    if (action === "zoom-in") setScale(scale + 0.25);
    if (action === "zoom-out") setScale(scale - 0.25);
    if (action === "reset") { scale = 1; resetPosition(); updateTransform(); }
    if ((event.target === viewer || event.target === stage) && !moved) close();
    moved = false;
  });

  stage.addEventListener("wheel", event => {
    event.preventDefault();
    setScale(scale + (event.deltaY < 0 ? 0.15 : -0.15));
  }, { passive: false });

  preview.addEventListener("pointerdown", event => {
    if (event.button !== 0 || scale <= 1) return;
    event.preventDefault();
    dragging = true;
    moved = false;
    pointerStartX = event.clientX;
    pointerStartY = event.clientY;
    translateStartX = translateX;
    translateStartY = translateY;
    preview.classList.add("dragging");
    preview.setPointerCapture(event.pointerId);
  });

  preview.addEventListener("pointermove", event => {
    if (!dragging) return;
    const deltaX = event.clientX - pointerStartX;
    const deltaY = event.clientY - pointerStartY;
    if (Math.abs(deltaX) + Math.abs(deltaY) > 3) moved = true;
    translateX = translateStartX + deltaX;
    translateY = translateStartY + deltaY;
    updateTransform();
  });

  function endDrag(event) {
    if (!dragging) return;
    dragging = false;
    preview.classList.remove("dragging");
    if (preview.hasPointerCapture(event.pointerId)) {
      preview.releasePointerCapture(event.pointerId);
    }
  }
  preview.addEventListener("pointerup", endDrag);
  preview.addEventListener("pointercancel", endDrag);
  preview.addEventListener("dragstart", event => event.preventDefault());
  preview.addEventListener("dblclick", event => {
    event.preventDefault();
    if (scale > 1) { scale = 1; resetPosition(); updateTransform(); }
    else setScale(2);
  });

  viewer.addEventListener("keydown", event => {
    if (event.key === "Escape") close();
    if (event.key === "+" || event.key === "=") setScale(scale + 0.25);
    if (event.key === "-") setScale(scale - 0.25);
    if (event.key === "0") { scale = 1; resetPosition(); updateTransform(); }
  });
})();
