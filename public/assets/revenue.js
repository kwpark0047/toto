// 매출·정산: 기간 선택 → 일별·시간대별·결제수단·인기 메뉴·카테고리 비중 + CSV
(() => {
  renderNav("revenue");
  const S = { preset: "today", start: "", end: "", data: null };

  const pct = (n) => `${Number(n || 0).toFixed(1)}%`;

  function qs() {
    const p = new URLSearchParams();
    p.set("preset", S.preset);
    if (S.preset === "custom") { p.set("start", S.start); p.set("end", S.end); }
    return p.toString();
  }

  async function load() {
    const data = await api("/api/revenue?" + qs());
    S.data = data;
    $("#rangeLabel").textContent = `${data.start} ~ ${data.end}`;
    $("#csvBtn").href = "/api/revenue.csv?" + qs();
    renderTotals();
    renderDays();
    renderHours();
    renderMethods();
    renderCats();
    renderItems();
  }

  function renderTotals() {
    const t = S.data.totals;
    $("#totals").innerHTML = `
      <div class="stat hot"><div class="k">결제 확인 매출</div><div class="v nums">${won(t.paidAmount)}</div>
        <div class="s">${t.paidCount}건 · 평균 ${won(t.avgTicket)}</div></div>
      <div class="stat"><div class="k">주문</div><div class="v">${t.orderCount}</div>
        <div class="s">취소 ${t.canceledCount}건 ${t.canceledAmount ? `· ${won(t.canceledAmount)}` : ""}</div></div>
      <div class="stat ${t.unpaidAmount ? "warn" : ""}"><div class="k">미수금(결제 전)</div><div class="v nums">${won(t.unpaidAmount)}</div>
        <div class="s">${t.unpaidCount}건</div></div>
      <div class="stat"><div class="k">할인(포인트)</div><div class="v nums">${won(t.discountAmount)}</div>
        <div class="s">할인 전 ${won(t.grossAmount)}</div></div>`;
  }

  function renderDays() {
    const rows = S.data.days;
    const max = Math.max(1, ...rows.map((d) => d.paidAmount));
    $("#days").innerHTML = `<table class="table">
      <thead><tr><th>날짜</th><th>주문</th><th>결제</th><th>매출</th><th>미수</th><th>취소</th></tr></thead>
      <tbody>${rows.map((d) => `<tr>
        <td class="nowrap"><b>${d.date.slice(5)}</b> <span class="muted small">${d.weekday}</span>
          <div class="bar"><i style="width:${Math.round((d.paidAmount / max) * 100)}%"></i></div></td>
        <td class="nums">${d.orderCount}</td>
        <td class="nums">${d.paidCount}</td>
        <td class="nums"><b>${won(d.paidAmount)}</b></td>
        <td class="nums muted">${d.unpaidAmount ? won(d.unpaidAmount) : "-"}</td>
        <td class="nums muted">${d.canceledCount ? `${d.canceledCount}건` : "-"}</td>
      </tr>`).join("")}</tbody></table>`;
  }

  function renderHours() {
    const rows = S.data.hourly.filter((h) => h.count > 0);
    const peak = S.data.peakHour;
    $("#peakLabel").textContent = peak ? `가장 바쁜 때 ${peak.label}` : "";
    if (!rows.length) { $("#hours").innerHTML = '<div class="empty"><div class="ico">⏱</div>이 기간에는 주문이 없습니다</div>'; return; }
    const max = Math.max(1, ...rows.map((h) => h.amount));
    $("#hours").innerHTML = rows.map((h) => `<div class="hrow">
        <span class="hl">${h.label}</span>
        <span class="hb"><i style="width:${Math.round((h.amount / max) * 100)}%"></i></span>
        <span class="hv nums">${won(h.amount)} <span class="muted small">${h.count}건</span></span>
      </div>`).join("");
  }

  function renderMethods() {
    $("#methods").innerHTML = `<table class="table"><tbody>
      ${S.data.paymentMethods.map((m) => `<tr>
        <td><b>${esc(m.label)}</b>${m.connected ? "" : ` <span class="badge line">미연동</span>`}
          ${m.note ? `<div class="small muted">${esc(m.note)}</div>` : ""}</td>
        <td class="nums right"><b>${won(m.amount)}</b><div class="small muted">${m.count}건</div></td>
      </tr>`).join("")}
    </tbody></table>`;
  }

  function renderCats() {
    const rows = S.data.categories;
    $("#cats").innerHTML = rows.length ? rows.map((c) => `<div class="catrow">
        <span class="cn">${esc(c.name)}</span>
        <span class="cb"><i style="width:${c.share}%"></i></span>
        <span class="cv nums">${pct(c.share)} <span class="muted small">${won(c.amount)}</span></span>
      </div>`).join("") : '<div class="small muted">결제 확인된 주문이 없습니다</div>';
  }

  function renderItems() {
    const rows = S.data.topItems;
    $("#items").innerHTML = rows.length ? `<table class="table">
      <thead><tr><th>메뉴</th><th>수량</th><th>금액</th><th>비중</th></tr></thead>
      <tbody>${rows.map((i, n) => `<tr>
        <td><span class="rank">${n + 1}</span> <b>${esc(i.name)}</b></td>
        <td class="nums">${i.qty}</td><td class="nums">${won(i.amount)}</td>
        <td class="nums">${pct(i.share)}</td></tr>`).join("")}</tbody></table>`
      : '<div class="small muted">결제 확인된 주문이 없습니다</div>';
  }

  $$("[data-preset]").forEach((b) => b.onclick = () => {
    S.preset = b.dataset.preset;
    $$("[data-preset]").forEach((x) => x.classList.toggle("on", x === b));
    load().catch((e) => toast(e.message, "err"));
  });

  $("#apply").onclick = () => {
    const start = $("#start").value, end = $("#end").value;
    if (!start || !end) { toast("시작일과 끝 날짜를 골라 주세요", "err"); return; }
    S.preset = "custom"; S.start = start; S.end = end;
    $$("[data-preset]").forEach((x) => x.classList.remove("on"));
    load().catch((e) => toast(e.message, "err"));
  };

  const today = new Date();
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  $("#end").value = iso(today);
  const first = new Date(today.getFullYear(), today.getMonth(), 1);
  $("#start").value = iso(first);

  load().catch((e) => toast(e.message, "err"));
})();
