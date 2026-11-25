// 주방 화면: 대기열(접수 → 조리중 → 완료), 경과 시간·지연 경고, 새 주문 알림
(() => {
  const S = { queue: [], serving: [], counts: {}, tables: [], maxId: 0, first: true, sound: true,
              tts: localStorage.getItem("mangjip.kds.tts") !== "off", view: "order",
              wake: null, maxAllergenId: 0 };
  const LABEL = { NEW: "새 주문", ACCEPTED: "접수됨", COOKING: "조리중", DONE: "서빙 대기" };

  function clock() {
    const d = new Date();
    $("#clock").textContent = `${d.getMonth() + 1}월 ${d.getDate()}일 ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  }
  clock();
  setInterval(clock, 15000);

  async function load() {
    const data = await api("/api/kitchen");
    const maxId = data.queue.reduce((m, o) => Math.max(m, o.id), S.maxId);
    if (!S.first && maxId > S.maxId) {
      const fresh = data.queue.filter((o) => o.id > S.maxId);
      if (fresh.length) {
        const allergen = fresh.find((o) => o.hasAllergen);
        if (S.sound) beep(3, allergen ? 620 : 940);
        fresh.slice(0, 2).forEach(speakOrder);
        toast(`새 주문 · 테이블 ${fresh.map((o) => o.table).join(", ")}`, "ok");
        document.body.animate(
          [{ filter: "brightness(1.35)" }, { filter: "brightness(1)" }],
          { duration: 700, iterations: 2 }
        );
      }
    }
    S.maxId = maxId;
    S.first = false;
    const calls = data.calls || [];
    const freshCalls = calls.filter((c) => !(S.calls || []).some((x) => x.id === c.id));
    if (freshCalls.length && !S.first) {
      beep(2, 1000);
      toast(`직원 호출 · ${freshCalls.map((c) => c.tableLabel).join(", ")}`, "ok");
    }
    S.calls = calls;
    renderCalls();
    S.queue = data.queue;
    S.serving = data.serving || [];
    S.counts = data.counts;
    S.tables = data.tables;
    render();
  }

  function render() {
    const c = S.counts;
    $("#counts").innerHTML = `
      <div class="kcount hot"><div class="k">새 주문</div><div class="v">${c.new || 0}</div></div>
      <div class="kcount ${(c.cooking || 0) > 0 ? "warn" : ""}"><div class="k">조리중</div><div class="v">${(c.accepted || 0) + (c.cooking || 0)}</div></div>
      <div class="kcount ${(c.serving || 0) > 0 ? "warn" : ""}"><div class="k">서빙 대기</div><div class="v">${c.serving || 0}</div></div>
      <div class="kcount"><div class="k">오늘 완료</div><div class="v">${c.doneToday || 0}</div></div>`;

    const q = S.queue;
    $("#emptyQueue").classList.toggle("hidden", q.length > 0);
    $("#queue").innerHTML = q.map(card).join("");
    $$("#queue [data-go]").forEach((b) => b.addEventListener("click", () => act(b)));
    renderGrouped();
    renderServing();
    $("#tstrip").innerHTML = S.tables
      .map((t) => `<div class="t ${t.state}"><b>${t.table}</b> <span class="muted">${t.state === "IDLE" ? "빈자리" : t.stateLabel}</span></div>`)
      .join("");
  }

  function card(o) {
    const mins = o.elapsedMin;
    const el = mins >= 1 ? `${mins}분` : `${o.elapsedSec}초`;
    const badge = o.delay === "late" ? "🚨 지연" : o.delay === "warn" ? "⏳ 서두르세요" : "";
    const btn = o.status === "NEW"
      ? { to: "ACCEPTED", label: "접수", cls: "go" }
      : o.status === "ACCEPTED"
        ? { to: "COOKING", label: "조리 시작", cls: "go" }
        : { to: "DONE", label: "✓ 조리 완료", cls: "done" };
    return `<article class="kcard ${o.delay}">
      <div class="top">
        <div class="tno">${esc(o.tableLabel || o.table + "번").replace("번", "")}<small>번</small></div>
        <div class="ono">#${esc(o.orderNo)} · ${LABEL[o.status] || ""} ${badge ? `<span style="color:${o.delay === "late" ? "#ff9a86" : "#ffd88a"}">${badge}</span>` : ""}</div>
        <div class="el">${el}</div>
      </div>
      <div class="items">
        ${o.items.map((i) => `<div class="it"><span class="q">${i.qty}×</span><span>${esc(i.name)}${i.options ? ` <span class="op">${esc(i.options)}</span>` : ""}</span></div>`).join("")}
      </div>
      ${o.hasAllergen ? `<div class="alarm">⚠️ 알레르기: ${o.allergens.map(esc).join(", ")} · 확인 후 조리</div>` : ""}
      ${o.note ? `<div class="note">📝 ${esc(o.note)}</div>` : ""}
      <div class="act"><button class="${btn.cls}" data-go="${btn.to}" data-id="${o.id}">${btn.label}</button></div>
    </article>`;
  }

  async function act(btn) {
    btn.disabled = true;
    try {
      const o = await api(`/api/orders/${btn.dataset.id}/status`, {
        method: "POST", body: { status: btn.dataset.go },
      });
      if (o.status === "DONE") beep(1, 620);
      if (o.status === "SERVED") beep(2, 760);
      await load();
    } catch (e) {
      toast(e.message, "err");
    } finally {
      btn.disabled = false;
    }
  }

  function renderServing() {
    const box = $("#serving");
    if (!box) return;
    const rows = S.serving || [];
    const cnt = $("#serveCount");
    if (cnt) cnt.textContent = rows.length ? `${rows.length}건` : "";
    $("#serveWrap").classList.toggle("empty", rows.length === 0);
    box.innerHTML = rows.length ? rows.map((o) => `<article class="scard ${o.servingLate ? "late" : ""}">
        <div class="tno">${esc(o.tableLabel || o.table + "번").replace("번", "")}<small>번</small></div>
        <div class="grow">
          <div class="ono">#${esc(o.orderNo)} · ${esc(o.tableLabel || "")}</div>
          <div class="items small">${o.items.map((i) => `${esc(i.name)} × ${i.qty}`).join(", ")}</div>
        </div>
        <div class="el">${o.servingMin >= 1 ? `${o.servingMin}분` : `${Math.max(0, o.servingSec || 0)}초`}</div>
        <button class="kbtn done" data-serve="${o.id}">서빙 완료</button>
      </article>`).join("")
      : `<div class="empty-serve">서빙 대기 없음</div>`;
    $$("#serving [data-serve]").forEach((b) => b.onclick = async () => {
      b.disabled = true;
      try {
        await api(`/api/orders/${b.dataset.serve}/status`, { method: "POST", body: { status: "SERVED" } });
        toast("서빙 완료 처리했습니다", "ok");
        await load();
      } catch (e) { toast(e.message, "err"); b.disabled = false; }
    });
  }

  function renderGrouped() {
    const box = $("#grouped");
    if (!box) return;
    const groups = {};
    S.queue.forEach((o) => {
      o.items.forEach((i) => {
        const key = i.name + "|" + (i.options || "");
        groups[key] = groups[key] || { name: i.name, options: i.options, qty: 0, tables: [] };
        groups[key].qty += i.qty;
        if (!groups[key].tables.includes(o.tableLabel || o.table + "번")) {
          groups[key].tables.push(o.tableLabel || o.table + "번");
        }
      });
    });
    const rows = Object.values(groups).sort((a, b) => b.qty - a.qty);
    box.innerHTML = rows.length
      ? `<table class="gtable"><thead><tr><th>메뉴</th><th>수량</th><th>테이블</th></tr></thead>
         <tbody>${rows.map((g) => `<tr><td><b>${esc(g.name)}</b>${g.options ? `<div class="op">${esc(g.options)}</div>` : ""}</td>
           <td class="gq">${g.qty}</td><td class="mt">${g.tables.map(esc).join(", ")}</td></tr>`).join("")}</tbody></table>`
      : '<div class="empty-queue">조리할 메뉴가 없습니다</div>';
  }

  function speakOrder(o) {
    if (!S.tts || !("speechSynthesis" in window)) return;
    try {
      const items = o.items.map((i) => `${i.name} ${i.qty}개`).join(", ");
      const u = new SpeechSynthesisUtterance(
        `${o.tableLabel || o.table + "번"} 테이블, ${items}${o.hasAllergen ? ", 알레르기 주의" : ""}`);
      u.lang = "ko-KR";
      u.volume = Number(localStorage.getItem("mangjip.kds.volume") || 0.9);
      window.speechSynthesis.speak(u);
    } catch (e) { /* TTS 미지원 */ }
  }

  $$("#ktabs .ktab").forEach((b) => b.onclick = () => {
    S.view = b.dataset.view;
    $$("#ktabs .ktab").forEach((x) => x.classList.toggle("on", x === b));
    $("#queue").classList.toggle("hidden", S.view !== "order");
    $("#grouped").classList.toggle("hidden", S.view !== "menu");
  });

  $("#ttsBtn").onclick = () => {
    if (!("speechSynthesis" in window)) { toast("이 브라우저는 음성 안내를 지원하지 않습니다", "err"); return; }
    S.tts = !S.tts;
    localStorage.setItem("mangjip.kds.tts", S.tts ? "on" : "off");
    $("#ttsBtn").textContent = S.tts ? "🗣 음성 안내 켜짐" : "🔇 음성 안내 꺼짐";
  };
  if (!("speechSynthesis" in window)) $("#ttsBtn").classList.add("hidden");
  $("#ttsBtn").textContent = S.tts ? "🗣 음성 안내 켜짐" : "🔇 음성 안내 꺼짐";

  $("#wakeBtn").onclick = async () => {
    try {
      if (S.wake) { await S.wake.release(); S.wake = null; $("#wakeBtn").textContent = "💡 화면 유지"; return; }
      if (!("wakeLock" in navigator)) { toast("이 브라우저는 화면 유지(Wake Lock)를 지원하지 않습니다", "err"); return; }
      S.wake = await navigator.wakeLock.request("screen");
      $("#wakeBtn").textContent = "💡 화면 유지 중";
      S.wake.addEventListener("release", () => { S.wake = null; $("#wakeBtn").textContent = "💡 화면 유지"; });
    } catch (e) { toast("화면 유지를 켤 수 없습니다", "err"); }
  };

  function renderCalls() {
    const box = $("#kcalls");
    if (!box) return;
    const calls = S.calls || [];
    box.innerHTML = calls.length
      ? `<span class="kcall-title">직원 호출</span>` + calls.map((c) =>
        `<span class="kcall">${esc(c.tableLabel)} <b>${c.elapsedMin}분</b>
          <button class="kbtn ghost" data-call="${c.id}">처리</button></span>`).join("")
      : "";
    $$("#kcalls [data-call]").forEach((b) => b.onclick = async () => {
      try {
        await api(`/api/calls/${b.dataset.call}/done`, { method: "POST", body: {} });
        toast("호출을 처리했습니다", "ok");
        await load();
      } catch (e) { toast(e.message, "err"); }
    });
  }

  $("#soundBtn").addEventListener("click", () => {
    S.sound = !S.sound;
    $("#soundBtn").textContent = S.sound ? "🔔 소리 켜짐" : "🔕 소리 꺼짐";
    if (S.sound) beep(1, 880);
  });

  if (typeof renderStaffTools === "function") renderStaffTools();
  load().catch((e) => toast(e.message, "err"));
  pollEvery(load, 3000);
  document.addEventListener("click", () => beep(0), { once: true });
})();
