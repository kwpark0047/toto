// 사장님 웨이팅 관리 — 호출·입장·취소·노쇼 + 알림 이력
(() => {
  renderNav("wait");
  const S = { data: null, tables: [], seating: null, maxCalled: null };

  async function load() {
    const data = await api("/api/wait/admin");
    S.data = data;
    S.tables = data.tables || [];
    const called = (data.tickets || []).filter((t) => t.status === "CALLED").map((t) => t.ticketNo).join(",");
    if (S.maxCalled !== null && called !== S.maxCalled && called) beep(2, 900);
    S.maxCalled = called;
    render();
  }

  function render() {
    const d = S.data;
    const c = d.counts || {};
    $("#stats").innerHTML = `
      <div class="card stat"><div class="k">대기 중</div>
        <div class="v nums">${d.waitingCount || 0}<span style="font-size:15px;font-weight:700">팀</span></div>
        <div class="s">인원 ${d.partyTotal || 0}명</div></div>
      <div class="card stat hot"><div class="k">호출 중</div>
        <div class="v nums">${c.CALLED || 0}<span style="font-size:15px;font-weight:700">팀</span></div>
        <div class="s">오늘 입장 ${c.SEATED || 0}팀</div></div>
      <div class="card stat"><div class="k">오늘 접수</div>
        <div class="v nums">${(c.WAITING || 0) + (c.CALLED || 0) + (c.SEATED || 0) + (c.CANCELED || 0) + (c.NOSHOW || 0)}</div>
        <div class="s">취소 ${c.CANCELED || 0} · 노쇼 ${c.NOSHOW || 0}</div></div>
      <div class="card stat"><div class="k">예상 대기</div>
        <div class="v">${d.estimateAvailable ? `약 ${d.estimateMinutes}분` : "계산 중"}</div>
        <div class="s">최근 입장 간격 기준</div></div>`;
    $("#estimate").textContent = d.estimateAvailable
      ? `평균 ${d.estimateMinutes}분 · 표본이 쌓이면 더 정확해집니다`
      : "표본이 2건 이상 쌓이면 예상 시간이 표시됩니다";

    const tickets = d.tickets || [];
    $("#waitList").innerHTML = tickets.length ? `<div class="cust-table" style="display:block">
      <table class="table" style="width:100%">
        <thead><tr><th>번호</th><th>이름</th><th>인원</th><th>접수</th><th>경과</th><th>순서</th><th>알림</th><th>처리</th></tr></thead>
        <tbody>${tickets.map(rowHTML).join("")}</tbody>
      </table></div>` : '<div class="empty">오늘 접수된 대기가 없습니다</div>';
    $$("#waitList [data-act]").forEach((b) => b.onclick = () => act(b));
    $$("#waitList [data-notify]").forEach((b) => b.onclick = () => notifyTicket(b));

    const n = d.notifications || {};
    const s = n.summary || {};
    $("#notifySummary").textContent = `오늘 ${s.total || 0}건 · 보냄 ${s.sent || 0} · 미연결 ${s.stub || 0}`;
    $("#notifyHistory").innerHTML = (n.history || []).length ? `<table class="table">
      <thead><tr><th>시각</th><th>채널</th><th>상황</th><th>대상</th><th>결과</th></tr></thead>
      <tbody>${n.history.slice(0, 12).map((h) => `<tr>
        <td class="small">${esc((h.createdAt || "").slice(11, 16))}</td>
        <td class="small">${esc(h.channelLabel)}</td>
        <td class="small">${esc(h.eventLabel)}</td>
        <td class="small">${esc(h.ticketNo)} ${esc(h.recipient)}</td>
        <td class="small">${statusLabel(h.status)}</td></tr>`).join("")}</tbody></table>`
      : "오늘 알림 기록이 없습니다.";
  }

  function statusLabel(code) {
    const map = { sent: ["green", "보냄"], stub: ["amber", "미연결"], disabled: ["", "꺼짐"],
                  blocked_no_consent: ["red", "동의 없음"], blocked_night: ["red", "야간 제한"],
                  denied: ["red", "거부"], failed: ["red", "실패"] };
    const [tone, label] = map[code] || ["", code];
    return `<span class="badge ${tone}">${label}</span>`;
  }

  function rowHTML(t) {
    const tone = { WAITING: "", CALLED: "brand", SEATED: "green", CANCELED: "red", NOSHOW: "red" }[t.status] || "";
    const actions = [];
    if (t.status === "WAITING" || t.status === "CALLED") {
      actions.push(`<button class="btn sm ${t.status === "CALLED" ? "" : "primary"}" data-act="call" data-id="${t.id}">${t.status === "CALLED" ? "다시 호출" : "호출"}</button>`);
      actions.push(`<button class="btn sm green" data-act="seat" data-id="${t.id}">입장</button>`);
      if (t.reservedOrders) actions.push(`<button class="btn sm" data-act="start" data-id="${t.id}">미리 주문 시작</button>`);
      actions.push(`<button class="btn sm ghost" data-act="noshow" data-id="${t.id}">노쇼</button>`);
      actions.push(`<button class="btn sm danger" data-act="cancel" data-id="${t.id}">취소</button>`);
    }
    return `<tr>
      <td><b>${esc(t.ticketNo)}</b><div class="small"><span class="badge ${tone}">${esc(t.statusLabel)}</span>
        ${t.reservedOrders ? `<span class="badge amber">미리 주문 ${t.reservedOrders}</span>` : ""}</div></td>
      <td>${esc(t.name)}<div class="small muted">${esc(t.phoneMasked)}</div></td>
      <td class="num">${t.partySize}명</td>
      <td class="small">${esc((t.createdAt || "").slice(11, 16))}</td>
      <td class="small">${t.status === "WAITING" ? minutesText(t.waitMinutes) : esc(t.statusLabel)}</td>
      <td class="small">${t.position ? `${t.position}번째` : "–"}${t.estimatedMinutes != null && t.status === "WAITING" ? `<div class="muted tiny">약 ${t.estimatedMinutes}분</div>` : ""}</td>
      <td class="nowrap">
        <button class="btn sm ghost" data-notify="sms" data-id="${t.id}" title="문자(미연결)">문자</button>
        <button class="btn sm ghost" data-notify="kakao" data-id="${t.id}" title="카카오(미연결)">카톡</button>
      </td>
      <td class="nowrap">${actions.join(" ")}</td>
    </tr>`;
  }

  async function act(btn) {
    const id = Number(btn.dataset.id);
    const what = btn.dataset.act;
    btn.disabled = true;
    try {
      if (what === "call") {
        await api(`/api/wait/${id}/call`, { method: "POST", body: {} });
        toast("호출했습니다. 손님 화면에 알림이 갑니다", "ok");
        beep(2, 880);
      } else if (what === "start") {
        const r = await api(`/api/wait/${id}/start`, { method: "POST", body: {} });
        toast(r.started.length ? `미리 주문 ${r.started.length}건을 주방으로 넘겼습니다` : "넘길 미리 주문이 없습니다", "ok");
      } else if (what === "seat") {
        openSeat(id);
        btn.disabled = false;
        return;
      } else if (what === "cancel") {
        if (!confirm("이 대기를 취소 처리할까요?")) { btn.disabled = false; return; }
        await api(`/api/wait/${id}/cancel`, { method: "POST", body: {} });
        toast("취소 처리했습니다");
      } else if (what === "noshow") {
        await api(`/api/wait/${id}/noshow`, { method: "POST", body: {} });
        toast("노쇼 처리했습니다");
      }
      await load();
    } catch (e) {
      toast(e.message, "err");
      btn.disabled = false;
    }
  }

  function openSeat(id) {
    const t = S.data.tickets.find((x) => x.id === id);
    if (!t) return;
    S.seating = t;
    $("#seatTitle").textContent = `${t.ticketNo} · ${t.name} 입장`;
    $("#seatInfo").textContent = `${t.partySize}명 · ${t.phoneMasked}`;
    $("#seatTable").innerHTML = `<option value="">테이블은 나중에 (그냥 입장 처리)</option>` +
      S.tables.map((tb) => `<option value="${tb.id}">${esc(tb.label)}${tb.seats ? ` (${tb.seats}석)` : ""}</option>`).join("");
    $("#back").classList.add("on");
    $("#seatSheet").classList.add("on");
  }

  $("#seatOk").onclick = async () => {
    if (!S.seating) return;
    try {
      const r = await api(`/api/wait/${S.seating.id}/seat`, {
        method: "POST", body: { tableId: $("#seatTable").value || null } });
      toast(`${r.ticketNo} 입장 처리${r.tableLabel ? " · " + r.tableLabel : ""}`, "ok");
      closeSeat();
      await load();
    } catch (e) { toast(e.message, "err"); }
  };

  async function notifyTicket(btn) {
    const id = Number(btn.dataset.id);
    const channel = btn.dataset.notify;
    try {
      const r = await api("/api/notifications/send", {
        method: "POST", body: { channel, event: "called", ticketId: id } });
      toast(`${r.sent ? "보냄" : "미전송"}: ${r.detail || r.message}`, r.sent ? "ok" : "err");
      await load();
    } catch (e) { toast(e.message, "err"); }
  }

  function closeSeat() {
    $("#back").classList.remove("on");
    $("#seatSheet").classList.remove("on");
    S.seating = null;
  }
  $("#back").onclick = closeSeat;
  $$("[data-close]").forEach((b) => b.onclick = closeSeat);
  $("#refreshBtn").onclick = () => load().then(() => toast("새로고침했습니다"));

  load().catch((e) => toast(e.message, "err"));
  pollEvery(load, 5000);
})();
