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
  }

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
