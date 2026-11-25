// 매장(다점포): 목록·추가·전환·비교
(() => {
  renderNav("stores");
  const S = { stores: [], comparison: null, current: 1, editing: null };

  async function load() {
    const [stores, comparison] = await Promise.all([
      api("/api/stores"), api("/api/stores/comparison"),
    ]);
    S.stores = stores.stores;
    S.current = stores.current;
    S.comparison = comparison;
    renderCompare();
    renderList();
    renderCopyOptions();
  }

  function renderCompare() {
    const rows = S.comparison.stores;
    $("#compare").innerHTML = `<table class="table">
      <thead><tr><th>매장</th><th>오늘 매출</th><th>오늘 주문</th><th>미수금</th><th>이번 달 매출</th><th>메뉴</th><th>직원</th><th>테이블</th></tr></thead>
      <tbody>${rows.map((s) => `<tr class="${s.isCurrent ? "cur" : ""}">
        <td><b>${esc(s.name)}</b>${s.isCurrent ? ' <span class="badge brand">보는 중</span>' : ""}</td>
        <td class="nums"><b>${won(s.todayPaid)}</b></td>
        <td class="nums">${s.todayOrders}</td>
        <td class="nums ${s.todayUnpaid ? "warn" : ""}">${s.todayUnpaid ? won(s.todayUnpaid) : "-"}</td>
        <td class="nums muted">${won(s.monthPaid)}</td>
        <td class="nums">${s.activeMenuCount}/${s.menuCount}</td>
        <td class="nums">${s.staffCount}</td>
        <td class="nums">${s.tableCount}</td>
      </tr>`).join("")}</tbody></table>
      <div class="small muted" style="margin-top:8px">오늘 합계 ${won(S.comparison.totalPaid)} · 이번 달 합계 ${won(S.comparison.totalMonthPaid)}</div>`;
  }

  function renderList() {
    $("#storeCount").textContent = `${S.stores.length}곳`;
    $("#storeList").innerHTML = S.stores.map((s) => `<div class="store-row">
        <div class="grow">
          <div class="row" style="gap:8px"><b style="font-size:16.5px">${esc(s.name)}</b>
            ${s.isCurrent ? '<span class="badge brand">지금 보는 매장</span>' : ""}
            ${s.active ? "" : '<span class="badge red">사용 안 함</span>'}</div>
          <div class="small muted">${[s.tagline, s.address, s.phone].filter(Boolean).map(esc).join(" · ") || "추가 정보 없음"}</div>
        </div>
        <div class="row" style="gap:6px">
          <button class="btn sm ghost" data-edit="${s.id}">정보 수정</button>
          ${s.id === S.current ? "" : `<button class="btn sm" data-switch="${s.id}">이 매장으로</button>`}
          <button class="btn sm ghost" data-toggle="${s.id}" data-active="${s.active ? 1 : 0}">${s.active ? "사용 안 함" : "다시 사용"}</button>
        </div>
      </div>`).join("");
    $$("#storeList [data-edit]").forEach((b) => b.onclick = () => openSheet(
      S.stores.find((x) => x.id === Number(b.dataset.edit))));
    $$("#storeList [data-switch]").forEach((b) => b.onclick = async () => {
      b.disabled = true;
      try {
        await api("/api/stores/switch", { method: "POST", body: { storeId: Number(b.dataset.switch) } });
        toast("매장을 바꿨습니다", "ok");
        location.reload();
      } catch (e) { toast(e.message, "err"); b.disabled = false; }
    });
    $$("#storeList [data-toggle]").forEach((b) => b.onclick = async () => {
      const id = Number(b.dataset.toggle);
      const active = b.dataset.active === "1";
      if (active && !confirm("이 매장을 '사용 안 함'으로 바꿀까요? 주문·QR이 막힙니다. 데이터는 남습니다.")) return;
      try {
        await api(`/api/stores/${id}`, { method: "PATCH", body: { active: !active } });
        toast(active ? "사용 안 함으로 바꿨습니다" : "다시 사용합니다", "ok");
        await load();
      } catch (e) { toast(e.message, "err"); }
    });
  }

  function renderCopyOptions() {
    const sel = $("#stCopy");
    sel.innerHTML = '<option value="">기본 메뉴 새로 깔기</option>' +
      S.stores.map((s) => `<option value="${s.id}">${esc(s.name)} 메뉴 복사</option>`).join("");
  }

  function openSheet(store) {
    S.editing = store || null;
    $("#stTitle").textContent = store ? `${store.name} 정보` : "매장 추가";
    $("#stName").value = store ? store.name : "";
    $("#stTagline").value = store ? store.tagline : "";
    $("#stAddress").value = store ? store.address : "";
    $("#stPhone").value = store ? store.phone : "";
    $("#newOnly").classList.toggle("hidden", !!store);
    $("#stHint").textContent = store
      ? "상호·소개·주소·전화만 바꿉니다. 메뉴·주문 데이터는 그대로입니다."
      : "만든 뒤 위쪽 매장 선택에서 새 매장으로 바꾸면 그 매장 화면이 됩니다.";
    $("#back").classList.add("on");
    $("#storeSheet").classList.add("on");
  }
  function closeSheet() { $("#back").classList.remove("on"); $("#storeSheet").classList.remove("on"); }
  $("#back").onclick = closeSheet;
  $$("[data-close]").forEach((b) => b.onclick = closeSheet);
  $("#addBtn").onclick = () => openSheet(null);

  $("#stSave").onclick = async () => {
    const base = { name: $("#stName").value, tagline: $("#stTagline").value,
                   address: $("#stAddress").value, phone: $("#stPhone").value };
    if (!base.name.trim()) { toast("상호를 넣어 주세요", "err"); return; }
    try {
      if (S.editing) {
        await api(`/api/stores/${S.editing.id}`, { method: "PATCH", body: base });
        toast("매장 정보를 저장했습니다", "ok");
      } else {
        const created = await api("/api/stores", { method: "POST", body: {
          ...base, tables: Number($("#stTables").value || 8),
          copyFrom: $("#stCopy").value ? Number($("#stCopy").value) : null } });
        toast(`'${created.name}' 매장을 만들었습니다`, "ok");
      }
      closeSheet();
      await load();
    } catch (e) { toast(e.message, "err"); }
  };

  load().catch((e) => toast(e.message, "err"));
})();
