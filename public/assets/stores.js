// 매장(다점포): 통합 합계·목록·추가/전환·메뉴 복사·직원 이동
(() => {
  renderNav("stores");
  const S = { stores: [], comparison: null, summary: null, staff: [], transfers: [],
              current: 1, editing: null, sourceMenu: null };

  async function load() {
    const [stores, comparison, summary, staff, transfers] = await Promise.all([
      api("/api/stores"),
      api("/api/stores/comparison"),
      api("/api/stores/summary"),
      api("/api/stores/staff"),
      api("/api/stores/transfers"),
    ]);
    S.stores = stores.stores;
    S.current = stores.current;
    S.comparison = comparison;
    S.summary = summary;
    S.staff = staff.staff || [];
    S.transfers = transfers.transfers || [];
    renderSummary();
    renderCompare();
    renderList();
    renderLog();
    renderCopyOptions();
  }

  function renderSummary() {
    const t = (S.summary && S.summary.totals) || {};
    const head = $("#summaryDate");
    if (head) head.textContent = S.summary ? `${S.summary.date} · ${t.storeCount || 0}개 매장` : "–";
    const stats = $("#summaryStats");
    if (stats) {
      stats.innerHTML = `
        <div class="card stat hot">
          <div class="k">오늘 통합 매출</div>
          <div class="v nums">${won(t.todayPaid || 0)}</div>
          <div class="s">주문 ${t.todayOrders || 0}건 · 매장 ${t.storeCount || 0}곳</div>
        </div>
        <div class="card stat">
          <div class="k">이번 달 매출</div>
          <div class="v nums">${won(t.monthPaid || 0)}</div>
          <div class="s">주문 ${t.monthOrders || 0}건</div>
        </div>
        <div class="card stat">
          <div class="k">누적 매출</div>
          <div class="v nums">${won(t.totalPaid || 0)}</div>
          <div class="s">전체 기간 결제 확인</div>
        </div>
        <div class="card stat">
          <div class="k">누적 주문</div>
          <div class="v nums">${t.totalOrders || 0}<span style="font-size:15px;font-weight:700">건</span></div>
          <div class="s">취소 포함 전체 주문</div>
        </div>`;
    }
    const share = $("#shareBox");
    if (!share) return;
    const rows = (S.summary && S.summary.stores) || [];
    const max = Math.max(1, ...rows.map((r) => r.monthPaid));
    share.innerHTML = rows.map((r) => `
      <div class="share-row">
        <span class="nm">${esc(r.name)}${r.isCurrent ? ' <span class="badge brand">보는 중</span>' : ""}</span>
        <span class="bar"><i style="width:${Math.round((r.monthPaid / max) * 100)}%"></i></span>
        <span class="val nums">${won(r.monthPaid)} <em>${r.monthShare || 0}%</em></span>
      </div>`).join("") || '<div class="small muted">매출 기록이 아직 없습니다.</div>';
  }

  function renderCompare() {
    const rows = S.comparison.stores;
    $("#compare").innerHTML = `<div class="tablewrap"><table class="table">
      <thead><tr><th>매장</th><th>오늘 매출</th><th>오늘 주문</th><th>미수금</th><th>이번 달</th><th>누적</th><th>비중</th><th>메뉴</th><th>직원</th><th>테이블</th></tr></thead>
      <tbody>${rows.map((s) => {
        const sum = ((S.summary && S.summary.stores) || []).find((x) => x.id === s.id) || {};
        return `<tr class="${s.isCurrent ? "cur" : ""}">
          <td><b>${esc(s.name)}</b>${s.isCurrent ? ' <span class="badge brand">보는 중</span>' : ""}</td>
          <td class="nums"><b>${won(s.todayPaid)}</b></td>
          <td class="nums">${s.todayOrders}</td>
          <td class="nums ${s.todayUnpaid ? "warn" : ""}">${s.todayUnpaid ? won(s.todayUnpaid) : "-"}</td>
          <td class="nums">${won(s.monthPaid)}</td>
          <td class="nums muted">${won(sum.totalPaid || 0)}</td>
          <td class="nums">${sum.monthShare != null ? sum.monthShare + "%" : "-"}</td>
          <td class="nums">${s.activeMenuCount}/${s.menuCount}</td>
          <td class="nums">${s.staffCount}</td>
          <td class="nums">${s.tableCount}</td>
        </tr>`;
      }).join("")}</tbody></table></div>
      <div class="small muted" style="margin-top:8px">오늘 합계 ${won(S.comparison.totalPaid)} · 이번 달 합계 ${won(S.comparison.totalMonthPaid)}</div>`;
  }

  function renderList() {
    $("#storeCount").textContent = `${S.stores.length}곳`;
    $("#storeList").innerHTML = S.stores.map((s) => `<div class="store-row">
        <div class="grow">
          <div class="row" style="gap:8px;flex-wrap:wrap"><b style="font-size:16.5px">${esc(s.name)}</b>
            ${s.isCurrent ? '<span class="badge brand">지금 보는 매장</span>' : ""}
            ${s.active ? "" : '<span class="badge red">사용 안 함</span>'}</div>
          <div class="small muted">${[s.tagline, s.address, s.phone].filter(Boolean).map(esc).join(" · ") || "추가 정보 없음"}</div>
        </div>
        <div class="row" style="gap:6px;flex-wrap:wrap">
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

  function renderLog() {
    const box = $("#transferLog");
    if (!box) return;
    if (!S.transfers.length) {
      box.innerHTML = '<span class="small muted">아직 이동 이력이 없습니다.</span>';
      return;
    }
    box.innerHTML = `<div class="tablewrap"><table class="table">
      <thead><tr><th>직원</th><th>이동</th><th>메모</th><th>시각</th></tr></thead>
      <tbody>${S.transfers.map((t) => `<tr>
        <td><b>${esc(t.staffName)}</b></td>
        <td>${esc(t.fromName)} → <b>${esc(t.toName)}</b></td>
        <td class="muted">${esc(t.note || "-")}</td>
        <td class="nums muted">${esc(t.createdAt)}</td>
      </tr>`).join("")}</tbody></table></div>`;
  }

  function renderCopyOptions() {
    const sel = $("#stCopy");
    if (sel) {
      sel.innerHTML = '<option value="">기본 메뉴 새로 깔기</option>' +
        S.stores.map((s) => `<option value="${s.id}">${esc(s.name)} 메뉴 복사</option>`).join("");
    }
    const from = $("#cpFrom");
    const to = $("#cpTo");
    if (from) from.innerHTML = S.stores.map((s) => `<option value="${s.id}">${esc(s.name)}</option>`).join("");
    if (to) {
      to.innerHTML = S.stores.map((s) => `<option value="${s.id}">${esc(s.name)}</option>`).join("");
      const other = S.stores.find((s) => s.id !== S.current);
      to.value = String((other || S.stores[0] || {}).id || "");
    }
    const mvTo = $("#mvTo");
    if (mvTo) mvTo.innerHTML = S.stores.filter((s) => s.active)
      .map((s) => `<option value="${s.id}">${esc(s.name)}</option>`).join("");
    const mvStaff = $("#mvStaff");
    if (mvStaff) {
      mvStaff.innerHTML = S.staff.map((p) =>
        `<option value="${p.id}" data-store="${p.storeId}">${esc(p.name)} (${esc(p.username)}) · ${esc(p.storeName || "")}${p.active ? "" : " · 비활성"}</option>`).join("");
    }
  }

  // ---------- 매장 추가/수정
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
    openPanel("storeSheet");
  }
  function openPanel(id) {
    $("#back").classList.add("on");
    $$(".sheet").forEach((s) => s.classList.remove("on"));
    const el = document.getElementById(id);
    if (el) el.classList.add("on");
  }
  function closeSheet() {
    $("#back").classList.remove("on");
    $$(".sheet").forEach((s) => s.classList.remove("on"));
  }
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

  // ---------- 메뉴 복사
  async function loadSourceMenu() {
    const sid = $("#cpFrom").value;
    const box = $("#cpItems");
    const state = $("#cpPickState");
    if (!sid) return;
    box.innerHTML = "불러오는 중…";
    try {
      const data = await api(`/api/stores/menu?store=${encodeURIComponent(sid)}`);
      S.sourceMenu = data;
      box.innerHTML = (data.items || []).map((i) => `<label class="cp-item">
        <input type="checkbox" value="${i.id}" checked>
        <span><b>${esc(i.name)}</b> <span class="muted">${won(i.price)} · ${esc(i.categoryName || "")}</span></span>
      </label>`).join("") || '<span class="small muted">이 매장에 메뉴가 없습니다.</span>';
      if (state) state.textContent = `전체 ${data.items.length}개`;
    } catch (e) {
      box.innerHTML = `<span class="small">${esc(e.message)}</span>`;
    }
  }

  const copyBtn = $("#copyBtn");
  if (copyBtn) copyBtn.onclick = () => {
    const msg = $("#cpMsg");
    if (msg) msg.textContent = "";
    const from = $("#cpFrom");
    if (from && !from.value) from.value = String(S.current);
    openPanel("copySheet");
    loadSourceMenu();
  };
  const cpFrom = $("#cpFrom");
  if (cpFrom) cpFrom.onchange = loadSourceMenu;
  const cpScope = $("#cpScope");
  if (cpScope) cpScope.onchange = () => {
    const box = $("#cpPickBox");
    if (box) box.style.display = cpScope.value === "pick" ? "" : "none";
  };
  const cpSave = $("#cpSave");
  if (cpSave) cpSave.onclick = async () => {
    const msg = $("#cpMsg");
    msg.textContent = "";
    const from = Number($("#cpFrom").value);
    const to = Number($("#cpTo").value);
    if (!from || !to) { msg.textContent = "원본과 대상 매장을 골라 주세요."; return; }
    if (from === to) { msg.textContent = "서로 다른 매장을 골라 주세요."; return; }
    const picked = $$("#cpItems input:checked").map((i) => Number(i.value));
    const ids = $("#cpScope").value === "pick" ? picked : null;
    if ($("#cpScope").value === "pick" && !ids.length) { msg.textContent = "복사할 메뉴를 골라 주세요."; return; }
    cpSave.disabled = true;
    try {
      const r = await api("/api/stores/copy-menu", { method: "POST", body: {
        fromStore: from, toStore: to, itemIds: ids, onDuplicate: $("#cpDup").value } });
      toast(`메뉴 ${r.created}개 추가 · ${r.updated}개 덮어씀 · ${r.skipped}개 건너뜀`, "ok");
      closeSheet();
      await load();
    } catch (e) {
      msg.textContent = e.message;
    } finally { cpSave.disabled = false; }
  };

  // ---------- 직원 이동
  const moveBtn = $("#moveBtn");
  if (moveBtn) moveBtn.onclick = () => {
    const msg = $("#mvMsg");
    if (msg) msg.textContent = "";
    openPanel("moveSheet");
    syncMoveTargets();
  };
  const mvStaff = $("#mvStaff");
  function syncMoveTargets() {
    const sel = mvStaff && mvStaff.selectedOptions && mvStaff.selectedOptions[0];
    const fromStore = sel ? Number(sel.dataset.store) : 0;
    const to = $("#mvTo");
    if (!to) return;
    Array.from(to.options).forEach((o) => { o.disabled = Number(o.value) === fromStore; });
    const enabled = Array.from(to.options).find((o) => !o.disabled);
    if (enabled) to.value = enabled.value;
  }
  if (mvStaff) mvStaff.onchange = syncMoveTargets;
  const mvSave = $("#mvSave");
  if (mvSave) mvSave.onclick = async () => {
    const msg = $("#mvMsg");
    msg.textContent = "";
    const staffId = Number($("#mvStaff").value);
    const toStore = Number($("#mvTo").value);
    if (!staffId || !toStore) { msg.textContent = "직원과 옮길 매장을 골라 주세요."; return; }
    mvSave.disabled = true;
    try {
      const r = await api("/api/stores/transfer-staff", { method: "POST", body: {
        staffId, toStore, note: $("#mvNote").value } });
      toast(`${r.staff.name} 님을 ${r.toStore.name}(으)로 옮겼습니다`, "ok");
      closeSheet();
      await load();
    } catch (e) {
      msg.textContent = e.message;
    } finally { mvSave.disabled = false; }
  };

  const cpPick = $("#cpPickBox");
  if (cpPick) cpPick.style.display = "none";

  load().catch((e) => toast(e.message, "err"));
})();
