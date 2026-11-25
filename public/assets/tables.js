// 테이블 관리 — 추가·이름/좌석 수정·순서·비활성·삭제
(() => {
  renderNav("tables");
  const S = { tables: [], stats: null, editing: null };

  async function load() {
    const data = await api("/api/tables/admin");
    S.tables = data.tables;
    S.stats = data;
    render();
  }

  function render() {
    const d = S.stats;
    $("#totalBadge").textContent = `테이블 ${d.tables.length}개`;
    $("#activeBadge").textContent = `사용 ${d.activeCount}`;
    $("#offBadge").textContent = `비활성 ${d.inactiveCount}`;
    $("#seatBadge").textContent = `좌석 ${d.seatsTotal}석`;
    $("#shopLine").innerHTML = `매장 공통 QR은 <b>${esc(location.origin)}/</b> (손님이 테이블 선택)`;
    $("#shopUrl").textContent = `${location.origin}/`;

    if (!S.tables.length) {
      $("#tableList").innerHTML = `<div class="empty"><div class="ico">🪑</div>테이블이 없습니다<br><span class="small">'+ 테이블 추가'로 만들어 주세요.</span></div>`;
      return;
    }
    $("#tableList").innerHTML = `<table class="cust-table">
      <thead><tr><th style="width:74px">순서</th><th>이름</th><th>고객 주소</th><th>좌석</th><th>주문</th><th>상태</th><th></th></tr></thead>
      <tbody>${S.tables.map(rowHTML).join("")}</tbody></table>`;
    $$("#tableList tr[data-id]").forEach((tr) => {
      const id = Number(tr.dataset.id);
      tr.querySelectorAll("[data-edit]").forEach((b) => b.onclick = (e) => { e.stopPropagation(); openTable(id); });
      tr.querySelectorAll("[data-move]").forEach((b) => b.onclick = async (e) => {
        e.stopPropagation();
        try { await api(`/api/tables/${id}/move`, { method: "POST", body: { dir: b.dataset.move } }); await load(); }
        catch (err) { toast(err.message, "err"); }
      });
    });
  }

  function rowHTML(t) {
    return `<tr data-id="${t.id}">
      <td class="nowrap"><button class="btn sm ghost" data-move="up" title="위로">↑</button>
        <button class="btn sm ghost" data-move="down" title="아래로">↓</button></td>
      <td><div class="nm">${esc(t.label)}</div></td>
      <td class="ph">/t/${esc(t.code)}</td>
      <td class="num">${t.seats ? t.seats + "석" : "–"}</td>
      <td class="num">${t.orderCount ? t.orderCount + "건" : "–"}</td>
      <td>${t.active ? '<span class="badge green">사용</span>' : '<span class="badge red">비활성</span>'}</td>
      <td class="nowrap"><a class="btn sm ghost" href="/t/${esc(t.code)}" target="_blank">보기</a>
        <button class="btn sm" data-edit>수정</button></td>
    </tr>`;
  }

  function openTable(id) {
    S.editing = id ? S.tables.find((t) => t.id === id) : null;
    const t = S.editing;
    $("#tbTitle").textContent = t ? `${t.label} 수정` : "테이블 추가";
    $("#tbLabel").value = t ? t.label : `${S.tables.length + 1}번`;
    $("#tbSeats").value = t ? t.seats : 4;
    $("#tbActive").checked = t ? t.active : true;
    $("#tbDelete").classList.toggle("hidden", !t);
    $("#tbInfo").innerHTML = t
      ? `고객 주소 <b>${esc(location.origin)}/t/${esc(t.code)}</b> · 주문 이력 ${t.orderCount}건${t.orderCount ? " (삭제 대신 비활성 권장)" : ""}`
      : "저장하면 고객 주소와 QR이 바로 만들어집니다.";
    $("#back").classList.add("on");
    $("#tableSheet").classList.add("on");
    $("#tbLabel").focus();
  }

  $("#tbSave").onclick = async () => {
    const body = { label: $("#tbLabel").value.trim(), seats: Number($("#tbSeats").value || 0),
                   active: $("#tbActive").checked };
    try {
      if (S.editing) await api(`/api/tables/${S.editing.id}`, { method: "PATCH", body });
      else await api("/api/tables", { method: "POST", body });
      toast(S.editing ? "테이블을 저장했습니다" : "테이블을 추가했습니다", "ok");
      closeSheets();
      await load();
    } catch (e) { toast(e.message, "err"); }
  };

  $("#tbDelete").onclick = async () => {
    if (!S.editing) return;
    if (!confirm(`${S.editing.label} 테이블을 삭제할까요? 주문 이력이 있으면 삭제되지 않습니다.`)) return;
    try {
      await api(`/api/tables/${S.editing.id}`, { method: "DELETE" });
      toast("테이블을 삭제했습니다", "ok");
      closeSheets();
      await load();
    } catch (e) { toast(e.message, "err"); }
  };

  function closeSheets() {
    $("#back").classList.remove("on");
    $("#tableSheet").classList.remove("on");
  }
  $("#back").onclick = closeSheets;
  $$("[data-close]").forEach((b) => b.onclick = closeSheets);
  $("#addBtn").onclick = () => openTable(null);

  load().then(() => {
    if (new URLSearchParams(location.search).get("add")) openTable(null);
  }).catch((e) => toast(e.message, "err"));
})();
