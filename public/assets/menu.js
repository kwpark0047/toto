// 메뉴 관리: 메뉴·카테고리 CRUD, 가격, 품절, 순서, 사진, 옵션
(() => {
  renderNav("menu");
  const S = { categories: [], items: [], editing: null, photo: null };

  const catName = (id) => S.categories.find((c) => c.id === id)?.name || "";

  async function load() {
    const data = await api("/api/menu/all");
    S.categories = data.categories;
    S.items = data.items;
    render();
  }

  function render() {
    $("#catChips").innerHTML = S.categories
      .map((c) => `<span class="chip">${esc(c.name)} <span class="muted">${c.itemCount}</span></span>`)
      .join("");
    $("#menuSections").innerHTML = S.categories
      .map((c) => {
        const items = S.items.filter((i) => i.categoryId === c.id);
        return `<section class="msec">
          <div class="hd"><h2>${esc(c.name)}</h2><span class="badge">${items.length}개</span></div>
          ${items.length ? items.map(rowHTML).join("") : `<div class="mrow muted small">메뉴가 없습니다. ‘+ 메뉴 추가’로 넣어 주세요.</div>`}
        </section>`;
      })
      .join("");
    $$("#menuSections [data-edit]").forEach((b) => b.onclick = () => openItem(Number(b.dataset.edit)));
    $$("#menuSections [data-del]").forEach((b) => b.onclick = () => delItem(Number(b.dataset.del)));
    $$("#menuSections [data-move]").forEach((b) => b.onclick = () => moveItem(Number(b.dataset.move), b.dataset.dir));
    $$("#menuSections [data-feat]").forEach((b) => b.onclick = () => toggleFeatured(Number(b.dataset.feat)));
    $$("#menuSections [data-soldout]").forEach((b) => b.onchange = () => toggleSoldout(Number(b.dataset.soldout), b.checked));
  }

  function rowHTML(it) {
    const img = it.image
      ? `<img src="${esc(it.image)}" alt="" loading="lazy">`
      : "🍽️";
    return `<div class="mrow ${it.soldout ? "out" : ""}">
      <div class="th">${img}</div>
      <div class="info">
        <div class="nm">${it.featured ? '<span class="badge brand">★ 추천</span>' : ""}${esc(it.name)}
          ${it.soldout ? '<span class="badge red">품절</span>' : ""}
          ${it.options?.length ? `<span class="badge line">옵션 ${it.options.length}</span>` : ""}
          ${(it.allergens || []).length ? `<span class="badge amber">알레르기 ${it.allergens.length}</span>` : `<span class="badge line">알레르기 정보 없음</span>`}
        </div>
        <div class="ds">${esc(it.description || "설명 없음")}</div>
        <div class="pr nums">${won(it.price)}</div>
      </div>
      <div class="acts">
        <button class="icon-btn" data-move="${it.id}" data-dir="up" title="위로" aria-label="위로">↑</button>
        <button class="icon-btn" data-move="${it.id}" data-dir="down" title="아래로" aria-label="아래로">↓</button>
        <label class="switch"><input type="checkbox" data-soldout="${it.id}" ${it.soldout ? "checked" : ""}> 품절</label>
        <button class="btn sm ghost" data-feat="${it.id}" title="추천 메뉴로">${it.featured ? "★" : "☆"}</button>
        <button class="btn sm" data-edit="${it.id}">수정</button>
        <button class="btn sm danger" data-del="${it.id}">삭제</button>
      </div>
    </div>`;
  }

  // ---------------- 메뉴 편집 시트
  async function toggleFeatured(id) {
    const it = S.items.find((i) => i.id === id);
    if (!it) return;
    try {
      await api(`/api/items/${id}/featured`, { method: "POST", body: { featured: !it.featured } });
      toast(!it.featured ? "추천 메뉴로 지정했습니다" : "추천에서 뺐습니다", "ok");
      await load();
    } catch (e) { toast(e.message, "err"); }
  }

  function openItem(item) {
    S.editing = item || null;
    S.photo = null;
    $("#itemTitle").textContent = item ? "메뉴 수정" : "메뉴 추가";
    $("#delItem").classList.toggle("hidden", !item);
    $("#fName").value = item?.name || "";
    $("#fPrice").value = item?.price ?? "";
    $("#fDesc").value = item?.description || "";
    $("#fSoldout").checked = !!item?.soldout;
    $("#fFeatured").checked = !!item?.featured;
    $("#fNote").value = item?.featuredNote || "";
    $("#fOrigin").value = item?.origin || "";
    renderI18n(item?.i18n || {});
    $("#fSpice").value = String(item?.spice || 0);
    renderAllergens(item?.allergens || []);
    $("#fCat").innerHTML = S.categories
      .map((c) => `<option value="${c.id}" ${item?.categoryId === c.id ? "selected" : ""}>${esc(c.name)}</option>`)
      .join("");
    setPreview(item?.image || "");
    $("#phClear").classList.toggle("hidden", !item?.image);
    renderOpts(item?.options || []);
    openSheet("itemSheet");
  }

  const ALLERGENS = ["난류", "우유", "메밀", "땅콩", "대두", "밀", "고등어", "게", "새우",
    "돼지고기", "복숭아", "토마토", "아황산류", "호두", "닭고기", "소고기", "오징어", "조개류"];

  const LANGS = [["en", "English"], ["zh", "中文"], ["ja", "日本語"]];

  function renderI18n(data) {
    $("#i18nBox").innerHTML = LANGS.map(([code, label]) => `
      <div class="row" style="gap:6px;margin-bottom:6px">
        <span class="badge" style="min-width:64px;justify-content:center">${label}</span>
        <input class="input" data-i18n="${code}" data-k="name" placeholder="메뉴 이름" value="${esc((data[code] || {}).name || "")}">
        <input class="input" data-i18n="${code}" data-k="description" placeholder="설명" value="${esc((data[code] || {}).description || "")}">
      </div>`).join("");
  }

  function collectI18n() {
    const out = {};
    $$("#i18nBox [data-i18n]").forEach((el) => {
      const code = el.dataset.i18n;
      out[code] = out[code] || {};
      out[code][el.dataset.k] = el.value.trim();
    });
    return out;
  }

  function renderAllergens(selected) {
    $("#fAllergens").innerHTML = ALLERGENS.map((a) =>
      `<label class="chip" style="min-height:36px;font-size:14px"><input type="checkbox" data-allergen="${a}" ${selected.includes(a) ? "checked" : ""} style="width:18px;height:18px;accent-color:var(--brand)"> ${a}</label>`).join("");
  }

  function collectAllergens() {
    return $$("#fAllergens [data-allergen]").filter((el) => el.checked).map((el) => el.dataset.allergen);
  }

  function setPreview(src) {
    $("#phPrev").innerHTML = src ? `<img src="${esc(src)}" alt="">` : "📷";
  }

  function renderOpts(groups) {
    $("#optEditor").innerHTML = groups
      .map((g, i) => `<div class="og" data-i="${i}">
        <div class="row">
          <input class="input" data-gname placeholder="옵션 이름 (예: 맵기)" value="${esc(g.name || "")}">
          <button class="rm" data-rmopt="${i}" aria-label="옵션 삭제">✕</button>
        </div>
        <div class="row">
          <input class="input" data-gchoices placeholder="선택지 (쉼표로 구분)" value="${esc((g.choices || []).join(", "))}">
        </div>
        <div class="row">
          <input class="input" data-gdefault placeholder="기본값" value="${esc(g.default || "")}">
        </div>
        <p class="choices">선택지를 쉼표로 나눠 적으면 고객 화면에 버튼으로 나옵니다.</p>
      </div>`)
      .join("");
    $$("#optEditor [data-rmopt]").forEach((b) => b.onclick = () => {
      const idx = Number(b.dataset.rmopt);
      const cur = collectOpts();
      cur.splice(idx, 1);
      renderOpts(cur);
    });
  }

  function collectOpts() {
    return $$("#optEditor .og").map((og) => ({
      name: og.querySelector("[data-gname]").value.trim(),
      choices: og.querySelector("[data-gchoices]").value.split(",").map((s) => s.trim()).filter(Boolean),
      default: og.querySelector("[data-gdefault]").value.trim(),
    })).filter((g) => g.name && g.choices.length);
  }

  $("#addOpt").onclick = () => {
    if ($$("#optEditor .og").length >= 3) return toast("옵션은 3개까지 넣을 수 있습니다", "err");
    const cur = collectOpts();
    cur.push({ name: "", choices: [], default: "" });
    renderOpts(cur);
  };

  $("#phFile").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    if (file.size > 12 * 1024 * 1024) return toast("12MB 이하 사진을 골라 주세요", "err");
    try {
      S.photo = await fileToJpeg(file, 900, 0.82);
      setPreview(S.photo);
      $("#phClear").classList.remove("hidden");
    } catch (err) {
      toast("사진을 읽지 못했습니다", "err");
    }
  });

  $("#phClear").onclick = () => {
    S.photo = "remove";
    setPreview("");
    $("#phClear").classList.add("hidden");
  };

  function fileToJpeg(file, maxW, q) {
    return new Promise((resolve, reject) => {
      const url = URL.createObjectURL(file);
      const img = new Image();
      img.onload = () => {
        const scale = Math.min(1, maxW / img.width);
        const canvas = document.createElement("canvas");
        canvas.width = Math.round(img.width * scale);
        canvas.height = Math.round(img.height * scale);
        const ctx = canvas.getContext("2d");
        ctx.fillStyle = "#fff";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        URL.revokeObjectURL(url);
        resolve(canvas.toDataURL("image/jpeg", q));
      };
      img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("이미지 오류")); };
      img.src = url;
    });
  }

  $("#saveItem").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    const body = {
      name: $("#fName").value.trim(),
      price: Number($("#fPrice").value || 0),
      categoryId: Number($("#fCat").value),
      description: $("#fDesc").value.trim(),
      soldout: $("#fSoldout").checked,
      options: collectOpts(),
      origin: $("#fOrigin").value.trim(),
      allergens: collectAllergens(),
      spice: Number($("#fSpice").value || 0),
      i18n: collectI18n(),
      image: S.editing?.image || "",
    };
    if (!body.name) return toast("메뉴 이름을 입력해 주세요", "err");
    if (!body.price) return toast("가격을 입력해 주세요", "err");
    if (S.photo === "remove") body.image = "";
    btn.disabled = true;
    btn.textContent = "저장 중…";
    try {
      let item;
      if (S.editing) {
        item = await api(`/api/items/${S.editing.id}`, { method: "PATCH", body });
      } else {
        item = await api("/api/items", { method: "POST", body });
      }
      if (S.photo && S.photo !== "remove") {
        await api(`/api/items/${item.id}/photo`, { method: "POST", body: { dataUrl: S.photo } });
      }
      await api(`/api/items/${item.id}/featured`, { method: "POST", body: {
        featured: $("#fFeatured").checked, note: $("#fNote").value.trim() } });
      toast(S.editing ? "메뉴를 수정했습니다" : "메뉴를 추가했습니다", "ok");
      closeAll();
      await load();
    } catch (err) {
      toast(err.message, "err");
    } finally {
      btn.disabled = false;
      btn.textContent = "저장";
    }
  });

  $("#delItem").addEventListener("click", () => S.editing && delItem(S.editing.id));

  async function delItem(id) {
    const it = S.items.find((i) => i.id === id);
    if (!confirm(`'${it?.name || "이 메뉴"}'을(를) 삭제할까요?\n지난 주문 기록에는 그대로 남습니다.`)) return;
    try {
      await api(`/api/items/${id}`, { method: "DELETE" });
      toast("삭제했습니다");
      closeAll();
      await load();
    } catch (e) { toast(e.message, "err"); }
  }

  async function moveItem(id, dir) {
    try {
      await api(`/api/items/${id}/move`, { method: "POST", body: { dir } });
      await load();
    } catch (e) { toast(e.message, "err"); }
  }

  async function toggleSoldout(id, soldout) {
    try {
      await api(`/api/items/${id}/soldout`, { method: "POST", body: { soldout } });
      toast(soldout ? "품절로 표시했습니다" : "품절을 풀었습니다", "ok");
      await load();
    } catch (e) { toast(e.message, "err"); }
  }

  // ---------------- 카테고리 관리
  $("#catManage").onclick = () => { renderCats(); openSheet("catSheet"); };

  function renderCats() {
    $("#catList").innerHTML = S.categories
      .map((c) => `<div class="cl" data-cat="${c.id}">
        <input class="input" value="${esc(c.name)}" data-cname>
        <span class="cnt">${c.itemCount}개</span>
        <button class="icon-btn" data-cmove="up" data-id="${c.id}">↑</button>
        <button class="icon-btn" data-cmove="down" data-id="${c.id}">↓</button>
        <button class="btn sm danger" data-cdel="${c.id}">삭제</button>
      </div>`)
      .join("");
    $$("#catList [data-cname]").forEach((inp) => {
      inp.onchange = async () => {
        const id = Number(inp.closest("[data-cat]").dataset.cat);
        try {
          await api(`/api/categories/${id}`, { method: "PATCH", body: { name: inp.value } });
          toast("이름을 바꿨습니다", "ok");
          await load();
          renderCats();
        } catch (e) { toast(e.message, "err"); }
      };
    });
    $$("#catList [data-cmove]").forEach((b) => b.onclick = async () => {
      await api(`/api/categories/${b.dataset.id}/move`, { method: "POST", body: { dir: b.dataset.cmove } });
      await load();
      renderCats();
    });
    $$("#catList [data-cdel]").forEach((b) => b.onclick = async () => {
      if (!confirm("이 카테고리를 삭제할까요? 메뉴가 들어 있으면 지울 수 없습니다.")) return;
      try {
        await api(`/api/categories/${b.dataset.cdel}`, { method: "DELETE" });
        toast("카테고리를 삭제했습니다");
        await load();
        renderCats();
      } catch (e) { toast(e.message, "err"); }
    });
  }

  $("#addCat").onclick = async () => {
    const name = $("#newCatName").value.trim();
    if (!name) return toast("이름을 입력해 주세요", "err");
    try {
      await api("/api/categories", { method: "POST", body: { name } });
      $("#newCatName").value = "";
      toast("카테고리를 추가했습니다", "ok");
      await load();
      renderCats();
    } catch (e) { toast(e.message, "err"); }
  };

  // ---------------- 시트
  function openSheet(id) {
    $("#back").classList.add("on");
    $$(".sheet").forEach((s) => s.classList.remove("on"));
    document.getElementById(id).classList.add("on");
  }
  function closeAll() {
    $("#back").classList.remove("on");
    $$(".sheet").forEach((s) => s.classList.remove("on"));
  }
  $("#back").onclick = closeAll;
  $$("[data-close]").forEach((b) => b.onclick = closeAll);
  $("#addItem").onclick = () => openItem(null);

  load().catch((e) => toast(e.message, "err"));
})();
