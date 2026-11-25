// 사장님 콘솔 — 주문 관리 (오늘 주문, 현금 결제 확인, 테이블 현황, 웨이팅 요약)
(() => {
  renderNav("orders");

  const S = { orders: [], tables: [], counts: {}, summary: null, waiting: null, calls: [], rev: -1,
              filter: "all", maxId: 0, first: true, date: null, me: null, store: null,
              dashboard: null };
  const STATUS_TEXT = { NEW: "새 주문", ACCEPTED: "접수", COOKING: "조리중",
                        DONE: "조리완료(서빙 대기)", SERVED: "서빙 완료", CANCELED: "취소" };
  const NEXT = {
    NEW: { status: "ACCEPTED", label: "접수하기", cls: "primary" },
    ACCEPTED: { status: "COOKING", label: "조리 시작", cls: "green" },
    COOKING: { status: "DONE", label: "조리 완료", cls: "" },
    DONE: { status: "SERVED", label: "서빙 완료", cls: "green" },
  };

  async function load(force) {
    if (!S.me) {
      const m = await api("/api/auth/me");
      S.me = m.user;
      S.store = m.store;
      renderSetupTip(m);
    }
    const data = await api("/api/state");
    try { S.dashboard = await api("/api/dashboard"); } catch (e) { S.dashboard = null; }
    const newMax = data.orders.reduce((m, o) => Math.max(m, o.id), 0);
    if (!S.first && newMax > S.maxId) {
      const fresh = data.orders.filter((o) => o.id > S.maxId);
      beep(2, 900);
      toast(`새 주문 ${fresh.length}건 · ${fresh.map((o) => o.tableLabel).join(", ")}`, "ok");
    }
    S.maxId = newMax;
    S.first = false;
    S.orders = data.orders;
    S.tables = data.tables;
    S.counts = data.counts;
    S.summary = data.summary;
    S.waiting = data.waiting;
    const newCalls = (data.calls || []).filter((c) => !S.calls.some((x) => x.id === c.id));
    if (S.calls.length || newCalls.length) {
      if (newCalls.length) { beep(2, 760); toast(`직원 호출 · ${newCalls.map((c) => c.tableLabel).join(", ")}`, "ok"); }
    }
    S.calls = data.calls || [];
    S.date = data.today;
    render();
  }

  function renderSetupTip(m) {
    const el = $("#setupTip");
    if (!el) return;
    const hints = [];
    if (m.setup.profileEmpty) hints.push(`매장 정보(사업자·주소·영업시간)를 넣으면 <a href="/settings">영수증·QR</a>에 표시됩니다`);
    if (m.setup.staffCount <= 1) hints.push(`직원 계정을 만들면 주방·카운터가 따로 로그인합니다 <a href="/staff">직원 관리</a>`);
    if (!hints.length) { el.classList.add("hidden"); return; }
    el.classList.remove("hidden");
    el.innerHTML = `💡 ${hints.join(" · ")} <button class="btn sm ghost" id="hideSetup">닫기</button>`;
    $("#hideSetup").onclick = () => el.classList.add("hidden");
  }

  function render() {
    const d = new Date();
    const wd = "일월화수목금토"[d.getDay()];
    $("#todayLabel").textContent = `${S.date} (${wd}) · 새 주문이 들어오면 소리와 함께 표시됩니다`;
    renderStats();
    renderAlert();
    renderOrders();
    renderTables();
    renderWait();
    renderCalls();
    renderTop();
  }

  function renderStats() {
    const s = S.summary || {};
    if (s.salesHidden) {
      $("#stats").innerHTML = `
        <div class="card stat"><div class="k">오늘 주문</div>
          <div class="v nums">${s.orderCount || 0}<span style="font-size:15px;font-weight:700">건</span></div>
          <div class="s">진행 중 ${s.activeCount || 0}건</div></div>
        <div class="card stat"><div class="k">결제 확인 매출</div>
          <div class="v" style="font-size:18px">권한 없음</div>
          <div class="s">매출 조회 권한이 필요합니다</div></div>
        <div class="card stat"><div class="k">결제 전</div>
          <div class="v nums">${s.unpaidCount || 0}<span style="font-size:15px;font-weight:700">건</span></div>
          <div class="s">금액은 매출 권한자만 볼 수 있습니다</div></div>
        <div class="card stat"><div class="k">주방 대기</div>
          <div class="v nums">${(S.counts.waiting || 0) + (S.counts.cooking || 0)}</div>
          <div class="s">새 주문 ${S.counts.new || 0}건</div></div>`;
      return;
    }
    $("#stats").innerHTML = `
      <div class="card stat">
        <div class="k">오늘 주문</div>
        <div class="v nums">${s.orderCount || 0}<span style="font-size:15px;font-weight:700">건</span></div>
        <div class="s">진행 중 ${s.activeCount || 0}건 · 완료 ${s.doneCount || 0}건</div>
      </div>
      <div class="card stat hot">
        <div class="k">결제 확인 매출(현금)</div>
        <div class="v nums">${won(s.paidAmount || 0)}</div>
        <div class="s">결제 확인 ${s.paidCount || 0}건 · 평균 ${won(s.avgTicket || 0)}
          ${S.dashboard ? `<br>이번 주 ${won(S.dashboard.week.paidAmount)} · 이번 달 ${won(S.dashboard.month.paidAmount)}` : ""}</div>
      </div>
      <div class="card stat ${s.unpaidAmount ? "warn" : ""}">
        <div class="k">결제 전(미수금)</div>
        <div class="v nums">${won(s.unpaidAmount || 0)}</div>
        <div class="s">${s.unpaidCount || 0}건 · 계산대에서 받을 금액</div>
      </div>
      <div class="card stat">
        <div class="k">주방 대기</div>
        <div class="v nums">${(S.counts.new || 0) + (S.counts.accepted || 0) + (S.counts.cooking || 0)}<span style="font-size:15px;font-weight:700">건</span></div>
        <div class="s">새 주문 ${S.counts.new || 0} · 조리중 ${S.counts.cooking || 0}</div>
      </div>`;
  }

  function renderAlert() {
    const s = S.summary || {};
    const el = $("#unpaidAlert");
    if (!s.unpaidCount) { el.classList.add("hidden"); return; }
    el.classList.remove("hidden");
    el.innerHTML = `💵 결제 전 주문이 <b>${s.unpaidCount}건</b> 있습니다 · 합계 <b>${won(s.unpaidAmount)}</b>
      <button class="btn sm danger" id="showUnpaid">모아 보기</button>`;
    $("#showUnpaid").onclick = () => setFilter("unpaid");
  }

  function renderWait() {
    const w = S.waiting;
    const el = $("#waitSummary");
    if (!el) return;
    if (!w) { el.textContent = "웨이팅 정보를 불러오지 못했습니다"; return; }
    const called = w.calledCount || 0;
    const waiting = w.waitingCount || 0;
    const est = w.estimateMinutes == null ? "계산 중" : `약 ${w.estimateMinutes}분`;
    el.innerHTML = `
      <div class="row between" style="margin-bottom:6px">
        <span>대기 <b class="nums">${waiting}팀</b> · 인원 <b class="nums">${w.partyTotal || 0}명</b></span>
        <span class="badge ${called ? "brand" : ""}">호출 중 ${called}</span>
      </div>
      <div class="row between">
        <span class="muted">예상 대기 <b>${est}</b></span>
        <span class="muted">오늘 입장 ${w.counts.SEATED || 0} · 취소 ${(w.counts.CANCELED || 0) + (w.counts.NOSHOW || 0)}</span>
      </div>
      ${called ? `<div class="small" style="margin-top:6px;color:var(--brand);font-weight:800">${w.called.map((c) => c.ticketNo).join(", ")} 호출 중</div>` : ""}`;
  }

  function renderCalls() {
    const box = $("#callsBox");
    if (!box) return;
    const calls = S.calls || [];
    $("#callBadge").textContent = String(calls.length);
    $("#callBadge").className = "badge " + (calls.length ? "brand" : "");
    box.innerHTML = calls.length
      ? calls.map((c) => `<div class="row between" style="padding:5px 0;border-bottom:1px solid var(--line)">
          <span><b>${esc(c.tableLabel)}</b> <span class="muted small">${c.elapsedMin}분 전</span></span>
          <button class="btn sm primary" data-call="${c.id}">처리</button></div>`).join("")
      : "호출 없음";
    $$("#callsBox [data-call]").forEach((b) => b.onclick = async () => {
      try {
        await api(`/api/calls/${b.dataset.call}/done`, { method: "POST", body: {} });
        toast("호출을 처리했습니다", "ok");
        await load();
      } catch (e) { toast(e.message, "err"); }
    });
  }

  function filtered() {
    const o = S.orders;
    if (S.filter === "unpaid") return o.filter((x) => x.paymentStatus === "UNPAID" && x.status !== "CANCELED");
    if (S.filter === "active") return o.filter((x) => ["NEW", "ACCEPTED", "COOKING", "DONE"].includes(x.status));
    if (S.filter === "done") return o.filter((x) => ["DONE", "SERVED"].includes(x.status));
    return o;
  }

  function renderOrders() {
    const list = filtered();
    if (!list.length) {
      $("#orderList").innerHTML = `<div class="empty"><div class="ico">🧾</div>해당하는 주문이 없습니다</div>`;
      return;
    }
    $("#orderList").innerHTML = `<div class="order-list">${list.map(orderHTML).join("")}</div>`;
    $$("#orderList [data-act]").forEach((b) => b.addEventListener("click", onAction));
    $$("#orderList [data-detail]").forEach((b) => b.addEventListener("click", () => openDetail(Number(b.dataset.detail))));
  }

  function orderHTML(o) {
    const next = NEXT[o.status];
    const items = o.items.map((i) => `${esc(i.name)} <b>×${i.qty}</b>${i.options ? ` <span class="muted small">(${esc(i.options)})</span>` : ""}`).join(" · ");
    return `<article class="order ${o.status === "NEW" && o.id > S.maxId - 3 ? "new" : ""}">
      <div class="hd">
        <span class="no">#${esc(o.orderNo)}</span>
        <span class="badge brand">${esc(o.tableLabel)}</span>
        <span class="meta">${hhmm(o.createdAt)} · ${ago(o.createdAt)}</span>
        <span class="badge ${o.status === "NEW" ? "brand" : o.status === "COOKING" ? "amber" : o.status === "DONE" ? "amber" : o.status === "SERVED" ? "green" : o.status === "CANCELED" ? "red" : ""}">${STATUS_TEXT[o.status]}</span>
        <span class="badge ${o.paymentStatus === "PAID" ? "green" : "red"}">${o.paymentStatus === "PAID" ? "현금 완료" : "결제 전"}</span>
        ${o.reserved ? '<span class="badge amber">미리 주문</span>' : ""}
        ${o.receiptType !== "none" ? `<span class="badge ${o.receiptIssued ? "green" : "line"}">영수증 ${o.receiptIssued ? "발급" : "요청"}</span>` : ""}
        <button class="btn sm ghost" style="margin-left:auto" data-detail="${o.id}">상세</button>
      </div>
      <div class="items">${items}</div>
      ${o.note ? `<div class="note">📝 ${esc(o.note)}</div>` : ""}
      <div class="ft">
        <span class="total nums">${won(o.total)}</span>
        ${o.pointsUsed ? `<span class="badge amber">포인트 -${points(o.pointsUsed)}</span>` : ""}
        ${o.paymentStatus === "UNPAID" && o.status !== "CANCELED"
          ? `<button class="btn sm primary" data-act="pay" data-id="${o.id}">💵 현금 받음</button>`
          : `<span class="muted small">결제 확인 ${o.paidAt ? hhmm(o.paidAt) : ""}${o.pointsEarned ? ` · ${points(o.pointsEarned)} 적립` : ""}</span>`}
        ${next ? `<button class="btn sm ${next.cls}" data-act="status" data-id="${o.id}" data-to="${next.status}">${next.label}</button>` : ""}
        ${["NEW", "ACCEPTED", "COOKING", "DONE"].includes(o.status)
          ? `<button class="btn sm danger" data-act="status" data-id="${o.id}" data-to="CANCELED">취소</button>` : ""}
      </div>
    </article>`;
  }

  async function onAction(e) {
    const b = e.currentTarget;
    const id = Number(b.dataset.id);
    b.disabled = true;
    try {
      if (b.dataset.act === "pay") {
        const o = await api(`/api/orders/${id}/payment`, { method: "POST", body: { paid: true } });
        toast(`#${o.orderNo} 현금 ${won(o.total)} 결제 확인${o.pointsEarned ? ` · ${points(o.pointsEarned)} 적립` : ""}`, "ok");
        beep(1, 660);
      } else if (b.dataset.act === "status") {
        const o = await api(`/api/orders/${id}/status`, { method: "POST", body: { status: b.dataset.to } });
        toast(`#${o.orderNo} → ${STATUS_TEXT[o.status]}`, "ok");
      }
      await load();
      if ($("#orderSheet").classList.contains("on")) openDetail(id);
    } catch (err) {
      toast(err.message, "err");
    } finally {
      b.disabled = false;
    }
  }

  function renderTables() {
    if (!S.tables.length) {
      $("#tables").innerHTML = `<div class="muted small">테이블이 없습니다. <a href="/tables">테이블을 추가</a>해 주세요.</div>`;
      return;
    }
    $("#tables").innerHTML = S.tables
      .map((t) => `<div class="tile ${t.state} ${t.active ? "" : "off"}" ${t.orders ? `data-tile="${t.table}"` : ""}>
        <div class="tno">${esc(t.label)}</div>
        <div class="tst">${t.active ? (t.state === "IDLE" ? "빈 테이블" : t.stateLabel) : "비활성"}</div>
        ${t.seats ? `<div class="tmenu">${t.seats}석${t.since ? ` · ${t.since}부터 ${minutesText(t.elapsedMin)}` : ""}</div>` : ""}
        ${t.menu ? `<div class="tmenu">${esc(t.menu)}</div>` : ""}
        ${t.total ? `<div class="tmenu nums" style="font-weight:800">${won(t.total)}</div>` : ""}
      </div>`)
      .join("");
  }

  function renderTop() {
    const top = S.summary?.topItems || [];
    $("#topItems").innerHTML = top.length
      ? top.map((t, i) => `<div class="ti"><span class="rank">${i + 1}</span>${esc(t.name)}<span class="qty">${t.qty}개</span></div>`).join("")
      : `<div class="muted small">결제 확인된 주문이 아직 없습니다</div>`;
  }

  function receiptHTML(o) {
    const s = S.store || {};
    const lines = [
      `<div class="rcp">`,
      `<div class="rcp-name">${esc(s.name || "맛집")}</div>`,
      s.businessNo || s.ownerName || s.address || s.phone
        ? `<div class="rcp-sub">${[s.businessNo ? `사업자 ${esc(s.businessNo)}` : "", s.ownerName ? `대표 ${esc(s.ownerName)}` : ""].filter(Boolean).join(" · ")}</div>`
        : "",
      s.address || s.phone ? `<div class="rcp-sub">${[esc(s.address || ""), esc(s.phone || "")].filter(Boolean).join(" · ")}</div>` : "",
      s.hours ? `<div class="rcp-sub">영업 ${esc(s.hours)}</div>` : "",
      `<hr>`,
      `<div class="row between small"><span>주문 #${esc(o.orderNo)} · ${esc(o.tableLabel)}</span><span>${esc(o.createdAt)}</span></div>`,
      `<div class="row between small"><span>결제</span><span>${o.paymentStatus === "PAID" ? "현금 결제 완료" : "결제 전(현금)"}</span></div>`,
      `<hr>`,
      o.items.map((i) => `<div class="row between small"><span>${esc(i.name)} ×${i.qty}</span><span class="nums">${won(i.price * i.qty)}</span></div>`).join(""),
      `<hr>`,
      `<div class="row between small"><span>합계</span><span class="nums">${won(o.subtotal || o.total)}</span></div>`,
      o.pointsUsed ? `<div class="row between small"><span>포인트 사용</span><span class="nums">-${won(o.pointsUsed)}</span></div>` : "",
      `<div class="row between" style="font-weight:900"><span>받을 금액</span><span class="nums">${won(o.total)}</span></div>`,
      o.pointsEarned ? `<div class="row between small"><span>적립 포인트</span><span>${points(o.pointsEarned)}</span></div>` : "",
      s.paymentNote ? `<div class="rcp-sub" style="margin-top:8px">${esc(s.paymentNote)}</div>` : "",
      `</div>`,
    ];
    return lines.join("");
  }

  async function openDetail(id) {
    const o = S.orders.find((x) => x.id === id) || (await api("/api/orders/" + id));
    const next = NEXT[o.status];
    $("#osTitle").textContent = `주문 #${o.orderNo} · ${o.tableLabel}`;
    $("#osBody").innerHTML = `
      <div class="os-kv">
        <span class="k">주문 시각</span><span>${o.createdAt} <span class="muted small">(${ago(o.createdAt)})</span></span>
        <span class="k">상태</span><span>${STATUS_TEXT[o.status]}</span>
        <span class="k">결제</span><span>${o.paymentStatus === "PAID" ? `현금 결제 완료 (${hhmm(o.paidAt)})` : "결제 전 · 계산대에서 현금"}</span>
        <span class="k">고객</span><span>${esc(o.customerName || "이름 없음")} ${o.customerPhone ? "· " + esc(o.customerPhone) : ""}</span>
        ${o.note ? `<span class="k">요청</span><span>${esc(o.note)}</span>` : ""}
      </div>
      <div class="os-items">
        ${o.items.map((i) => `<div class="li"><span>${esc(i.name)}${i.options ? `<br><span class="muted small">${esc(i.options)}</span>` : ""}</span>
          <span class="nowrap">${i.qty}개 · <b class="nums">${won(i.price * i.qty)}</b></span></div>`).join("")}
      </div>
      ${o.pointsUsed ? `<div class="row between small" style="border-top:1px solid var(--line);padding-top:8px">
        <span>포인트 사용</span><span class="nums">-${won(o.pointsUsed)}</span></div>` : ""}
      <div class="row between" style="font-size:19px;font-weight:900;border-top:2px solid var(--line);padding-top:10px">
        <span>받을 금액</span><span class="nums">${won(o.total)}</span>
      </div>
      ${o.pointsEarned ? `<p class="small muted" style="margin:6px 0 0">적립 ${points(o.pointsEarned)} (결제 확인 시)</p>` : ""}
      ${o.receiptType !== "none" ? `<div class="card pad" style="margin-top:12px">
        <div class="row between"><b>현금영수증 요청</b>
          <span class="badge ${o.receiptIssued ? "green" : "amber"}">${o.receiptIssued ? "발급 완료" : "요청됨"}</span></div>
        <div class="small muted" style="margin-top:6px">${o.receiptType === "phone" ? "휴대폰번호" : "사업자번호"} ${esc(o.receiptNoMasked)}</div>
        <button class="btn sm ${o.receiptIssued ? "ghost" : "primary"}" id="receiptToggle" style="margin-top:8px">
          ${o.receiptIssued ? "발급 완료 취소" : "발급 완료로 표시"}</button>
        <p class="small muted" style="margin:6px 0 0">국세청 실제 발급·전송은 하지 않습니다(추후 연동).</p>
      </div>` : ""}
      <h4 style="margin:18px 0 8px;font-size:16px">영수증 미리보기</h4>
      ${receiptHTML(o)}
      <button class="btn sm ghost" id="printReceipt" style="margin-top:10px">🖨 영수증 인쇄</button>`;
    const foot = [];
    if (o.paymentStatus === "UNPAID" && o.status !== "CANCELED")
      foot.push(`<button class="btn primary" data-act="pay" data-id="${o.id}" style="flex:1">💵 현금 ${won(o.total)} 받음</button>`);
    else if (o.paymentStatus === "PAID")
      foot.push(`<button class="btn sm ghost" data-act="unpay" data-id="${o.id}">결제 확인 취소</button>`);
    if (next) foot.push(`<button class="btn green" data-act="status" data-id="${o.id}" data-to="${next.status}" style="flex:1">${next.label}</button>`);
    $("#osFoot").innerHTML = foot.join("");
    const pr = $("#printReceipt");
    if (pr) pr.onclick = () => printReceipt(o);
    const rt = $("#receiptToggle");
    if (rt) rt.onclick = async () => {
      try {
        await api(`/api/orders/${o.id}/receipt`, { method: "POST", body: { issued: !o.receiptIssued } });
        toast(o.receiptIssued ? "발급 완료를 취소했습니다" : "발급 완료로 표시했습니다", "ok");
        await load();
        openDetail(o.id);
      } catch (e) { toast(e.message, "err"); }
    };
    $$("#osFoot [data-act]").forEach((b) => b.addEventListener("click", async (e) => {
      if (b.dataset.act === "unpay") {
        if (!confirm("결제 확인을 취소할까요? 매출에서 빠지고 적립 포인트도 회수됩니다.")) return;
        await api(`/api/orders/${o.id}/payment`, { method: "POST", body: { paid: false } });
        toast("결제 확인을 취소했습니다");
      } else {
        await onAction(e);
      }
      await load();
      openDetail(o.id);
    }));
    $("#back").classList.add("on");
    $("#orderSheet").classList.add("on");
  }

  function printReceipt(o) {
    const w = window.open("", "_blank", "width=380,height=600");
    if (!w) { toast("팝업이 막혔습니다. 브라우저 팝업을 허용해 주세요", "err"); return; }
    w.document.write(`<!doctype html><html lang="ko"><head><meta charset="utf-8">
      <title>영수증 #${esc(o.orderNo)}</title>
      <style>body{font-family:-apple-system,"Malgun Gothic",sans-serif;padding:14px;font-size:13px;color:#241c16}
      .rcp-name{font-size:19px;font-weight:900;text-align:center}
      .rcp-sub{text-align:center;color:#666;font-size:11.5px}
      hr{border:0;border-top:1px dashed #bbb;margin:8px 0}
      .row{display:flex;justify-content:space-between;gap:8px;margin:3px 0}
      .small{font-size:12px}</style></head><body>
      ${receiptHTML(o)}
      <script>window.onload=()=>window.print();</script></body></html>`);
    w.document.close();
  }

  function setFilter(f) {
    S.filter = f;
    $$("#filters .chip").forEach((c) => c.classList.toggle("on", c.dataset.f === f));
    renderOrders();
  }

  $$("#filters .chip").forEach((c) => c.addEventListener("click", () => setFilter(c.dataset.f)));
  $("#refreshBtn").addEventListener("click", () => load().then(() => toast("새로고침했습니다")));
  $("#back").addEventListener("click", () => {
    $("#back").classList.remove("on");
    $("#orderSheet").classList.remove("on");
  });
  $$("[data-close]").forEach((b) => b.addEventListener("click", () => {
    $("#back").classList.remove("on");
    $("#orderSheet").classList.remove("on");
  }));

  // 알림음은 사용자가 화면을 한 번 건드린 뒤부터 소리가 난다(브라우저 정책)
  let soundOn = true;
  $("#soundBadge").addEventListener("click", () => {
    soundOn = !soundOn;
    $("#soundBadge").textContent = soundOn ? "🔔 알림 켜짐" : "🔕 알림 꺼짐";
    $("#soundBadge").classList.toggle("brand", soundOn);
  });
  document.addEventListener("click", () => beep(0), { once: true });

  load().catch((e) => toast(e.message, "err"));
  pollEvery(() => load(), 3000);
})();
