// 예약 관리: 월 캘린더 · 일자별 목록 · 상태(확정/도착/노쇼/취소) · 테이블 배정
(() => {
  renderNav("reservations");
  const S = { month: "", day: "", data: null, tables: [], reserveUrl: "/reserve" };
  const STATUS_CLASS = { PENDING: "amber", CONFIRMED: "brand", ARRIVED: "green", NOSHOW: "red", CANCELED: "line" };

  const todayISO = () => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  };

  async function load() {
    const p = new URLSearchParams();
    if (S.month) p.set("month", S.month);
    const data = await api("/api/reservations?" + p.toString());
    S.data = data;
    S.tables = data.tables || [];
    if (!S.day) S.day = data.today.date;
    renderStats(data.today);
    renderCalendar();
    renderDay();
    renderUpcoming();
    fillTableOptions();
  }

  function renderStats(t) {
    $("#stats").innerHTML = `
      <div class="stat hot"><div class="k">오늘 예약</div><div class="v">${t.count}</div>
        <div class="s">신청·확정 ${t.activeCount}건 · ${t.partyTotal}명</div></div>
      <div class="stat ${t.pendingCount ? "warn" : ""}"><div class="k">확정 대기(신청)</div><div class="v">${t.pendingCount}</div>
        <div class="s">손님이 신청한 건</div></div>
      <div class="stat"><div class="k">도착</div><div class="v">${t.arrivedCount}</div><div class="s">오늘</div></div>`;
  }

  function renderCalendar() {
    const c = S.data.calendar;
    S.month = c.month;
    const [y, m] = c.month.split("-").map(Number);
    $("#monthTitle").textContent = `${y}년 ${m}월`;
    const first = new Date(y, m - 1, 1);
    const days = new Date(y, m, 0).getDate();
    const offset = first.getDay();
    const cells = [];
    for (let i = 0; i < offset; i++) cells.push('<div class="cd empty"></div>');
    for (let d = 1; d <= days; d++) {
      const iso = `${c.month}-${String(d).padStart(2, "0")}`;
      const info = c.days[iso] || { total: 0, byStatus: {} };
      const pending = info.byStatus.PENDING || 0;
      const confirmed = info.byStatus.CONFIRMED || 0;
      cells.push(`<button class="cd ${iso === S.day ? "on" : ""} ${iso === todayISO() ? "today" : ""}" data-day="${iso}">
        <span class="dnum">${d}</span>
        ${info.total ? `<span class="dots">${pending ? `<i class="p" title="신청 ${pending}"></i>` : ""}${confirmed ? `<i class="c" title="확정 ${confirmed}"></i>` : ""}</span>
          <span class="cnt">${info.total}</span>` : ""}
      </button>`);
    }
    $("#cal").innerHTML = `<div class="cweek">${["일", "월", "화", "수", "목", "금", "토"].map((w) => `<span>${w}</span>`).join("")}</div>
      <div class="cgrid">${cells.join("")}</div>`;
    $$("#cal [data-day]").forEach((b) => b.onclick = () => { S.day = b.dataset.day; renderCalendar(); renderDay(); });
  }

  function rowsForDay() {
    return (S.data.reservations || []).filter((r) => r.date === S.day);
  }

  function renderDay() {
    $("#dayTitle").textContent = S.day === todayISO() ? "오늘 예약" : `${S.day} 예약`;
    const rows = rowsForDay();
    $("#dayCount").textContent = `${rows.length}건`;
    $("#dayList").innerHTML = rows.length ? rows.map((r) => `<article class="rescard ${r.status}">
        <div class="rt"><b>${r.time}</b><span class="badge ${STATUS_CLASS[r.status] || ""}">${esc(r.statusLabel)}</span>
          ${r.partySize ? `<span class="badge line">${r.partySize}명</span>` : ""}
          ${r.tableLabel ? `<span class="badge line">${esc(r.tableLabel)}</span>` : ""}</div>
        <div class="rn"><b>${esc(r.name)}</b> <span class="muted small">${esc(r.phone)}</span></div>
        ${r.memo ? `<div class="small muted">📝 ${esc(r.memo)}</div>` : ""}
        <div class="row wrap" style="gap:6px;margin-top:8px">
          ${r.status === "PENDING" ? `<button class="btn sm primary" data-st="CONFIRMED" data-id="${r.id}">확정</button>` : ""}
          ${["PENDING", "CONFIRMED"].includes(r.status) ? `<button class="btn sm green" data-st="ARRIVED" data-id="${r.id}">도착</button>
            <button class="btn sm ghost" data-st="NOSHOW" data-id="${r.id}">노쇼</button>
            <button class="btn sm danger" data-st="CANCELED" data-id="${r.id}">취소</button>` : ""}
          ${["PENDING", "CONFIRMED"].includes(r.status) ? `<select class="select sm" data-table="${r.id}" style="max-width:130px">
            <option value="">테이블 배정</option>
            ${S.tables.map((t) => `<option value="${t.id}" ${t.id === r.tableId ? "selected" : ""}>${esc(t.label)}</option>`).join("")}
          </select>` : ""}
        </div>
      </article>`).join("")
      : '<div class="empty"><div class="ico">📅</div>이 날은 예약이 없습니다</div>';
    $$("#dayList [data-st]").forEach((b) => b.onclick = () => setStatus(Number(b.dataset.id), b.dataset.st));
    $$("#dayList [data-table]").forEach((sel) => sel.onchange = async () => {
      if (!sel.value) return;
      try {
        await api(`/api/reservations/${sel.dataset.table}/table`, { method: "POST", body: { tableId: Number(sel.value) } });
        toast("테이블을 배정했습니다", "ok");
        await load();
      } catch (e) { toast(e.message, "err"); }
    });
  }

  async function setStatus(id, status) {
    try {
      await api(`/api/reservations/${id}/status`, { method: "POST", body: { status } });
      toast("상태를 바꿨습니다", "ok");
      await load();
    } catch (e) { toast(e.message, "err"); }
  }

  function renderUpcoming() {
    const rows = S.data.upcoming || [];
    $("#upcoming").innerHTML = rows.length ? `<table class="table">
      <thead><tr><th>날짜·시간</th><th>이름</th><th>인원</th><th>상태</th><th>연락처</th></tr></thead>
      <tbody>${rows.map((r) => `<tr><td class="nowrap"><b>${r.date.slice(5)}</b> ${r.time}</td>
        <td>${esc(r.name)}${r.memo ? `<div class="small muted">${esc(r.memo)}</div>` : ""}</td>
        <td class="nums">${r.partySize}</td>
        <td><span class="badge ${STATUS_CLASS[r.status] || ""}">${esc(r.statusLabel)}</span></td>
        <td class="small muted">${esc(r.phone)}</td></tr>`).join("")}</tbody></table>`
      : '<div class="small muted">7일 안에 예약이 없습니다.</div>';
  }

  function fillTableOptions() {
    $("#rsTable").innerHTML = '<option value="">없음</option>' +
      S.tables.map((t) => `<option value="${t.id}">${esc(t.label)} (${t.seats}석)</option>`).join("");
  }

  $("#prevMonth").onclick = () => {
    const [y, m] = S.month.split("-").map(Number);
    const d = new Date(y, m - 2, 1);
    S.month = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    load().catch((e) => toast(e.message, "err"));
  };
  $("#nextMonth").onclick = () => {
    const [y, m] = S.month.split("-").map(Number);
    const d = new Date(y, m, 1);
    S.month = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    load().catch((e) => toast(e.message, "err"));
  };
  $("#todayMonth").onclick = () => { S.month = ""; S.day = todayISO(); load().catch((e) => toast(e.message, "err")); };

  function openSheet() { $("#rsDate").value = S.day || todayISO(); $("#back").classList.add("on"); $("#resSheet").classList.add("on"); }
  function closeSheets() { $("#back").classList.remove("on"); $$(".sheet").forEach((s) => s.classList.remove("on")); }
  $("#back").onclick = closeSheets;
  $$("[data-close]").forEach((b) => b.onclick = closeSheets);
  $("#addBtn").onclick = openSheet;

  $("#rsSave").onclick = async () => {
    const body = { date: $("#rsDate").value, time: $("#rsTime").value, party: Number($("#rsParty").value || 2),
                   name: $("#rsName").value, phone: $("#rsPhone").value, memo: $("#rsMemo").value,
                   tableId: $("#rsTable").value ? Number($("#rsTable").value) : null, status: "CONFIRMED" };
    try {
      await api("/api/reservations", { method: "POST", body });
      toast("예약을 등록했습니다", "ok");
      closeSheets();
      S.day = body.date;
      await load();
    } catch (e) { toast(e.message, "err"); }
  };

  $("#copyLink").onclick = async () => {
    try { await navigator.clipboard.writeText(S.reserveUrl); toast("신청 링크를 복사했습니다", "ok"); }
    catch (e) { toast(S.reserveUrl, "ok"); }
  };

  (async () => {
    try {
      const m = await me();
      const sid = m.storeId || (m.user && m.user.storeId) || 1;
      S.reserveUrl = `${location.origin}/reserve` + (sid === 1 ? "" : `?store=${sid}`);
      $("#reserveUrl").textContent = S.reserveUrl;
    } catch (e) { /* 기본값 유지 */ }
  })();

  load().catch((e) => toast(e.message, "err"));
})();
