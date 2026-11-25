// 회원 관리 — 등급·포인트·생일·방문 이력·CSV (문자 발송은 2단계)
(() => {
  renderNav("customers");
  const S = { list: [], counts: null, q: "", sort: "recent", grade: "", selected: new Set(), editing: null };

  async function load() {
    const data = await api(`/api/customers?q=${encodeURIComponent(S.q)}&sort=${S.sort}&grade=${S.grade}`);
    S.list = data.customers;
    S.counts = data.counts;
    S.selected = new Set([...S.selected].filter((id) => S.list.some((c) => c.id === id)));
    render();
  }

  function render() {
    const c = S.counts || { byGrade: {}, grades: [] };
    const gradeRows = Object.entries(c.byGrade || {});
    $("#gradeStats").innerHTML = `
      <div class="card stat"><div class="k">전체 회원</div>
        <div class="v nums">${c.total || 0}<span style="font-size:15px;font-weight:700">명</span></div>
        <div class="s">연락처를 남긴 손님</div></div>
      ${gradeRows.map(([g, n]) => {
        const label = g === "NEW" ? "신규" : (c.grades || []).find((x) => x.code === g)?.label || g;
        return `<div class="card stat"><div class="k">${esc(label)}</div>
          <div class="v nums">${n}<span style="font-size:15px;font-weight:700">명</span></div>
          <div class="s">${g === "NEW" ? "아직 기준 미달" : "자동 산정 + 수동 변경 포함"}</div></div>`;
      }).join("")}
      <div class="card stat"><div class="k">포인트 잔액 합계</div>
        <div class="v nums">${points(c.pointsTotal || 0)}</div>
        <div class="s">결제 금액의 ${c.pointsRate || 0}% 적립</div></div>`;
    $("#countBadge").textContent = `${S.list.length}명`;
    $("#criteria").textContent = c.criteriaText || "";
    $("#csvBtn").href = `/api/customers.csv?q=${encodeURIComponent(S.q)}&sort=${S.sort}&grade=${S.grade}`;

    const gf = $("#gradeFilter");
    if (gf.options.length <= 1) {
      (c.grades || []).forEach((g) => {
        const o = document.createElement("option");
        o.value = g.code; o.textContent = g.label;
        gf.appendChild(o);
      });
      const base = document.createElement("option");
      base.value = (c.baseGrade || {}).code || "NEW";
      base.textContent = (c.baseGrade || {}).label || "신규";
      gf.appendChild(base);
    }
    $("#birthdayList").innerHTML = (c.birthdays || []).length
      ? (c.birthdays.map((b) => `<span class="badge amber" style="margin:2px 4px 2px 0">${esc(b.birthdayLabel)} · ${esc(b.name)}</span>`).join(""))
      : '<span class="small muted">이번 달 생일 회원이 없습니다.</span>';
    $("#bdayNote").textContent = (c.birthdays || []).length
      ? `${c.birthdays.length}명 · 문자 발송은 2단계 예정(대상 확인만)`
      : "";

    if (!S.list.length) {
      $("#custList").innerHTML = `<div class="empty"><div class="ico">👥</div>조건에 맞는 회원이 없습니다<br>
        <span class="small">손님이 주문서에 이름·연락처를 남기면 자동으로 쌓이고, ‘회원 추가’로 직접 넣을 수도 있습니다.</span></div>`;
      updateSendBar();
      return;
    }

    $("#custList").innerHTML = `<table class="cust-table">
      <thead><tr>
        <th style="width:34px"><input type="checkbox" id="checkAll"></th>
        <th>이름·등급</th><th>연락처</th><th>생일</th><th>방문</th><th>누적 결제</th>
        <th>포인트</th><th>최근 방문</th><th>메모</th>
      </tr></thead>
      <tbody>${S.list.map(rowHTML).join("")}</tbody></table>
      <div class="cust-cards">${S.list.map(cardHTML).join("")}</div>`;

    $$("#custList tr[data-id]").forEach((tr) => {
      const id = Number(tr.dataset.id);
      const pick = tr.querySelector("[data-pick]");
      if (pick) pick.onchange = (e) => {
        e.target.checked ? S.selected.add(id) : S.selected.delete(id);
        updateSendBar();
      };
      tr.querySelectorAll("[data-open]").forEach((el) => el.onclick = () => openCust(id));
    });
    $$("#custList .ccard[data-id]").forEach((el) => {
      el.querySelectorAll("[data-open]").forEach((b) => b.onclick = () => openCust(Number(el.dataset.id)));
    });
    const all = $("#checkAll");
    if (all) {
      all.checked = S.list.length > 0 && S.list.every((x) => S.selected.has(x.id));
      all.onchange = (e) => {
        S.list.forEach((x) => e.target.checked ? S.selected.add(x.id) : S.selected.delete(x.id));
        render();
      };
    }
    updateSendBar();
  }

  function gradeBadge(c) {
    const tone = c.gradeTone || "";
    return `<span class="badge ${tone}">${esc(c.gradeLabel)}${c.gradeAuto ? "" : " · 수동"}</span>`;
  }

  function rowHTML(c) {
    return `<tr data-id="${c.id}">
      <td><input type="checkbox" data-pick ${S.selected.has(c.id) ? "checked" : ""} style="width:20px;height:20px;accent-color:var(--brand)"></td>
      <td><div class="nm">${esc(c.name)} ${gradeBadge(c)}</div>
        ${c.unpaidTotal ? `<span class="badge red">미결제 ${won(c.unpaidTotal)}</span>` : ""}</td>
      <td class="ph">${esc(c.phone || "–")}</td>
      <td class="small">${esc(c.birthdayLabel || "–")}</td>
      <td class="num">${c.visits}회</td>
      <td class="num"><b>${won(c.paidTotal)}</b></td>
      <td class="num">${c.points ? `<b>${points(c.points)}</b>` : "–"}</td>
      <td class="small">${c.lastVisit ? `${c.daysSince === 0 ? "오늘" : c.daysSince + "일 전"}` : "주문 없음"}
        <div class="small muted">${(c.lastVisit || "").slice(5, 16)}</div></td>
      <td><div class="memo ${c.memo ? "" : "empty"}" data-open>${esc(c.memo || "메모 추가")}</div></td>
    </tr>`;
  }

  function cardHTML(c) {
    return `<div class="ccard" data-id="${c.id}">
      <div class="top"><span class="nm">${esc(c.name)}</span>${gradeBadge(c)}
        <span class="badge ${c.consent ? "green" : ""}" style="margin-left:auto">${c.consent ? "수집 동의" : "미동의"}</span></div>
      <div class="small muted">${esc(c.phone || "연락처 없음")}${c.birthdayLabel ? ` · 생일 ${esc(c.birthdayLabel)}` : ""}</div>
      <div class="grid2">
        <div><div class="k">방문</div><div class="v">${c.visits}회</div></div>
        <div><div class="k">누적 결제</div><div class="v">${won(c.paidTotal)}</div></div>
        <div><div class="k">포인트</div><div class="v">${points(c.points)}</div></div>
        <div><div class="k">최근 방문</div><div class="v">${c.lastVisit ? (c.daysSince === 0 ? "오늘" : c.daysSince + "일 전") : "–"}</div></div>
      </div>
      <div class="row" style="margin-top:10px;gap:8px">
        <button class="btn sm" data-open>정보·메모 수정</button>
        <a class="btn sm ghost" href="tel:${esc(c.phone)}" ${c.phone ? "" : 'style="display:none"'}>전화</a>
      </div>
    </div>`;
  }

  async function openCust(id) {
    let c;
    try {
      c = await api(`/api/customers/${id}`);
    } catch (e) { toast(e.message, "err"); return; }
    S.editing = c;
    $("#csTitle").textContent = `${c.name} · ${c.gradeLabel}`;
    const grades = S.counts.grades || [];
    $("#csBody").innerHTML = `
      <div class="done-meta" style="margin:0 0 14px">
        <div><div class="k">방문</div><div class="v">${c.visits}회</div></div>
        <div><div class="k">누적 결제</div><div class="v">${won(c.paidTotal)}</div></div>
        <div><div class="k">포인트</div><div class="v">${points(c.points)}</div></div>
        <div><div class="k">최근 방문</div><div class="v">${c.lastVisit ? (c.daysSince === 0 ? "오늘" : c.daysSince + "일 전") : "–"}</div></div>
      </div>
      <div class="grid2">
        <div class="field"><label>이름</label><input class="input" id="cnName" value="${esc(c.name)}"></div>
        <div class="field"><label>연락처</label><input class="input" id="cnPhone" value="${esc(c.phone)}" placeholder="010-0000-0000"></div>
        <div class="field"><label>생일</label><input class="input" id="cnBirthday" value="${esc(c.birthday)}" placeholder="1990-03-15 또는 03-15"></div>
        <div class="field"><label>등급</label>
          <select class="select" id="cnGrade">
            <option value="" ${c.gradeManual ? "" : "selected"}>자동 (방문·결제 기준)</option>
            ${grades.map((g) => `<option value="${g.code}" ${c.gradeManual === g.code ? "selected" : ""}>${esc(g.label)} (수동)</option>`).join("")}
          </select></div>
      </div>
      <label class="consent" style="display:flex;gap:8px;align-items:flex-start;margin-bottom:12px">
        <input type="checkbox" id="cnConsent" ${c.consent ? "checked" : ""} style="width:20px;height:20px;accent-color:var(--brand)">
        <span>연락처 수집·이용에 동의함</span>
      </label>
      <div class="field"><label>메모</label>
        <textarea class="input" id="cnMemo" maxlength="500" placeholder="예: 매운맛 좋아함, 단체 예약 문의">${esc(c.memo)}</textarea></div>

      ${(c.favoriteMenus || []).length ? `<p class="small muted">자주 시킨 메뉴: ${c.favoriteMenus.map((f) => `${esc(f.name)} ×${f.qty}`).join(", ")}</p>` : ""}

      <h4 style="margin:16px 0 8px;font-size:16px">포인트 이력</h4>
      ${(c.pointHistory || []).length ? `<table class="table">
        <thead><tr><th>시각</th><th>내용</th><th>증감</th><th>잔액</th></tr></thead>
        <tbody>${c.pointHistory.slice(0, 20).map((p) => `<tr>
          <td class="small">${esc((p.createdAt || "").slice(5, 16))}</td>
          <td class="small">${esc(p.memo || p.kind)}</td>
          <td class="small ${p.delta > 0 ? "" : "muted"}">${p.delta > 0 ? "+" : ""}${p.delta.toLocaleString()}P</td>
          <td class="small nums">${p.balanceAfter.toLocaleString()}P</td></tr>`).join("")}</tbody></table>`
        : '<p class="small muted">포인트 이력이 없습니다.</p>'}

      <h4 style="margin:16px 0 8px;font-size:16px">방문 이력</h4>
      ${(c.orders || []).length ? `<table class="table">
        <thead><tr><th>시각</th><th>주문</th><th>메뉴</th><th>금액</th><th>결제</th></tr></thead>
        <tbody>${c.orders.slice(0, 12).map((o) => `<tr>
          <td class="small">${esc((o.createdAt || "").slice(5, 16))}</td>
          <td class="small">#${esc(o.orderNo)}</td>
          <td class="small">${esc(o.menu)}</td>
          <td class="small nums">${won(o.total)}</td>
          <td class="small">${o.paymentStatus === "PAID" ? '<span class="badge green">결제</span>' : '<span class="badge red">결제 전</span>'}</td>
        </tr>`).join("")}</tbody></table>` : '<p class="small muted">주문 이력이 없습니다(직접 등록한 회원).</p>'}
      <p class="small muted" style="margin-top:14px">연락처는 주문 확인·방문 기록 목적으로만 쓰고, 문자 발송은 2단계에서 붙습니다.</p>`;
    openSheet("custSheet");
  }

  $("#csSave").onclick = async () => {
    if (!S.editing) return;
    try {
      await api(`/api/customers/${S.editing.id}`, {
        method: "PATCH",
        body: {
          name: $("#cnName").value.trim(), phone: $("#cnPhone").value.trim(),
          birthday: $("#cnBirthday").value.trim(), consent: $("#cnConsent").checked,
          memo: $("#cnMemo").value.trim(), grade: $("#cnGrade").value,
        },
      });
      toast("저장했습니다", "ok");
      closeSheets();
      await load();
    } catch (e) { toast(e.message, "err"); }
  };

  $("#csMerge").onclick = async () => {
    const ids = [...S.selected].filter((id) => id !== S.editing.id);
    if (!ids.length) {
      toast("먼저 목록에서 합칠 회원을 체크해 주세요", "err");
      return;
    }
    if (!confirm(`${ids.length}명을 '${S.editing.name}' 회원으로 합칠까요? 주문·포인트 이력이 옮겨집니다.`)) return;
    try {
      await api(`/api/customers/${S.editing.id}/merge`, { method: "POST", body: { ids } });
      toast("회원을 합쳤습니다", "ok");
      S.selected = new Set();
      closeSheets();
      await load();
    } catch (e) { toast(e.message, "err"); }
  };

  function updateSendBar() {
    const n = S.selected.size;
    $("#selInfo").textContent = n ? `선택 ${n}명` : "선택한 회원 없음";
    $("#smsBtn").disabled = n === 0;
    $("#smsBtn").textContent = n ? `선택 ${n}명에게 문자 발송 (2단계 예정)` : "문자 발송 (2단계 예정)";
  }

  let timer;
  $("#search").addEventListener("input", (e) => {
    clearTimeout(timer);
    timer = setTimeout(() => { S.q = e.target.value.trim(); load(); }, 250);
  });
  $("#sort").addEventListener("change", (e) => { S.sort = e.target.value; load(); });
  $("#gradeFilter").addEventListener("change", (e) => { S.grade = e.target.value; load(); });
  $("#smsBtn").onclick = () => toast("문자 발송은 2단계에서 붙습니다. 지금은 대상 선택까지만 됩니다.");

  $("#addBtn").onclick = () => {
    ["addName", "addPhone", "addBirthday", "addMemo"].forEach((id) => { $("#" + id).value = ""; });
    $("#addGrade").value = "";
    $("#addConsent").checked = false;
    openSheet("addSheet");
    $("#addName").focus();
  };

  $("#addSave").onclick = async () => {
    try {
      const res = await api("/api/customers", { method: "POST", body: {
        name: $("#addName").value.trim(), phone: $("#addPhone").value.trim(),
        birthday: $("#addBirthday").value.trim(), grade: $("#addGrade").value,
        memo: $("#addMemo").value.trim(), consent: $("#addConsent").checked,
      } });
      toast(res.merged ? "같은 연락처의 기존 회원에 합쳤습니다" : "회원을 등록했습니다", "ok");
      closeSheets();
      await load();
    } catch (e) { toast(e.message, "err"); }
  };

  function openSheet(id) {
    $("#back").classList.add("on");
    $("#" + id).classList.add("on");
  }
  function closeSheets() {
    $("#back").classList.remove("on");
    $$(".sheet").forEach((s) => s.classList.remove("on"));
  }
  $("#back").onclick = closeSheets;
  $$("[data-close]").forEach((b) => b.onclick = closeSheets);

  load().catch((e) => toast(e.message, "err"));
})();
