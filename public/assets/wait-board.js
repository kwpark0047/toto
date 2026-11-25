// 매장 앞 대기 현황판 — 자동 갱신(5초), 호출 시 소리
(() => {
  let lastCalled = null;

  function clock() {
    const d = new Date();
    $("#bClock").textContent = `${d.getMonth() + 1}월 ${d.getDate()}일 ${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
  }
  clock();
  setInterval(clock, 15000);

  async function load() {
    const sid = new URLSearchParams(location.search).get("store");
    const data = await api("/api/wait/board" + (sid ? `?store=${encodeURIComponent(sid)}` : ""));
    const store = data.store || {};
    $("#bStore").textContent = store.name || "맛집";
    $("#bLogo").textContent = (store.name || "맛").slice(0, 1);
    document.title = `${store.name || "맛집"} · 대기 현황`;

    const called = data.called || [];
    const signature = called.map((c) => c.ticketNo).join(",");
    if (lastCalled !== null && signature !== lastCalled && called.length) beep(3, 880);
    lastCalled = signature;

    $("#calls").innerHTML = called.length
      ? called.map((c) => `<div><div class="call-no">${esc(c.ticketNo)}</div>
          <div style="color:#c8b9a9;font-size:14px">${esc(c.name || "")} · ${c.partySize}명</div></div>`).join("")
      : '<div class="empty-board">호출 중인 번호가 없습니다</div>';

    $("#waitCount").textContent = `${data.waitingCount || 0}팀`;
    $("#numbers").innerHTML = (data.waiting || []).length
      ? data.waiting.map((t) => `<div class="num-chip"><b>${esc(t.ticketNo)}</b>
          <span>${t.partySize}명 · ${t.ahead === 0 ? "다음 차례" : `앞 ${t.ahead}팀`}</span></div>`).join("")
      : '<div class="empty-board">대기 중인 번호가 없습니다</div>';

    $("#estimate").textContent = data.estimateMinutes == null ? "계산 중" : `약 ${data.estimateMinutes}분`;
    $("#seated").textContent = `${(data.counts && data.counts.SEATED) || 0}팀`;
    $("#updated").textContent = `방금 갱신 · ${(data.serverTime || "").slice(11, 16)}`;
  }

  load().catch((e) => console.warn(e));
  pollEvery(load, 5000);
})();
