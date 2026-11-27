// 매장 설정 — 기본 정보 · 사업자 정보 · 영업시간 · 포인트/등급 · 알림 · 직원/테이블
(() => {
  renderNav("settings");
  const S = { data: null, notify: null };

  async function load() {
    S.data = await api("/api/settings");
    S.notify = S.data.notifications;
    fill();
  }

  function fill() {
    const d = S.data, st = d.store, me = d.user;
    $("#storeName").value = st.name || "";
    $("#storeTagline").value = st.tagline || "";
    $("#basicState").textContent = "";
    $("#username").value = me.username;
    $("#accountName").value = me.name;
    $("#businessNo").value = st.businessNo || "";
    $("#ownerName").value = st.ownerName || "";
    $("#address").value = st.address || "";
    $("#phone").value = st.phone || "";
    $("#hours").value = st.hours || "";
    $("#paymentNote").value = st.paymentNote || "";
    $("#pointsRate").value = d.pointsRate;
    $("#pointsSub").textContent = `결제 금액의 ${d.pointsRate}% 자동 적립 · ${d.grades.map((g) => g.label).join("·")} 기준`;
    $("#bizSub").textContent = (st.businessNo || st.address || st.phone)
      ? [st.businessNo, st.address, st.phone].filter(Boolean).join(" · ")
      : "사업자등록번호·대표자·주소·전화 (아직 비어 있음)";
    $("#hoursSub").textContent = st.hours || st.paymentNote || "영업시간·결제 안내 (기본 문구 사용 중)";
    $("#notifySub").textContent = notifySubText();
    $("#staffSub").textContent = `직원 ${d.staff.staff.length}명 · 오늘 출근 ${d.staff.staff.filter((s) => s.open).length}명`;
    $("#tablesSub").textContent = `테이블 ${d.tables.tables.length}개 (사용 ${d.tables.activeCount} · 좌석 ${d.tables.seatsTotal}석)`;
    $("#setupNote").classList.toggle("hidden", !d.profileEmpty);

    fillGrades();
    fillSessions();
    fillStaff();
    fillTables();
    fillNotify();
    fillOps();
    fillPayments();
    fillEvents();
    fillCommunity();
    fillWaiting();
  }

  /* ---------- 온·오프라인 운영 모드 ---------- */
  function fillOps() {
    const ch = S.data.channel || {};
    const labels = S.data.channelLabels || {};
    $("#chMode").innerHTML = Object.keys(labels).map((k) =>
      `<option value="${k}"${ch.mode === k ? " selected" : ""}>${esc(labels[k])}</option>`).join("");
    if (ch.mode) $("#chMode").value = ch.mode;
    $("#chPickup").checked = !!ch.pickup;
    $("#chDelivery").checked = !!ch.delivery;
    $("#chPreorder").checked = !!ch.preorder;
    $("#chPickupMin").value = ch.pickupMin == null ? 20 : ch.pickupMin;
    $("#chDeliveryFee").value = ch.deliveryFee == null ? 0 : ch.deliveryFee;
    $("#chNote").value = ch.onlineNote || "";
    $("#channelSub").textContent = `${labels[ch.mode] || "오프라인"}` +
      [ch.pickup ? "포장" : "", ch.delivery ? "배달" : "", ch.preorder ? "사전주문" : ""]
        .filter(Boolean).map((x) => ` · ${x}`).join("");
  }

  $("#saveChannel").onclick = () => save({ channel: {
    mode: $("#chMode").value, pickup: $("#chPickup").checked,
    delivery: $("#chDelivery").checked, preorder: $("#chPreorder").checked,
    pickupMin: Number($("#chPickupMin").value || 0),
    deliveryFee: Number($("#chDeliveryFee").value || 0),
    onlineNote: $("#chNote").value,
  } }, "운영 모드");

  /* ---------- 결제 수단 ---------- */
  function fillPayments() {
    const p = S.data.payments || {};
    const cash = p.cash || {}, tr = p.transfer || {}, card = p.card || {}, quick = p.quick || {};
    $("#payCashNote").value = cash.note || "";
    $("#payTransferOn").checked = !!tr.enabled;
    $("#payBank").value = tr.bank || "";
    $("#payAccountNo").value = tr.accountNo || "";
    $("#payHolder").value = tr.holder || "";
    $("#payTransferNote").value = tr.note || "";
    $("#payCardOn").checked = !!card.enabled;
    $("#payCardFee").value = card.feeRate == null ? 0 : card.feeRate;
    $("#payCardProvider").value = card.provider || "none";
    $("#payCardNote").value = card.note || "";
    $("#payQuickOn").checked = !!quick.enabled;
    $("#payQuickFee").value = quick.feeRate == null ? 0 : quick.feeRate;
    $("#payQuickNote").value = quick.note || "";
    const on = ["현금", tr.enabled ? "계좌이체" : "", card.enabled ? "카드" : "", quick.enabled ? "간편결제" : ""]
      .filter(Boolean).join(" · ");
    $("#paySub").textContent = on;
    $("#payAdapterNote").textContent = (card.enabled || quick.enabled)
      ? "카드·간편결제는 PG 키가 없어 모의 승인으로만 기록됩니다(실제 결제 아님)."
      : "카드·간편결제를 켜면 모의 승인으로 동작합니다(PG 계약 후 실제 연동).";
  }

  $("#savePay").onclick = () => save({ payments: {
    cash: { note: $("#payCashNote").value },
    transfer: { enabled: $("#payTransferOn").checked, bank: $("#payBank").value,
                accountNo: $("#payAccountNo").value, holder: $("#payHolder").value,
                note: $("#payTransferNote").value },
    card: { enabled: $("#payCardOn").checked, feeRate: Number($("#payCardFee").value || 0),
            provider: $("#payCardProvider").value, note: $("#payCardNote").value },
    quick: { enabled: $("#payQuickOn").checked, feeRate: Number($("#payQuickFee").value || 0),
             note: $("#payQuickNote").value },
  } }, "결제 수단");

  /* ---------- 고객 이벤트·쿠폰 ---------- */
  function fillEvents() {
    const e = S.data.events || {};
    const fv = e.firstVisit || {}, rv = e.revisit || {}, bd = e.birthday || {};
    const td = e.timeDiscount || {}, cp = e.coupon || {};
    $("#eventBox").innerHTML = `
      <div class="row between" style="padding:8px 0;border-bottom:1px solid var(--line)">
        <div><b>첫 방문</b><div class="small muted">처음 결제한 손님에게 포인트·쿠폰</div></div>
        <label class="row" style="gap:6px"><input type="checkbox" data-ev="firstVisit" ${fv.enabled ? "checked" : ""} style="width:20px;height:20px"><span class="small">사용</span></label>
      </div>
      <div class="grid2" style="margin:8px 0">
        <div class="field"><label>첫 방문 포인트</label><input class="input" id="evFirstPoints" type="number" min="0" value="${fv.points || 0}"></div>
        <div class="field"><label>첫 방문 쿠폰</label><label class="row" style="gap:6px;margin-top:8px"><input type="checkbox" id="evFirstCoupon" ${fv.coupon ? "checked" : ""} style="width:20px;height:20px"><span class="small">쿠폰도 발급</span></label></div>
      </div>
      <div class="row between" style="padding:8px 0;border-bottom:1px solid var(--line)">
        <div><b>재방문</b><div class="small muted">며칠 안에 다시 오면 포인트</div></div>
        <label class="row" style="gap:6px"><input type="checkbox" data-ev="revisit" ${rv.enabled ? "checked" : ""} style="width:20px;height:20px"><span class="small">사용</span></label>
      </div>
      <div class="grid2" style="margin:8px 0">
        <div class="field"><label>기준(일)</label><input class="input" id="evRevDays" type="number" min="1" max="365" value="${rv.days || 7}"></div>
        <div class="field"><label>포인트</label><input class="input" id="evRevPoints" type="number" min="0" value="${rv.points || 0}"></div>
      </div>
      <div class="row between" style="padding:8px 0;border-bottom:1px solid var(--line)">
        <div><b>생일</b><div class="small muted">생일 달에 온 손님에게 포인트·쿠폰</div></div>
        <label class="row" style="gap:6px"><input type="checkbox" data-ev="birthday" ${bd.enabled ? "checked" : ""} style="width:20px;height:20px"><span class="small">사용</span></label>
      </div>
      <div class="grid2" style="margin:8px 0">
        <div class="field"><label>생일 포인트</label><input class="input" id="evBirthPoints" type="number" min="0" value="${bd.points || 0}"></div>
        <div class="field"><label>생일 쿠폰</label><label class="row" style="gap:6px;margin-top:8px"><input type="checkbox" id="evBirthCoupon" ${bd.coupon ? "checked" : ""} style="width:20px;height:20px"><span class="small">쿠폰도 발급</span></label></div>
      </div>
      <div class="row between" style="padding:8px 0;border-bottom:1px solid var(--line)">
        <div><b>시간 할인</b><div class="small muted">정해진 시간에 주문하면 자동 할인</div></div>
        <label class="row" style="gap:6px"><input type="checkbox" data-ev="timeDiscount" ${td.enabled ? "checked" : ""} style="width:20px;height:20px"><span class="small">사용</span></label>
      </div>
      <div class="grid2" style="margin:8px 0">
        <div class="field"><label>시작</label><input class="input" id="evTimeStart" value="${esc(td.start || "14:00")}" maxlength="5" placeholder="14:00"></div>
        <div class="field"><label>끝</label><input class="input" id="evTimeEnd" value="${esc(td.end || "17:00")}" maxlength="5" placeholder="17:00"></div>
        <div class="field"><label>할인율(%)</label><input class="input" id="evTimePercent" type="number" min="1" max="90" value="${td.percent || 10}"></div>
      </div>
      <div class="row between" style="padding:8px 0;border-bottom:1px solid var(--line)">
        <div><b>쿠폰</b><div class="small muted">발급 조건·금액</div></div>
        <label class="row" style="gap:6px"><input type="checkbox" data-ev="coupon" ${cp.enabled ? "checked" : ""} style="width:20px;height:20px"><span class="small">사용</span></label>
      </div>
      <div class="grid2" style="margin:8px 0">
        <div class="field"><label>쿠폰 이름</label><input class="input" id="evCouponTitle" maxlength="40" value="${esc(cp.title || "")}"></div>
        <div class="field"><label>할인 금액(원)</label><input class="input" id="evCouponAmount" type="number" min="0" value="${cp.amount || 0}"></div>
        <div class="field"><label>최소 주문(원)</label><input class="input" id="evCouponMin" type="number" min="0" value="${cp.minSpend || 0}"></div>
        <div class="field"><label>유효 기간(일)</label><input class="input" id="evCouponDays" type="number" min="1" max="365" value="${cp.validDays || 30}"></div>
      </div>`;
    $("#eventsSub").textContent =
      [fv.enabled ? "첫 방문" : "", rv.enabled ? "재방문" : "", bd.enabled ? "생일" : "",
       td.enabled ? "시간 할인" : "", cp.enabled ? "쿠폰" : ""].filter(Boolean).join(" · ") || "모두 꺼짐";
    loadEventSide();
  }

  async function loadEventSide() {
    try {
      const data = await api("/api/events");
      const coupons = data.coupons || [];
      $("#couponBox").innerHTML = coupons.length ? `<table class="table">
        <thead><tr><th>쿠폰</th><th>금액</th><th>조건</th><th>발급</th><th>사용</th></tr></thead>
        <tbody>${coupons.map((c) => `<tr><td>${esc(c.title)}</td>
          <td class="nums">${Number(c.amount || 0).toLocaleString()}원</td>
          <td class="small">${Number(c.minSpend || 0) ? Number(c.minSpend).toLocaleString() + "원 이상" : "조건 없음"}</td>
          <td class="nums">${c.issued}</td><td class="nums">${c.used}</td></tr>`).join("")}</tbody></table>`
        : '<span class="small muted">아직 발급된 쿠폰이 없습니다.</span>';
      const logs = data.recent || [];
      $("#eventLog").innerHTML = logs.length ? logs.slice(0, 8).map((l) =>
        `<div class="row between" style="padding:4px 0;border-bottom:1px solid var(--line)">
          <span class="small">${esc(l.createdAt.slice(5, 16))} · ${esc(l.title)}</span>
          <span class="small muted">${esc(l.customer || "")}${l.points ? ` · +${l.points}P` : ""}</span></div>`).join("")
        : '<span class="small muted">아직 적용된 이벤트가 없습니다.</span>';
    } catch (e) {
      $("#couponBox").innerHTML = '<span class="small muted">쿠폰을 불러오지 못했습니다.</span>';
      $("#eventLog").innerHTML = '<span class="small muted">이벤트 기록을 불러오지 못했습니다.</span>';
    }
  }

  const evOn = (key) => {
    const el = document.querySelector(`#eventBox [data-ev="${key}"]`);
    return el ? el.checked : false;
  };

  $("#saveEvents").onclick = () => save({ events: {
    firstVisit: { enabled: evOn("firstVisit"), points: Number($("#evFirstPoints").value || 0),
                  coupon: $("#evFirstCoupon").checked },
    revisit: { enabled: evOn("revisit"), days: Number($("#evRevDays").value || 7),
               points: Number($("#evRevPoints").value || 0) },
    birthday: { enabled: evOn("birthday"), points: Number($("#evBirthPoints").value || 0),
                coupon: $("#evBirthCoupon").checked },
    timeDiscount: { enabled: evOn("timeDiscount"), start: $("#evTimeStart").value,
                    end: $("#evTimeEnd").value, percent: Number($("#evTimePercent").value || 10) },
    coupon: { enabled: evOn("coupon"), title: $("#evCouponTitle").value,
              amount: Number($("#evCouponAmount").value || 0),
              minSpend: Number($("#evCouponMin").value || 0),
              validDays: Number($("#evCouponDays").value || 30) },
  } }, "고객 이벤트");

  /* ---------- 로컬 커뮤니티 ---------- */
  function fillCommunity() {
    const c = S.data.community || {};
    $("#comOn").checked = !!c.enabled;
    $("#comShow").checked = !!c.showToCustomers;
    $("#comJoint").checked = !!c.jointPromo;
    $("#comNeighborhood").value = c.neighborhood || "";
    $("#comIntro").value = c.intro || "";
    $("#communitySub").textContent = c.enabled
      ? `참여 중 · 손님에게 ${c.showToCustomers ? "보임" : "숨김"}` : "꺼짐(동네 소식·프로모션 올리지 않음)";
  }

  $("#saveCommunity").onclick = () => save({ community: {
    enabled: $("#comOn").checked, showToCustomers: $("#comShow").checked,
    jointPromo: $("#comJoint").checked, neighborhood: $("#comNeighborhood").value,
    intro: $("#comIntro").value,
  } }, "로컬 커뮤니티");

  /* ---------- 웨이팅 ---------- */
  function fillWaiting() {
    const w = S.data.waiting || {};
    $("#waitOn").checked = !!w.enabled;
    $("#waitNotice").value = w.notice || "";
    $("#waitMaxParty").value = w.maxParty == null ? 8 : w.maxParty;
    $("#waitingSub").textContent = w.enabled
      ? `받는 중 · 한 팀 최대 ${w.maxParty}명` : "꺼짐(대기 접수 안 함)";
  }

  $("#saveWaiting").onclick = () => save({ waiting: {
    enabled: $("#waitOn").checked, notice: $("#waitNotice").value,
    maxParty: Number($("#waitMaxParty").value || 8),
  } }, "웨이팅");

  function notifySubText() {
    const ch = S.notify.channels.map((c) => `${c.label} ${c.connected ? "연결" : "미연결"}${c.enabled ? "" : "(꺼짐)"}`);
    return ch.join(" · ");
  }

  function fillGrades() {
    const d = S.data;
    $("#gradeBox").innerHTML = d.grades.map((g) => `
      <div class="grid2" style="margin-top:8px">
        <div class="field" style="margin:0">
          <label>${esc(g.label)} — 방문 횟수 이상</label>
          <input class="input" data-grade="${g.code}" data-k="minVisits" type="number" min="0" value="${g.minVisits}">
        </div>
        <div class="field" style="margin:0">
          <label>${esc(g.label)} — 누적 결제 이상(원)</label>
          <input class="input" data-grade="${g.code}" data-k="minSpend" type="number" min="0" step="1000" value="${g.minSpend}">
        </div>
      </div>`).join("") +
      `<p class="small muted" style="margin:8px 0 0">신규는 위 기준에 못 미치는 회원입니다. 지금: ${esc(d.grades.map((g) => `${g.label} ${g.minVisits}회·${g.minSpend.toLocaleString()}원`).join(" / "))}</p>`;
  }

  function fillSessions() {
    const rows = S.data.sessions || [];
    $("#sessions").innerHTML = rows.length ? `<table class="table">
      <thead><tr><th>기기</th><th>마지막 사용</th><th>로그인</th><th></th></tr></thead>
      <tbody>${rows.map((s) => `<tr><td>${esc(s.device)} <span class="muted tiny">${esc(s.ip)}</span></td>
        <td>${esc(s.lastSeen)}</td><td class="muted small">${esc((s.createdAt || "").slice(0, 16))}</td>
        <td>${s.current ? '<span class="badge green">지금 기기</span>' : ""}</td></tr>`).join("")}</tbody>
    </table>` : '<span class="small muted">표시할 세션이 없습니다.</span>';
  }

  function fillStaff() {
    const list = S.data.staff.staff;
    $("#staffBox").innerHTML = list.length ? list.map((s) =>
      `<div class="row between" style="padding:6px 0;border-bottom:1px solid var(--line)">
        <span><b>${esc(s.name)}</b> <span class="badge ${s.role === "admin" ? "brand" : s.role === "kitchen" ? "amber" : ""}">${esc(s.roleLabel)}</span>
          ${s.active ? "" : '<span class="badge red">비활성</span>'} ${s.open ? '<span class="badge green">근무 중</span>' : ""}</span>
        <span class="muted small">이번 달 ${s.monthText}</span>
      </div>`).join("") : '<span class="small muted">직원이 아직 없습니다(사장님 계정만).</span>';
  }

  function fillTables() {
    const list = S.data.tables.tables;
    $("#tablesBox").innerHTML = `<div class="row wrap" style="gap:6px">${list.map((t) =>
      `<span class="badge ${t.active ? "" : "red"}">${esc(t.label)}${t.seats ? ` · ${t.seats}석` : ""}</span>`).join("")}</div>
`;
  }

  function fillNotify() {
    const n = S.notify;
    $("#channelBox").innerHTML = n.channels.map((c) => `
      <div class="row between" style="padding:8px 0;border-bottom:1px solid var(--line)">
        <div>
          <b>${esc(c.label)}</b>
          <span class="badge ${c.connected ? "green" : "red"}">${c.connected ? "연결됨" : "미연결"}</span>
          <div class="small muted" style="margin-top:2px">${esc(c.need)}</div>
        </div>
        <label class="row" style="gap:6px">
          <input type="checkbox" data-ch="${c.code}" ${c.enabled ? "checked" : ""} ${c.connected ? "" : "disabled"} style="width:20px;height:20px;accent-color:var(--brand)">
          <span class="small">사용</span>
        </label>
      </div>`).join("") +
      `<p class="small muted" style="margin:8px 0 0">${esc(n.nightRule)}</p>
       <p class="small muted" style="margin:4px 0 0">${esc(n.pushStub.need)}</p>
       ${n.channels.filter((c) => !c.connected).map((c) => `<p class="small" style="color:var(--brand);margin:6px 0 0">${esc(c.label)}을 켜려면 ${esc(c.need)}이 필요합니다.</p>`).join("")}`;
    $("#tplBox").innerHTML = n.templates && Object.values(n.templates).length
      ? Object.values(n.templates).map((t) => `<div class="field">
          <label>${esc(t.label)} <span class="muted tiny">— {name} {ticket} {ahead} {party} {store} 사용</span></label>
          <input class="input" data-tpl="${t.code}" value="${esc(t.text)}" maxlength="120"></div>`).join("")
      : "";
    const s = n.summary;
    $("#notifySummary").innerHTML = `오늘 ${s.total}건 · 보냄 ${s.sent} · 미연결 ${s.stub} · 차단 ${(s.byStatus.blocked_no_consent || 0) + (s.byStatus.blocked_night || 0)}`;
    $("#notifyHistory").innerHTML = n.history.length ? `<div style="max-height:230px;overflow:auto"><table class="table">
      <thead><tr><th>시각</th><th>채널</th><th>상황</th><th>대상</th><th>결과</th></tr></thead>
      <tbody>${n.history.slice(0, 20).map((h) => `<tr>
        <td class="small">${esc((h.createdAt || "").slice(11, 16))}</td>
        <td class="small">${esc(h.channelLabel)}</td>
        <td class="small">${esc(h.eventLabel)}</td>
        <td class="small">${esc(h.ticketNo)} ${esc(h.recipient)}</td>
        <td class="small">${statusBadge(h)}</td></tr>`).join("")}</tbody></table></div>`
      : '<span class="small muted">아직 알림 기록이 없습니다.</span>';
  }

  function statusBadge(h) {
    const map = { sent: ["green", "보냄"], stub: ["amber", "미연결"], disabled: ["", "꺼짐"],
                  blocked_no_consent: ["red", "동의 없음"], blocked_night: ["red", "야간 제한"], denied: ["red", "거부"] };
    const [tone, label] = map[h.status] || ["", h.status];
    return `<span class="badge ${tone}">${label}</span>`;
  }

  /* ---------- 저장 ---------- */
  async function save(patch, label) {
    try {
      const res = await api("/api/settings", { method: "PATCH", body: patch });
      S.data = await api("/api/settings");
      S.notify = S.data.notifications;
      fill();
      toast(`${label} 저장했습니다`, "ok");
      return res;
    } catch (e) {
      toast(e.message, "err");
      throw e;
    }
  }

  $("#saveBasic").onclick = () => save({
    storeName: $("#storeName").value, tagline: $("#storeTagline").value,
  }, "기본 정보");

  $("#saveAccount").onclick = async () => {
    try {
      await api("/api/account", { method: "PATCH", body: { username: $("#username").value.trim(), name: $("#accountName").value.trim() } });
      toast("계정 정보를 저장했습니다", "ok");
      await me(true);
    } catch (e) { toast(e.message, "err"); }
  };

  $("#savePw").onclick = async () => {
    try {
      await api("/api/account/password", { method: "POST",
        body: { current: $("#pwCurrent").value, new: $("#pwNew").value } });
      $("#pwCurrent").value = ""; $("#pwNew").value = "";
      toast("비밀번호를 바꿨습니다", "ok");
      S.data = await api("/api/settings"); fillSessions();
    } catch (e) { toast(e.message, "err"); }
  };

  $("#saveBiz").onclick = () => save({
    businessNo: $("#businessNo").value, ownerName: $("#ownerName").value,
    address: $("#address").value, phone: $("#phone").value,
  }, "사업자 정보");

  $("#saveHours").onclick = () => save({
    hours: $("#hours").value, paymentNote: $("#paymentNote").value,
  }, "영업시간·안내");

  $("#savePoints").onclick = () => {
    const grades = $$("#gradeBox [data-grade]").reduce((acc, el) => {
      const g = acc.find((x) => x.code === el.dataset.grade) || { code: el.dataset.grade };
      g[el.dataset.k] = Number(el.value || 0);
      if (!acc.includes(g)) acc.push(g);
      return acc;
    }, []).map((g) => {
      const base = S.data.grades.find((x) => x.code === g.code) || {};
      return { code: g.code, label: base.label || g.code,
               minVisits: Number(g.minVisits || 0), minSpend: Number(g.minSpend || 0) };
    });
    save({ pointsRate: Number($("#pointsRate").value), grades }, "포인트·등급");
  };

  $("#saveNotify").onclick = () => {
    const channels = {};
    $$("#channelBox [data-ch]").forEach((el) => { channels[el.dataset.ch] = el.checked; });
    const templates = {};
    $$("#tplBox [data-tpl]").forEach((el) => { templates[el.dataset.tpl] = el.value; });
    save({ notify: { channels, templates } }, "알림 설정");
  };

  $("#previewNotify").onclick = async () => {
    try {
      const r = await api("/api/notifications/test", { method: "POST", body: { channel: "browser", event: "soon" } });
      toast(`미리보기: "${r.message}" (${r.sent ? "보냄" : r.detail})`, "ok");
      S.data = await api("/api/settings"); S.notify = S.data.notifications; fillNotify();
    } catch (e) { toast(e.message, "err"); }
  };

  // ---------------------------------------------------------------- 백업·복원
  async function loadBackups() {
    const box = $("#backupList");
    if (!box) return;
    try {
      const data = await api("/api/backup");
      $("#backupSub").textContent = `자동 백업 최근 ${data.keep}개 보관 · ${data.dbPath}`;
      box.innerHTML = (data.backups || []).length
        ? `<table class="table"><thead><tr><th>파일</th><th>크기</th><th>만든 시각</th><th></th></tr></thead>
           <tbody>${data.backups.map((b) => `<tr>
             <td class="small">${esc(b.name)} ${b.auto ? '<span class="badge">자동</span>' : ""}</td>
             <td class="small nums">${Math.round(b.size / 1024)}KB</td>
             <td class="small">${esc(b.createdAt)}</td>
             <td><button class="btn sm ghost" data-pick="${esc(b.name)}">복원 대상</button></td></tr>`).join("")}
           </tbody></table>`
        : '<span class="small muted">백업 파일이 없습니다. ‘지금 백업 만들기’를 눌러 주세요.</span>';
      $$("#backupList [data-pick]").forEach((b) => b.onclick = () => {
        $("#restoreName").value = b.dataset.pick;
        $("#restoreConfirm").focus();
      });
    } catch (e) { box.innerHTML = `<span class="small muted">${esc(e.message)}</span>`; }
  }

  $("#backupNow").onclick = async () => {
    try {
      const r = await api("/api/backup", { method: "POST", body: {} });
      toast(`백업 파일을 만들었습니다 (${Math.round(r.size / 1024)}KB)`, "ok");
      await loadBackups();
    } catch (e) { toast(e.message, "err"); }
  };

  $("#restoreBtn").onclick = async () => {
    const name = $("#restoreName").value.trim();
    const confirmText = $("#restoreConfirm").value.trim();
    if (!name) { toast("복원할 백업 파일을 골라 주세요", "err"); return; }
    if (confirmText !== "복원") { toast("확인 문구에 '복원'이라고 입력해 주세요", "err"); return; }
    if (!window.confirm(`'${name}' 파일로 되돌립니다. 지금 데이터는 덮어써집니다. 계속할까요?`)) return;
    try {
      await api("/api/backup/restore", { method: "POST", body: { name, confirm: confirmText } });
      toast("복원했습니다. 화면을 새로 고칩니다", "ok");
      setTimeout(() => location.reload(), 800);
    } catch (e) { toast(e.message, "err"); }
  };

  document.querySelector('[data-card="backup"] .acc-head').addEventListener("click", () => {
    setTimeout(loadBackups, 50);
  });
  loadBackups();

  // 접이식 카드 열기/닫기
  $$(".acc").forEach((card) => {
    const btn = card.querySelector("[data-open]");
    const head = card.querySelector(".acc-head");
    const toggle = () => card.classList.toggle("open");
    if (btn && btn.tagName === "BUTTON") btn.onclick = (e) => { e.stopPropagation(); toggle(); };
    head.addEventListener("click", (e) => { if (e.target.tagName !== "A") toggle(); });
  });
  if (location.search.includes("setup=1") || location.hash) {
    const first = $(".acc");
    if (first) first.classList.add("open");
  }


  async function loadInquiries() {
    const box = $("#inqBox");
    if (!box) return;
    try {
      const data = await api("/api/inquiries");
      const list = data.inquiries || [];
      const cnt = $("#inqCount");
      if (cnt) cnt.textContent = `${list.length}건`;
      if (!list.length) { box.innerHTML = '<span class="small muted">아직 접수된 문의가 없습니다.</span>'; return; }
      box.innerHTML = `<div class="tablewrap"><table class="table">
        <thead><tr><th>접수번호</th><th>종류</th><th>이름</th><th>연락처</th><th>내용</th><th>접수</th></tr></thead>
        <tbody>${list.map((q) => `<tr>
          <td class="nums"><b>${esc(q.receiptNo)}</b></td>
          <td>${esc(q.kind)}</td>
          <td>${esc(q.name)}${q.storeName ? `<div class="small muted">${esc(q.storeName)}</div>` : ""}</td>
          <td class="small">${esc(q.phone || q.email || "-")}</td>
          <td class="small" style="max-width:300px">${esc(q.message)}</td>
          <td class="nums small muted">${esc(q.createdAt)}</td>
        </tr>`).join("")}</tbody></table></div>`;
      if ($("#inqSub")) $("#inqSub").textContent = `최근 ${list.length}건 · 홈페이지 문의 폼`;
    } catch (e) {
      box.innerHTML = '<span class="small muted">문의를 불러오지 못했습니다.</span>';
    }
  }

  loadInquiries();

  load().catch((e) => toast(e.message, "err"));
})();
