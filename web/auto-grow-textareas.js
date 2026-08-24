(() => {
  if (window.__autoGrowTextareasInstalled) return;
  window.__autoGrowTextareasInstalled = true;

  function grow(textarea) {
    if (!(textarea instanceof HTMLTextAreaElement)) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.max(textarea.scrollHeight, 42)}px`;
  }

  function scan(root = document) {
    if (root instanceof HTMLTextAreaElement) grow(root);
    root.querySelectorAll?.("textarea").forEach(grow);
  }

  document.addEventListener("input", event => grow(event.target));
  document.addEventListener("focusin", event => grow(event.target));
  new MutationObserver(records => {
    records.forEach(record => record.addedNodes.forEach(node => {
      if (node instanceof Element) scan(node);
    }));
  }).observe(document.body, { childList: true, subtree: true });
  scan();
})();
