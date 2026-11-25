// 리뷰: 평균·분포·최근 추이, 답글 메모, 숨김
(() => {
  renderNav("reviews");
  const S = { reviews: [], summary: null };

  const stars = (n) => `${"★".repeat(n)}${"☆".repeat(5 - n)}`;

  async function load() {
    const data = await api("/api/reviews");
    S.reviews = data.reviews;
    S.summary = data.summary;
    renderStats();
    renderTrend();
    renderList();
  }

  function renderStats() {
    const s = S.summary;
    const dist = s.distribution || {};
    $("#stats").innerHTML = `
      <div class="stat hot"><div class="k">평균 별점</div><div class="v">${s.average ? s.average.toFixed(1) : "-"}</div>
        <div class="s">${s.count}건 (숨김 제외) · 전체 ${s.totalCount}건</div></div>
      <div class="stat"><div class="k">별점 분포</div>
        <div class="s" style="line-height:1.7;margin-top:6px">${[5, 4, 3, 2, 1].map((n) => `<span class="nowrap">${n}★ ${dist[String(n)] || 0}</span>`).join(" · ")}</div></div>
      <div class="stat ${s.unrepliedCount ? "warn" : ""}"><div class="k">답글 안 단 리뷰</div><div class="v">${s.unrepliedCount}</div>
        <div class="s">답글 ${s.repliedCount}건</div></div>`;
  }

  function renderTrend() {
    const rows = S.summary.trend || [];
    const max = Math.max(1, ...rows.map((r) => r.count));
    $("#trend").innerHTML = rows.map((r) => `<div class="tday">
        <div class="tb"><i style="height:${Math.round((r.count / max) * 100)}%"></i></div>
        <div class="tn">${r.avg ? r.avg.toFixed(1) : "-"}</div>
        <div class="td">${r.date.slice(5)}</div>
        <div class="tc">${r.count}건</div>
      </div>`).join("");
  }

  function renderList() {
    const includeHidden = $("#showHidden").checked;
    const rows = S.reviews.filter((r) => includeHidden || !r.hidden);
    $("#countBadge").textContent = `${rows.length}건`;
    $("#reviewList").innerHTML = rows.length ? rows.map((r) => `<article class="rv ${r.hidden ? "hidden" : ""}">
        <div class="rh">
          <span class="st">${stars(r.rating)}</span>
          <span class="badge line">${esc(r.tableLabel)}</span>
          <span class="small muted">#${esc(r.orderNo || r.orderId)} · ${(r.createdAt || "").slice(5, 16)}</span>
          ${r.hidden ? '<span class="badge red">숨김</span>' : ""}
          <span class="spacer"></span>
          <button class="btn sm ghost" data-hide="${r.id}">${r.hidden ? "다시 보이기" : "숨기기"}</button>
        </div>
        <div class="rc">${r.comment ? esc(r.comment) : '<span class="muted">(한 줄 평가 없음)</span>'}</div>
        <div class="rr">
          <input class="input" data-reply="${r.id}" maxlength="200" placeholder="사장님 답글 메모 (손님에게 전송되지 않습니다)" value="${esc(r.reply || "")}">
          <button class="btn sm" data-save="${r.id}">저장</button>
        </div>
      </article>`).join("")
      : '<div class="empty"><div class="ico">⭐</div>아직 리뷰가 없습니다. 손님이 주문 완료 후 남길 수 있습니다.</div>';
    $$("#reviewList [data-save]").forEach((b) => b.onclick = () => saveReply(Number(b.dataset.save)));
    $$("#reviewList [data-hide]").forEach((b) => b.onclick = () => toggleHidden(Number(b.dataset.hide)));
  }

  async function saveReply(id) {
    const input = document.querySelector(`[data-reply="${id}"]`);
    try {
      await api(`/api/reviews/${id}/reply`, { method: "POST", body: { reply: input.value } });
      toast("답글 메모를 저장했습니다", "ok");
      await load();
    } catch (e) { toast(e.message, "err"); }
  }

  async function toggleHidden(id) {
    const row = S.reviews.find((r) => r.id === id);
    if (!row) return;
    try {
      await api(`/api/reviews/${id}/hidden`, { method: "POST", body: { hidden: !row.hidden } });
      toast(row.hidden ? "다시 보이게 했습니다" : "숨겼습니다(평균에서 제외)", "ok");
      await load();
    } catch (e) { toast(e.message, "err"); }
  }

  $("#showHidden").onchange = renderList;
  load().catch((e) => toast(e.message, "err"));
})();
