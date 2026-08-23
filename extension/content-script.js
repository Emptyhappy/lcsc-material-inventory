(() => {
  if (window.__materialInventoryInjected) return;
  window.__materialInventoryInjected = true;

  function readJson(selector) {
    const element = document.querySelector(selector);
    if (!element?.textContent) return null;
    try { return JSON.parse(element.textContent); }
    catch { return null; }
  }

  function productJsonLd() {
    for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
      try {
        const data = JSON.parse(script.textContent);
        const candidates = data["@graph"] || [data];
        const product = candidates.find(item => {
          const type = item?.["@type"];
          return type === "Product" || (Array.isArray(type) && type.includes("Product"));
        });
        const breadcrumb = candidates.find(item => item?.["@type"] === "BreadcrumbList");
        if (product) return { product, breadcrumb };
      } catch { /* try the next structured-data block */ }
    }
    return { product: null, breadcrumb: null };
  }

  function extractProduct() {
    const next = readJson("#__NEXT_DATA__");
    const pageProps = next?.props?.pageProps || {};
    const webData = pageProps.webData || {};
    const record = webData.productRecord || {};
    const catalog = webData.currentCatalog || {};
    const params = webData.paramList || [];
    const { product, breadcrumb } = productJsonLd();
    const supplierSku = String(record.productCode || product?.sku || "").toUpperCase();
    if (!/^C\d+$/.test(supplierSku)) {
      throw new Error("当前页面没有识别到立创C编号，请确认这是商品详情页");
    }
    const specs = {};
    for (const item of params) {
      const key = item.parameterName;
      const value = item.parameterDetailValue || item.parameterValue;
      if (key && value != null && Object.keys(specs).length < 80) specs[key] = String(value);
    }
    const subject = product?.subjectOf;
    const datasheet = Array.isArray(subject)
      ? subject.find(item => item?.url)?.url
      : subject?.url;
    const images = product?.image || record.luceneBreviaryImageUrls || [];
    const imageUrl = Array.isArray(images) ? images[0] : String(images).split("<$>")[0];
    const leafCrumb = breadcrumb?.itemListElement
      ?.filter(item => /list\.szlcsc\.com\/catalog\/(\d+)/.test(item.item || ""))
      ?.at(-1);
    const crumbId = leafCrumb?.item?.match(/catalog\/(\d+)/)?.[1];
    const categoryId = String(catalog.catalogId || crumbId || "");
    const categoryName = catalog.catalogName || leafCrumb?.name || product?.category || "未分类";
    return {
      request_id: crypto.randomUUID(),
      supplier_sku: supplierSku,
      name: record.productName || product?.description || record.productModel || product?.mpn,
      manufacturer_part: record.productModel || product?.mpn || "",
      brand: record.productGradePlateName || product?.brand?.name || product?.manufacturer?.name || "",
      package: record.encapsulationModel || specs["封装/外壳"] || specs["封装"] || "",
      description: product?.description || record.remark || "",
      specs,
      image_url: imageUrl || "",
      datasheet_url: datasheet || webData.pdfFileDetailVO?.fileUrl || "",
      product_url: product?.url || location.href.split("?")[0],
      price: Number(pageProps.price ?? product?.offers?.price) || null,
      currency: product?.offers?.priceCurrency || "CNY",
      category: categoryId ? {
        external_id: categoryId,
        parent_external_id: String(catalog.parentId || "1"),
        name: categoryName,
        code: catalog.catalogCode || "",
        url: leafCrumb?.item || `https://list.szlcsc.com/catalog/${categoryId}.html`,
      } : null,
    };
  }

  function showToast(message, { error = false, transactionId = null } = {}) {
    document.querySelector("#material-inventory-toast")?.remove();
    const element = document.createElement("div");
    element.id = "material-inventory-toast";
    element.className = error ? "is-error" : "";
    const text = document.createElement("span");
    text.textContent = message;
    element.append(text);
    if (transactionId) {
      const undo = document.createElement("button");
      undo.textContent = "撤销";
      undo.addEventListener("click", async () => {
        undo.disabled = true;
        const response = await chrome.runtime.sendMessage({ type: "UNDO_TRANSACTION", transactionId });
        if (response?.ok) {
          element.remove();
          showToast("刚才的入库已撤销");
        } else {
          undo.disabled = false;
          showToast(response?.error || "撤销失败", { error: true });
        }
      });
      element.append(undo);
    }
    if (error && /连接密钥|Failed to fetch|本地服务/.test(message)) {
      const settings = document.createElement("button");
      settings.textContent = "扩展设置";
      settings.addEventListener("click", () => chrome.runtime.sendMessage({ type: "OPEN_OPTIONS" }));
      element.append(settings);
    }
    document.body.append(element);
    requestAnimationFrame(() => element.classList.add("visible"));
    setTimeout(() => {
      element.classList.remove("visible");
      setTimeout(() => element.remove(), 250);
    }, error ? 7000 : 5000);
  }

  const button = document.createElement("button");
  button.id = "material-inventory-add";
  button.innerHTML = `<span class="mi-icon">＋</span><span><b>加入我的物料库</b><small>默认数量 1 · 默认仓位</small></span>`;
  document.body.append(button);

  button.addEventListener("click", async () => {
    if (button.disabled) return;
    const original = button.innerHTML;
    button.disabled = true;
    button.innerHTML = `<span class="mi-spinner"></span><span><b>正在加入…</b><small>读取商品参数和分类</small></span>`;
    try {
      const payload = extractProduct();
      const response = await chrome.runtime.sendMessage({ type: "IMPORT_LCSC", payload });
      if (!response?.ok) throw new Error(response?.error || "扩展没有收到本地系统响应");
      const data = response.data;
      if (data.duplicate_request) {
        showToast(`${data.name} 已处理，请勿重复点击`);
      } else {
        showToast(
          `${data.created ? "已创建物料" : "已存在，继续入库"}：${data.name}  +${data.added_quantity}`,
          { transactionId: data.transaction_id },
        );
      }
      button.innerHTML = `<span class="mi-icon mi-success">✓</span><span><b>已加入，可再次 +1</b><small>${data.internal_code} · 当前 ${data.stock}</small></span>`;
    } catch (error) {
      showToast(error.message || "添加失败", { error: true });
      button.innerHTML = original;
    } finally {
      setTimeout(() => { button.disabled = false; }, 800);
    }
  });
})();
