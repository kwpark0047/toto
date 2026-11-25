// 재고·재료: 등록/입고/조정, 레시피(메뉴별 소모량), 안전재고 경고, 품절 제안
(() => {
  renderNav("inventory");
  const S = { ingredients: [], suggestions: [], recipes: [], logs: [], menu: [], editing: null,
              moving: null, moveKind: "in", picked: null };

  async function load() {
    const data = await api("/api/inventory");
    S.ingredients = data.ingredients;
    S.suggestions = data.suggestions;
    S.recipes = data.recipes;
    S.logs = data.logs;
    S.menu = data.menu;
    renderStats(data);
    renderWarnings(data.warnings);
    renderSuggestions();
    renderIngredients();
    renderMenuPick();
    renderRecipe();
    renderLogs();
  }

  function renderStats(data) {
    const s = data.summary, w = data.warnings;
    $("#stats").innerHTML = `
      <div class="stat"><div class="k">등록 재료</div><div class="v">${s.ingredientCount}</div><div class="s">단위 ${s.units.length}종</div></div>
      <div class="stat ${w.lowCount ? "warn" : ""}"><div class="k">안전재고 미만</div><div class="v">${w.lowCount}</div>
        <div class="s">${w.outCount ? `재고 0: ${w.outCount}개` : "모두 안전"}</div></div>
      <div class="stat"><div class="k">레시피 설정 메뉴</div><div class="v">${s.recipeMenuCount}</div><div class="s">결제 확인 때 자동 차감</div></div>`;
  }

  function renderWarnings(w) {
    const rows = w.low || [];
    $("#warnList").innerHTML = rows.length ? rows.map((i) => `<div class="wrow">
        <b>${esc(i.name)}</b>
        <span class="nums">${i.stock}${esc(i.unit)} <span class="muted">/ 안전 ${i.safety}${esc(i.unit)}</span></span>
        <button class="btn sm ghost" data-in="${i.id}">입고</button>
      </div>`).join("")
      : '<div class="small muted">안전재고 미만인 재료가 없습니다.</div>';
    $$("#warnList [data-in]").forEach((b) => b.onclick = () => openMove(Number(b.dataset.in), "in"));
  }

  function renderSuggestions() {
    $("#suggestList").innerHTML = S.suggestions.length ? S.suggestions.map((s) => `<div class="srow">
        <div class="grow"><b>${esc(s.menuName)}</b>
          <div class="small muted">${s.ingredients.map((i) => `${esc(i.name)} ${i.stock}/${i.need}${esc(i.unit)}`).join(" · ")}</div></div>
        <button class="btn sm danger" data-sold="${s.menuItemId}">품절로</button>
      </div>`).join("")
      : '<div class="small muted">재고가 모자란 메뉴가 없습니다.</div>';
    $$("#suggestList [data-sold]").forEach((b) => b.onclick = async () => {
      b.disabled = true;
      try {
        await api(`/api/inventory/suggestions/${b.dataset.sold}/soldout`, { method: "POST", body: {} });
        toast("품절로 바꿨습니다", "ok");
        await load();
      } catch (e) { toast(e.message, "err"); b.disabled = false; }
    });
  }

  function renderIngredients() {
    $("#ingCount").textContent = `${S.ingredients.length}개`;
    $("#ingList").innerHTML = S.ingredients.length ? `<table class="table">
      <thead><tr><th>재료</th><th>현재고</th><th>안전재고</th><th>상태</th><th></th></tr></thead>
      <tbody>${S.ingredients.map((i) => `<tr>
        <td><b>${esc(i.name)}</b>${i.memo ? `<div class="small muted">${esc(i.memo)}</div>` : ""}</td>
        <td class="nums"><b>${i.stock}</b> ${esc(i.unit)}</td>
        <td class="nums muted">${i.safety} ${esc(i.unit)}</td>
        <td>${i.out ? '<span class="badge red">재고 0</span>' : i.low ? '<span class="badge amber">부족</span>' : '<span class="badge green">충분</span>'}</td>
        <td class="right nowrap">
          <button class="btn sm ghost" data-in="${i.id}">입고</button>
          <button class="btn sm ghost" data-adj="${i.id}">조정</button>
          <button class="btn sm ghost" data-edit="${i.id}">수정</button>
        </td></tr>`).join("")}</tbody></table>`
      : '<div class="empty"><div class="ico">📦</div>등록된 재료가 없습니다. ‘+ 재료 등록’으로 시작하세요.</div>';
    $$("#ingList [data-in]").forEach((b) => b.onclick = () => openMove(Number(b.dataset.in), "in"));
    $$("#ingList [data-adj]").forEach((b) => b.onclick = () => openMove(Number(b.dataset.adj), "adjust"));
    $$("#ingList [data-edit]").forEach((b) => b.onclick = () => openIngredient(S.ingredients.find((x) => x.id === Number(b.dataset.edit))));
  }

  function renderMenuPick() {
    const sel = $("#menuPick");
    if (!S.menu.length) { sel.innerHTML = '<option value="">메뉴 없음</option>'; return; }
    const current = S.picked || (S.menu[0] && S.menu[0].id);
    sel.innerHTML = S.menu.map((m) => `<option value="${m.id}" ${m.id === current ? "selected" : ""}>${esc(m.name)}${m.soldout ? " (품절)" : ""}</option>`).join("");
    S.picked = current;
  }

  function renderRecipe() {
    const itemId = Number($("#menuPick").value || S.picked);
    S.picked = itemId;
    const mine = S.recipes.filter((r) => r.menuItemId === itemId);
    $("#recipeCurrent").textContent = mine.length
      ? `설정됨: ${mine.map((r) => `${r.ingredientName} ${r.qty}${r.unit}`).join(", ")}`
      : "이 메뉴는 아직 레시피가 없습니다. 결제 확인 때 차감되지 않습니다.";
    $("#recipeRows").innerHTML = (mine.length ? mine : [{ ingredientId: "", qty: "" }]).map(recipeRow).join("");
    bindRecipeRows();
  }

  function recipeRow(line) {
    const opts = ['<option value="">재료 선택</option>'].concat(
      S.ingredients.map((i) => `<option value="${i.id}" ${i.id === Number(line.ingredientId) ? "selected" : ""}>${esc(i.name)} (${esc(i.unit)})</option>`)).join("");
    return `<div class="rrow">
      <select class="select rr-ing">${opts}</select>
      <input class="input rr-qty" type="number" step="0.1" min="0" placeholder="1인분 양" value="${line.qty || ""}">
      <button class="btn sm ghost rr-del" type="button">✕</button>
    </div>`;
  }

  function bindRecipeRows() {
    $$("#recipeRows .rr-del").forEach((b) => b.onclick = () => b.closest(".rrow").remove());
  }

  $("#menuPick").onchange = renderRecipe;
  $("#addRow").onclick = () => {
    $("#recipeRows").insertAdjacentHTML("beforeend", recipeRow({ ingredientId: "", qty: "" }));
    bindRecipeRows();
  };
  $("#saveRecipe").onclick = async () => {
    const lines = $$("#recipeRows .rrow").map((row) => ({
      ingredientId: Number(row.querySelector(".rr-ing").value),
      qty: Number(row.querySelector(".rr-qty").value),
    })).filter((l) => l.ingredientId && l.qty > 0);
    try {
      await api("/api/inventory/recipes", { method: "POST", body: { menuItemId: Number($("#menuPick").value), lines } });
      toast(lines.length ? "레시피를 저장했습니다" : "레시피를 비웠습니다", "ok");
      await load();
    } catch (e) { toast(e.message, "err"); }
  };
  $("#recipeJump").onclick = () => { $("#recipeCard").scrollIntoView({ behavior: "smooth" }); $("#menuPick").focus(); };

  function renderLogs() {
    $("#logList").innerHTML = S.logs.length ? `<table class="table">
      <thead><tr><th>시각</th><th>재료</th><th>구분</th><th>변동</th><th>남은 양</th><th>메모</th></tr></thead>
      <tbody>${S.logs.map((l) => `<tr>
        <td class="nowrap small">${(l.createdAt || "").slice(5, 16)}</td>
        <td><b>${esc(l.name)}</b></td>
        <td><span class="badge ${l.kind === "IN" ? "green" : l.kind === "ADJUST" ? "amber" : "line"}">${esc(l.kindLabel)}</span></td>
        <td class="nums ${l.delta < 0 ? "" : "green"}">${l.delta > 0 ? "+" : ""}${l.delta}${esc(l.unit)}</td>
        <td class="nums muted">${l.stockAfter}${esc(l.unit)}</td>
        <td class="small muted">${esc(l.memo)}${l.orderId ? ` <span class="tiny">#${l.orderId}</span>` : ""}</td>
      </tr>`).join("")}</tbody></table>`
      : '<div class="empty"><div class="ico">🧾</div>기록이 없습니다</div>';
  }

  // ---------------------------------------------------------------- 시트
  function openSheet(id) { $("#back").classList.add("on"); $(id).classList.add("on"); }
  function closeSheets() { $("#back").classList.remove("on"); $$(".sheet").forEach((s) => s.classList.remove("on")); }
  $("#back").onclick = closeSheets;
  $$("[data-close]").forEach((b) => b.onclick = closeSheets);

  function openIngredient(item) {
    S.editing = item || null;
    $("#ingTitle").textContent = item ? "재료 수정" : "재료 등록";
    $("#ingName").value = item ? item.name : "";
    $("#ingUnit").value = item ? item.unit : "개";
    $("#ingStock").value = item ? item.stock : 0;
    $("#ingSafety").value = item ? item.safety : 0;
    $("#ingMemo").value = item ? item.memo : "";
    $("#ingDelete").classList.toggle("hidden", !item);
    openSheet("#ingSheet");
  }
  $("#addBtn").onclick = () => openIngredient(null);

  $("#ingSave").onclick = async () => {
    const body = { name: $("#ingName").value, unit: $("#ingUnit").value,
                   stock: Number($("#ingStock").value || 0), safety: Number($("#ingSafety").value || 0),
                   memo: $("#ingMemo").value };
    try {
      if (S.editing) await api(`/api/inventory/ingredients/${S.editing.id}`, { method: "PATCH", body });
      else await api("/api/inventory/ingredients", { method: "POST", body });
      toast("저장했습니다", "ok");
      closeSheets();
      await load();
    } catch (e) { toast(e.message, "err"); }
  };

  $("#ingDelete").onclick = async () => {
    if (!S.editing) return;
    if (!confirm(`'${S.editing.name}' 재료를 지울까요? 레시피에서도 빠집니다.`)) return;
    try {
      await api(`/api/inventory/ingredients/${S.editing.id}`, { method: "DELETE" });
      toast("지웠습니다", "ok");
      closeSheets();
      await load();
    } catch (e) { toast(e.message, "err"); }
  };

  function openMove(id, kind) {
    const item = S.ingredients.find((x) => x.id === id);
    if (!item) return;
    S.moving = { item, kind };
    $("#moveTitle").textContent = kind === "in" ? "입고" : "재고 조정";
    $("#moveLabel").textContent = kind === "in" ? `입고 수량 (${item.unit})` : `실제 수량 (${item.unit})`;
    $("#moveHint").textContent = kind === "in"
      ? `${item.name} · 지금 ${item.stock}${item.unit} → 입고한 만큼 더합니다.`
      : `${item.name} · 지금 ${item.stock}${item.unit} → 실제로 센 수량으로 맞춥니다(차이 기록).`;
    $("#moveQty").value = kind === "in" ? "" : item.stock;
    $("#moveMemo").value = "";
    openSheet("#moveSheet");
    $("#moveQty").focus();
  }

  $("#moveSave").onclick = async () => {
    if (!S.moving) return;
    const { item, kind } = S.moving;
    const qty = Number($("#moveQty").value);
    if (!Number.isFinite(qty) || qty < 0 || (kind === "in" && qty <= 0)) {
      toast("수량을 확인해 주세요", "err"); return;
    }
    try {
      const url = kind === "in"
        ? `/api/inventory/ingredients/${item.id}/in`
        : `/api/inventory/ingredients/${item.id}/adjust`;
      const body = kind === "in" ? { qty, memo: $("#moveMemo").value } : { stock: qty, memo: $("#moveMemo").value };
      await api(url, { method: "POST", body });
      toast(kind === "in" ? "입고를 기록했습니다" : "재고를 맞췄습니다", "ok");
      closeSheets();
      await load();
    } catch (e) { toast(e.message, "err"); }
  };

  load().catch((e) => toast(e.message, "err"));
})();
