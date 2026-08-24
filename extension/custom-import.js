(() => {
  if (window.__materialInventoryCustomInjected) return;
  window.__materialInventoryCustomInjected = true;

  function json(selector) {
    try { return JSON.parse(document.querySelector(selector)?.textContent || "null"); }
    catch { return null; }
  }

  function jsonLdProduct() {
    for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
      try {
        const data = JSON.parse(script.textContent);
        const graph = data["@graph"] || [data];
        const product = graph.find(item => {
          const type = item?.["@type"];
          return type === "Product" || (Array.isArray(type) && type.includes("Product"));
        });
        const breadcrumb = graph.find(item => item?.["@type"] === "BreadcrumbList");
        if (product) return { product, breadcrumb };
      } catch { /* continue */ }
    }
    return {};
  }

  function extract() {
    const props = json("#__NEXT_DATA__")?.props?.pageProps || {};
    const web = props.webData || {};
    const record = web.productRecord || {};
    const catalog = web.currentCatalog || {};
    const { product, breadcrumb } = jsonLdProduct();
    const supplierSku = String(record.productCode || product?.sku || "").toUpperCase();
    if (!/^C\d+$/.test(supplierSku)) throw new Error("没有识别到有效的立创C编号");
    const specs = {};
    for (const item of web.paramList || []) {
      const value = item.parameterDetailValue || item.parameterValue;
      if (item.parameterName && value != null && Object.keys(specs).length < 80) {
        specs[item.parameterName] = String(value);
      }
    }
    const subject = product?.subjectOf;
    const datasheet = Array.isArray(subject) ? subject.find(item => item?.url)?.url : subject?.url;
    const images = product?.image || record.luceneBreviaryImageUrls || [];
    const leaf = breadcrumb?.itemListElement
      ?.filter(item => /list\.szlcsc\.com\/catalog\/(\d+)/.test(item.item || ""))
      ?.at(-1);
    const categoryId = String(catalog.catalogId || leaf?.item?.match(/catalog\/(\d+)/)?.[1] || "");
    return {
      request_id: crypto.randomUUID(),
      supplier_sku: supplierSku,
      name: record.productName || product?.description || record.productModel || product?.mpn,
      manufacturer_part: record.productModel || product?.mpn || "",
      brand: record.productGradePlateName || product?.brand?.name || product?.manufacturer?.name || "",
      package: record.encapsulationModel || specs["封装/外壳"] || specs["封装"] || "",
      description: product?.description || record.remark || "",
      specs,
      image_url: (Array.isArray(images) ? images[0] : String(images).split("<$>")[0]) || "",
      datasheet_url: datasheet || web.pdfFileDetailVO?.fileUrl || "",
      product_url: product?.url || location.href.split("?")[0],
      price: Number(props.price ?? product?.offers?.price) || null,
      currency: product?.offers?.priceCurrency || "CNY",
      category: categoryId ? {
        external_id: categoryId,
        parent_external_id: String(catalog.parentId || "1"),
        name: catalog.catalogName || leaf?.name || product?.category || "未分类",
        code: catalog.catalogCode || "",
        url: leaf?.item || `https://list.szlcsc.com/catalog/${categoryId}.html`,
      } : null,
    };
  }

  function notify(message, error = false) {
    document.querySelector("#mi-custom-toast")?.remove();
    const element = document.createElement("div");
    element.id = "mi-custom-toast";
    if (error) element.className = "error";
    element.textContent = message;
    document.body.append(element);
    requestAnimationFrame(() => element.classList.add("show"));
    setTimeout(() => element.remove(), error ? 6500 : 4200);
  }

  function closeModal() {
    document.querySelector("#mi-custom-backdrop")?.remove();
  }

  async function openModal() {
    const response = await chrome.runtime.sendMessage({ type: "GET_IMPORT_OPTIONS" });
    if (!response?.ok) {
      notify(response?.error || "无法读取入库设置，请确认本地系统已启动", true);
      if (/连接密钥/.test(response?.error || "")) {
        chrome.runtime.sendMessage({ type: "OPEN_OPTIONS" });
      }
      return;
    }
    const options = response.data || {};
    const locations = Array.isArray(options.locations) && options.locations.length
      ? options.locations
      : [{ id: options.default_location_id || "", name: options.default_location_name || "默认仓位" }];
    const product = extract();
    closeModal();
    const backdrop = document.createElement("div");
    backdrop.id = "mi-custom-backdrop";
    backdrop.innerHTML = `
      <form id="mi-custom-form">
        <div class="mi-modal-header"><div><b>自定义加入物料库</b><small>${escapeHtml(product.supplier_sku)} · ${escapeHtml(product.manufacturer_part)}</small></div><button type="button" data-close>×</button></div>
        <div class="mi-product-preview">
          ${product.image_url ? `<img src="${escapeHtml(product.image_url)}" alt="" referrerpolicy="no-referrer">` : ""}
          <div><strong>${escapeHtml(product.name)}</strong><span>${escapeHtml(product.brand)} · ${escapeHtml(product.package || "未识别封装")}</span></div>
        </div>
        <div class="mi-form-grid">
          <label>入库数量<input name="quantity" type="number" min="0.001" step="any" value="${Number(options.default_quantity) || 1}" required></label>
          <label>入库仓位<select name="location_id">${locations.map(item => `<option value="${item.id}" ${Number(item.id) === Number(options.default_location_id) ? "selected" : ""}>${escapeHtml(item.name)}</option>`).join("")}<option value="__new__">＋ 新建仓位…</option></select></label>
          <label class="wide mi-new-location mi-hidden">新仓位名称<input name="new_location_name" maxlength="120" placeholder="例如 A柜-03盒-02格"></label>
          <label>最低库存<input name="min_stock" type="number" min="0" step="any" value="0"></label>
          <label>单位<select name="unit"><option>个</option><option>片</option><option>只</option><option>米</option><option>卷</option><option>盒</option></select></label>
          <label class="wide">入库备注<textarea name="transaction_note" rows="1" placeholder="只记录到本次入库流水，例如 2026年采购"></textarea></label>
          <label class="wide">元器件备注<textarea name="material_notes" rows="1" placeholder="长期保存在元器件档案，例如 项目A专用"></textarea></label>
        </div>
        <div class="mi-modal-actions"><button type="button" data-close>取消</button><button class="primary" type="submit">确认加入并入库</button></div>
      </form>`;
    document.body.append(backdrop);
    backdrop.querySelectorAll("[data-close]").forEach(button => button.addEventListener("click", closeModal));
    backdrop.addEventListener("click", event => { if (event.target === backdrop) closeModal(); });
    const locationSelect = backdrop.querySelector("[name='location_id']");
    const newLocationLabel = backdrop.querySelector(".mi-new-location");
    const newLocationInput = backdrop.querySelector("[name='new_location_name']");
    function toggleNewLocation() {
      const creating = locationSelect.value === "__new__";
      newLocationLabel.classList.toggle("mi-hidden", !creating);
      newLocationInput.required = creating;
      if (creating) newLocationInput.focus();
    }
    locationSelect.addEventListener("change", toggleNewLocation);
    function grow(textarea) {
      textarea.style.height = "auto";
      textarea.style.height = `${Math.max(textarea.scrollHeight, 39)}px`;
    }
    backdrop.querySelectorAll("textarea").forEach(textarea => {
      grow(textarea);
      textarea.addEventListener("input", () => grow(textarea));
    });
    backdrop.querySelector("form").addEventListener("submit", async event => {
      event.preventDefault();
      const submit = event.submitter;
      submit.disabled = true;
      submit.textContent = "正在保存并下载图片…";
      const values = Object.fromEntries(new FormData(event.currentTarget).entries());
      product.quantity = Number(values.quantity);
      let selectedLocationName = "所选仓位";
      if (values.location_id === "__new__") {
        const name = String(values.new_location_name || "").trim();
        const locationResult = await chrome.runtime.sendMessage({ type: "CREATE_LOCATION", name });
        if (!locationResult?.ok) {
          submit.disabled = false;
          submit.textContent = "确认加入并入库";
          notify(locationResult?.error || "新建仓位失败", true);
          return;
        }
        product.location_id = Number(locationResult.data.id);
        selectedLocationName = locationResult.data.name;
      } else {
        product.location_id = Number(values.location_id);
        selectedLocationName = locations.find(
          item => Number(item.id || 0) === product.location_id
        )?.name || "所选仓位";
      }
      product.min_stock = Number(values.min_stock || 0);
      product.unit = values.unit;
      product.transaction_note = values.transaction_note;
      product.material_notes = values.material_notes;
      const result = await chrome.runtime.sendMessage({ type: "IMPORT_LCSC", payload: product });
      if (!result?.ok) {
        submit.disabled = false;
        submit.textContent = "确认加入并入库";
        notify(result?.error || "自定义入库失败", true);
        return;
      }
      closeModal();
      const data = result.data;
      notify(`${data.created ? "已创建" : "已继续入库"}：${data.name} +${data.added_quantity}，${selectedLocationName}`);
    });
  }

  function escapeHtml(value) {
    return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
  }

  const button = document.createElement("button");
  button.id = "material-inventory-custom";
  button.innerHTML = `<span>⚙</span><span><b>自定义加入</b><small>设置数量、仓位和备注</small></span>`;
  document.body.append(button);
  button.addEventListener("click", async () => {
    button.disabled = true;
    try { await openModal(); }
    catch (error) { notify(error.message || "无法打开自定义入库", true); }
    finally { button.disabled = false; }
  });
})();
