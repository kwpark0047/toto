// 직원 관리 — 역할·권한 예외·급여 정보, 근태, 근무 스케줄(지각·미출근 대조), 예상 급여(참고용)
(() => {
  renderNav("staff");
  const S = { list: [], summary: null, month: "", editing: null, viewing: null,
              catalog: [], roleDefaults: {}, roles: [], partRole: "part",
              week: "", sched: null, editingSched: null, tab: "staff" };

  async function meta() {
    const m = await api("/api/staff/permissions");
    S.catalog = m.catalog;
    S.roles = m.roles;
    S.partRole = m.partRole;
    S.roleDefaults = {};
    m.roles.forEach((r) => { S.roleDefaults[r.code] = r.permissions; });
  }

  async function load() {
    const q = encodeURIComponent($("#search").value.trim());
    const sort = $("#sort").value;
    const month = $("#month").value || "";
    const data = await api(`/api/staff?q=${q}&sort=${sort}${month ? `&month=${month}` : ""}`);
    S.list = data.staff;
    S.summary = data.summary;
    S.month = data.month;
    if (!$("#month").value) $("#month").value = data.month;
    if (!$("#payMonth").value) $("#payMonth").value = data.month;
    render();
  }

  function render() {
    $("#countBadge").textContent = `${S.list.length}명`;
    const total = S.summary ? S.summary.totalMinutes : 0;
    $("#totalBadge").textContent = `이번 달 ${minutesText(total)}`;
    $("#monthLabel").textContent = S.month;
    $("#csvBtn").href = `/api/staff/attendance.csv${$("#month").value ? `?month=${$("#month").value}` : ""}`;
    $("#payCsvBtn").href = `/api/payroll.csv?month=${$("#payMonth").value || S.month}`;
    $("#monthSummary").innerHTML = S.summary && S.summary.rows.length
      ? S.summary.rows.map((r) => `<div class="row between" style="padding:6px 0;border-bottom:1px solid var(--line)">
          <span><b>${esc(r.name)}</b> ${r.open ? '<span class="badge green">근무 중</span>' : ""}</span>
          <span class="muted small">${r.days}일 · <b>${esc(r.text)}</b></span></div>`).join("")
      : '<span class="small muted">이번 달 출퇴근 기록이 없습니다.</span>';

    if (!S.list.length) {
      $("#staffList").innerHTML = `<div class="empty"><div class="ico">👥</div>직원이 없습니다<br><span class="small">'+ 직원 추가'로 주방·카운터 계정을 만들어 주세요.</span></div>`;
      return;
    }
    $("#staffList").innerHTML = `<table class="cust-table">
      <thead><tr><th>이름</th><th>아이디</th><th>역할</th><th>급여</th><th>상태</th><th>이번 달 근무</th><th>최근 출근</th><th></th></tr></thead>
      <tbody>${S.list.map(rowHTML).join("")}</tbody></table>`;
    $$("#staffList tr[data-id]").forEach((tr) => {
      const id = Number(tr.dataset.id);
      tr.querySelectorAll("[data-edit]").forEach((b) => b.onclick = (e) => { e.stopPropagation(); openStaff(id); });
      tr.querySelectorAll("[data-att]").forEach((b) => b.onclick = (e) => { e.stopPropagation(); openAttendance(id); });
    });
  }

  function payText(s) {
    if (s.payType === "hourly" && s.hourlyWage) return `시급 ${won(s.hourlyWage)}`;
    if (s.payType === "monthly" && s.monthlySalary) return `월급 ${won(s.monthlySalary)}`;
    return '<span class="muted small">미정</span>';
  }

  function rowHTML(s) {
    const roleBadge = { admin: "brand", manager: "brand", counter: "", kitchen: "amber", part: "line" }[s.role] || "";
    return `<tr data-id="${s.id}">
      <td><div class="nm">${esc(s.name)} ${s.open ? '<span class="badge green">근무 중</span>' : ""}
          ${s.mustChange ? '<span class="badge red">비번 변경 필요</span>' : ""}</div>
        <div class="small muted">${esc(s.phone || "")}</div></td>
      <td class="ph">${esc(s.username)}</td>
      <td><span class="badge ${roleBadge}">${esc(s.roleLabel)}</span></td>
      <td class="small">${payText(s)}</td>
      <td>${s.active ? '<span class="badge green">사용</span>' : '<span class="badge red">비활성</span>'}</td>
      <td class="num"><b>${esc(s.monthText)}</b></td>
      <td class="small muted">${s.open ? `오늘 ${hhmm(s.openSince)} 출근` : (s.lastIn ? ago(s.lastIn) : "–")}</td>
      <td class="nowrap"><button class="btn sm ghost" data-att>근태</button>
        <button class="btn sm" data-edit>수정</button></td>
    </tr>`;
  }

  /* ---------------- 직원 추가/수정 ---------------- */
  function permHTML(role, overrides) {
    const defaults = S.roleDefaults[role] || [];
    return S.catalog.map((p) => {
      const base = defaults.includes(p.code);
      const has = Object.prototype.hasOwnProperty.call(overrides || {}, p.code);
      const on = role === "admin" ? true : has ? !!overrides[p.code] : base;
      const diff = role !== "admin" && has && !!overrides[p.code] !== base;
      return `<label class="perm ${role === "admin" ? "off" : ""}">
        <input type="checkbox" data-perm="${p.code}" ${on ? "checked" : ""} ${role === "admin" ? "disabled" : ""}>
        <span><b>${esc(p.label)}</b>${diff ? ' <span class="badge amber">예외</span>' : ""}
          <span class="small muted">${esc(p.desc)}</span></span>
      </label>`;
    }).join("");
  }

  function refreshPerms() {
    const role = $("#stRole").value;
    const overrides = S.editing ? (S.editing.permissionOverrides || {}) : {};
    $("#permBox").innerHTML = permHTML(role, overrides);
    const hint = S.roles.find((r) => r.code === role);
    $("#roleHint").textContent = hint ? hint.hint : "";
  }

  function openStaff(id) {
    S.editing = id ? S.list.find((s) => s.id === id) : null;
    const s = S.editing;
    $("#stTitle").textContent = s ? `${s.name} 수정` : "직원 추가";
    $("#stName").value = s ? s.name : "";
    $("#stUsername").value = s ? s.username : "";
    $("#stPhone").value = s ? s.phone : "";
    $("#stRole").value = s ? s.role : "counter";
    $("#stPassword").value = "";
    $("#stPassword").placeholder = s ? "바꿀 때만 입력" : "4자 이상";
    $("#stMemo").value = s ? s.memo : "";
    $("#stActive").checked = s ? s.active : true;
    $("#stPayType").value = s ? (s.payType || "") : "";
    $("#stHourly").value = s && s.hourlyWage ? s.hourlyWage : "";
    $("#stMonthly").value = s && s.monthlySalary ? s.monthlySalary : "";
    $("#stDeactivate").classList.toggle("hidden", !s);
    $("#stReset").classList.toggle("hidden", !s);
    $("#resetBox").classList.add("hidden");
    $("#resetBox").innerHTML = "";
    refreshPerms();
    openSheet("staffSheet");
    $("#stName").focus();
  }

  $("#stRole").onchange = refreshPerms;

  $("#stSave").onclick = async () => {
    const overrides = {};
    $$("#permBox [data-perm]").forEach((cb) => {
      const base = (S.roleDefaults[$("#stRole").value] || []).includes(cb.dataset.perm);
      if ($("#stRole").value !== "admin" && cb.checked !== base) overrides[cb.dataset.perm] = cb.checked;
    });
    const body = {
      name: $("#stName").value.trim(), username: $("#stUsername").value.trim(),
      phone: $("#stPhone").value.trim(), role: $("#stRole").value,
      memo: $("#stMemo").value.trim(), active: $("#stActive").checked,
      payType: $("#stPayType").value, hourlyWage: Number($("#stHourly").value || 0),
      monthlySalary: Number($("#stMonthly").value || 0), permissions: overrides,
    };
    if ($("#stPassword").value) body.password = $("#stPassword").value;
    try {
      if (S.editing) await api(`/api/staff/${S.editing.id}`, { method: "PATCH", body });
      else await api("/api/staff", { method: "POST", body });
      toast(S.editing ? "직원 정보를 저장했습니다" : "직원을 추가했습니다", "ok");
      closeSheets();
      await load();
      if (S.tab === "schedule") await loadSchedule();
      if (S.tab === "payroll") await loadPayroll();
    } catch (e) { toast(e.message, "err"); }
  };

  $("#stReset").onclick = async () => {
    if (!S.editing) return;
    if (!confirm(`${S.editing.name} 님의 비밀번호를 초기화할까요? 지금 로그인은 모두 끊깁니다.`)) return;
    try {
      const r = await api(`/api/staff/${S.editing.id}/reset-password`, { method: "POST", body: {} });
      $("#resetBox").classList.remove("hidden");
      $("#resetBox").innerHTML = `<b>임시 비밀번호</b> <code class="temp-pw">${esc(r.temporaryPassword)}</code>
        <div class="small muted" style="margin-top:4px">이 값은 다시 볼 수 없습니다. 직원에게 알려 주고, 첫 로그인 뒤 ‘내 계정’에서 바꾸도록 하세요.</div>`;
      toast("임시 비밀번호를 만들었습니다", "ok");
      await load();
    } catch (e) { toast(e.message, "err"); }
  };

  $("#stDeactivate").onclick = async () => {
    if (!S.editing) return;
    if (!confirm(`${S.editing.name} 님을 비활성으로 바꿀까요? 로그인할 수 없게 됩니다(기록은 남습니다).`)) return;
    try {
      await api(`/api/staff/${S.editing.id}`, { method: "PATCH", body: { active: false } });
      toast("비활성으로 바꿨습니다", "ok");
      closeSheets();
      await load();
    } catch (e) { toast(e.message, "err"); }
  };

  /* ---------------- 근태 ---------------- */
  async function openAttendance(id) {
    S.viewing = S.list.find((s) => s.id === id);
    $("#attTitle").textContent = `${S.viewing.name} · 근태`;
    $("#attMonth").value = $("#month").value || S.month;
    await loadAttendance();
    openSheet("attSheet");
  }

  async function loadAttendance() {
    if (!S.viewing) return;
    const month = $("#attMonth").value || "";
    const data = await api(`/api/staff/attendance?staffId=${S.viewing.id}${month ? `&month=${month}` : ""}`);
    $("#attCsv").href = `/api/staff/attendance.csv?staffId=${S.viewing.id}${month ? `&month=${month}` : ""}`;
    const sum = data.summary.rows.find((r) => r.staffId === S.viewing.id);
    $("#attBody").innerHTML = `
      <div class="done-meta" style="margin:0 0 14px">
        <div><div class="k">${esc(data.month)} 근무</div><div class="v">${esc(sum ? sum.text : "0시간 0분")}</div></div>
        <div><div class="k">출근일</div><div class="v">${sum ? sum.days : 0}일</div></div>
        <div><div class="k">역할</div><div class="v">${esc(S.viewing.roleLabel)}</div></div>
        <div><div class="k">상태</div><div class="v">${S.viewing.active ? "사용" : "비활성"}</div></div>
      </div>
      ${data.records.length ? `<table class="table">
        <thead><tr><th>날짜</th><th>출근</th><th>퇴근</th><th>근무</th></tr></thead>
        <tbody>${data.records.map((r) => `<tr>
          <td>${esc(r.date)}</td><td>${esc((r.clockIn || "").slice(11, 16))}</td>
          <td>${r.clockOut ? esc(r.clockOut.slice(11, 16)) : '<span class="badge green">근무 중</span>'}</td>
          <td class="nums">${esc(r.minutesText)}</td></tr>`).join("")}</tbody></table>`
        : '<p class="muted small">이 달 기록이 없습니다.</p>'}`;
  }
  $("#attMonth").onchange = loadAttendance;

  /* ---------------- 근무 스케줄 ---------------- */
  $("#prevWeek").onclick = () => shiftWeek(-7);
  $("#nextWeek").onclick = () => shiftWeek(7);
  $("#thisWeek").onclick = () => { S.week = ""; loadSchedule(); };

  function shiftWeek(days) {
    const base = S.sched ? new Date(S.sched.start + "T00:00:00") : new Date();
    base.setDate(base.getDate() + days);
    S.week = `${base.getFullYear()}-${String(base.getMonth() + 1).padStart(2, "0")}-${String(base.getDate()).padStart(2, "0")}`;
    loadSchedule();
  }

  async function loadSchedule() {
    const q = S.week ? `?week=${S.week}` : "";
    const data = await api("/api/schedule" + q);
    S.sched = data;
    $("#weekLabel").textContent = `${data.start} ~ ${data.end}`;
    $("#planBadge").textContent = `예정 ${data.plannedCount}`;
    $("#lateBadge").textContent = `지각 ${data.lateCount}`;
    $("#missBadge").textContent = `미출근 ${data.missingCount}`;
    $("#todayWorkers").innerHTML = data.todayRows.length
      ? `<b>오늘 근무</b> ` + data.todayRows.map((r) =>
          `<span class="tw ${r.status}">${esc(r.staffName)} ${r.start}-${r.end}
            ${r.status === "LATE" ? `<b>지각 ${r.lateMin}분</b>` : r.status === "MISSING" ? "<b>미출근</b>" : r.status === "OK" ? "출근" : ""}</span>`).join(" ")
      : '<span class="muted small">오늘 등록된 근무가 없습니다.</span>';

    const days = data.days;
    const head = days.map((d) => {
      const w = "일월화수목금토"[new Date(d + "T00:00:00").getDay()];
      return `<th class="${d === data.today ? "today" : ""}">${d.slice(5)}<span class="small muted"> ${w}</span></th>`;
    }).join("");
    const rows = (data.staff || []).map((s) => {
      const cells = days.map((d) => {
        const row = (data.byDay[d] || []).find((r) => r.staffId === s.id);
        if (!row) return `<td class="scell empty" data-staff="${s.id}" data-date="${d}"><span class="plus">+</span></td>`;
        return `<td class="scell ${row.status}" data-staff="${s.id}" data-date="${d}" data-sched="${row.id}"
             data-start="${row.start}" data-end="${row.end}" data-memo="${esc(row.memo)}">
          <b>${row.start}</b><br>${row.end}
          ${row.status === "LATE" ? `<div class="sc-bad">지각 ${row.lateMin}분</div>` : ""}
          ${row.status === "MISSING" ? '<div class="sc-bad">미출근</div>' : ""}
          ${row.status === "OK" ? `<div class="sc-ok">${(row.clockIn || "").slice(11, 16)} 출근</div>` : ""}
        </td>`;
      }).join("");
      return `<tr><th class="sname">${esc(s.name)}<div class="small muted">${esc(s.roleLabel)}</div></th>${cells}</tr>`;
    }).join("");
    $("#schedGrid").innerHTML = (data.staff || []).length
      ? `<table class="schedtable"><thead><tr><th>직원</th>${head}</tr></thead><tbody>${rows}</tbody></table>`
      : '<div class="empty"><div class="ico">🗓</div>직원을 먼저 추가해 주세요</div>';
    $$("#schedGrid .scell").forEach((td) => td.onclick = () => openSched(td.dataset));
  }

  function openSched(d) {
    S.editingSched = d.sched || null;
    $("#scStaff").innerHTML = S.list.filter((s) => s.active).map((s) =>
      `<option value="${s.id}" ${Number(d.staff) === s.id ? "selected" : ""}>${esc(s.name)} (${esc(s.roleLabel)})</option>`).join("");
    $("#scDate").value = d.date;
    $("#scStart").value = d.start || "10:00";
    $("#scEnd").value = d.end || "15:00";
    $("#scMemo").value = d.memo || "";
    $("#scDelete").classList.toggle("hidden", !d.sched);
    $("#scTitle").textContent = d.sched ? "근무 수정" : "근무 등록";
    openSheet("schedSheet");
  }

  $("#scSave").onclick = async () => {
    try {
      await api("/api/schedule", { method: "POST", body: {
        staffId: Number($("#scStaff").value), date: $("#scDate").value,
        start: $("#scStart").value, end: $("#scEnd").value, memo: $("#scMemo").value,
      }});
      toast("근무를 저장했습니다", "ok");
      closeSheets();
      await loadSchedule();
    } catch (e) { toast(e.message, "err"); }
  };

  $("#scDelete").onclick = async () => {
    if (!S.editingSched || !confirm("이 근무를 지울까요?")) return;
    try {
      await api(`/api/schedule/${S.editingSched}`, { method: "DELETE" });
      toast("지웠습니다", "ok");
      closeSheets();
      await loadSchedule();
    } catch (e) { toast(e.message, "err"); }
  };

  /* ---------------- 예상 급여 ---------------- */
  async function loadPayroll() {
    const month = $("#payMonth").value || S.month;
    const data = await api(`/api/payroll?month=${month}`);
    $("#payTotal").textContent = `${data.month} 합계 ${won(data.totalPay)} · ${minutesText(data.totalMinutes)}`;
    $("#payCsvBtn").href = `/api/payroll.csv?month=${month}`;
    $("#payList").innerHTML = data.rows.length ? `<table class="table">
      <thead><tr><th>직원</th><th>급여 형태</th><th>근무</th><th>예상 급여</th><th>비고</th></tr></thead>
      <tbody>${data.rows.map((r) => `<tr>
        <td><b>${esc(r.name)}</b><div class="small muted">${esc(r.roleLabel)}</div></td>
        <td class="small">${esc(r.payLabel)}<div class="small muted">${r.payType === "monthly" ? won(r.monthlySalary) : r.hourlyWage ? `시급 ${won(r.hourlyWage)}` : "–"}</div></td>
        <td class="nums">${r.days}일 · ${esc(r.hoursText)}</td>
        <td class="nums"><b>${won(r.expectedPay)}</b></td>
        <td class="small muted">${esc(r.note || "참고용")}</td></tr>`).join("")}</tbody></table>`
      : '<div class="empty"><div class="ico">💰</div>직원이 없습니다</div>';
  }
  $("#payReload").onclick = () => loadPayroll().catch((e) => toast(e.message, "err"));

  /* ---------------- 탭 ---------------- */
  $$("#tabs [data-tab]").forEach((b) => b.onclick = async () => {
    S.tab = b.dataset.tab;
    $$("#tabs [data-tab]").forEach((x) => x.classList.toggle("on", x === b));
    $("#tabStaff").classList.toggle("hidden", S.tab !== "staff");
    $("#tabSchedule").classList.toggle("hidden", S.tab !== "schedule");
    $("#tabPayroll").classList.toggle("hidden", S.tab !== "payroll");
    try {
      if (S.tab === "schedule") await loadSchedule();
      if (S.tab === "payroll") await loadPayroll();
    } catch (e) { toast(e.message, "err"); }
  });

  /* ---------------- 시트 공통 ---------------- */
  function openSheet(id) { $("#back").classList.add("on"); $("#" + id).classList.add("on"); }
  function closeSheets() { $("#back").classList.remove("on"); $$(".sheet").forEach((s) => s.classList.remove("on")); }
  $("#back").onclick = closeSheets;
  $$("[data-close]").forEach((b) => b.onclick = closeSheets);

  let timer;
  $("#search").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(load, 250); });
  $("#sort").addEventListener("change", load);
  $("#month").addEventListener("change", load);
  $("#addBtn").onclick = () => openStaff(null);

  (async () => {
    await meta();
    await load();
    if (new URLSearchParams(location.search).get("add")) openStaff(null);
  })().catch((e) => toast(e.message, "err"));
})();
