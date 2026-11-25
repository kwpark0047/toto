// 고객 대기 접수·내 순서 확인 + 브라우저 알림(서비스 워커 + 폴링)
(() => {
  // 매장이 여러 개일 때: /wait?store=2 처럼 매장을 지정할 수 있다(대기 보드도 같음)
  const STORE_ID = new URLSearchParams(location.search).get("store");
  const STORE_Q = STORE_ID ? `?store=${encodeURIComponent(STORE_ID)}` : "";
  const STORE_AMP = STORE_ID ? `&store=${encodeURIComponent(STORE_ID)}` : "";
  const LS = "mangjip.wait.token";
  const LS_SEEN = "mangjip.wait.seen.";
  const tokenFromPath = (location.pathname.match(/\/wait\/t\/([A-Za-z0-9_-]+)/) || [])[1] || "";
  const S = { ticket: null, token: tokenFromPath, seen: null, swReady: false, pollTimer: null };

  /* ---------- 알림 판단(테스트 가능한 순수 함수) ---------- */
  // 앞 2팀이 되었을 때(한 번), 호출되었을 때(한 번) 알림을 만든다. 같은 알림은 다시 만들지 않는다.
  function waitAlerts(ticket, seen) {
    const out = [];
    if (!ticket) return out;
    seen = seen || {};
    if (ticket.status === "CALLED" && !seen.called) {
      out.push({ key: "called", event: "called",
        title: `${ticket.ticketNo}번 입장해 주세요`,
        body: `카운터에서 불렀습니다 · ${ticket.name || ""}` });
      return out;
    }
    const ahead = ticket.ahead;
    if (ticket.status === "WAITING" && ahead !== null && ahead !== undefined && ahead <= 2 && !seen.soon) {
      out.push({ key: "soon", event: "soon",
        title: "곧 순서입니다",
        body: `${ticket.ticketNo}번 · 앞에 ${Math.max(0, ahead)}팀` });
    }
    return out;
  }

  function loadSeen() {
    try { return JSON.parse(localStorage.getItem(LS_SEEN + S.token)) || {}; } catch (e) { return {}; }
  }
  function saveSeen(seen) {
    try { localStorage.setItem(LS_SEEN + S.token, JSON.stringify(seen)); } catch (e) { /* 무시 */ }
  }

  /* ---------- 화면 ---------- */
  async function boot() {
    try {
      const data = await api("/api/auth/me");
      const st = data.store || {};
      $("#wstore").textContent = st.name || "맛집";
      $("#wlogo").textContent = (st.name || "맛").slice(0, 1);
      $("#tkStore").textContent = st.name || "맛집";
      $("#wsub").textContent = st.tagline ? `웨이팅 · ${st.tagline}` : "웨이팅 접수";
      document.title = `${st.name || "맛집"} · 대기 접수`;
    } catch (e) { /* 로그인 없이도 동작 */ }

    if (!S.token) S.token = localStorage.getItem(LS) || "";
    await initNotify();
    if (S.token) {
      try {
        await showTicket(await fetchTicket(S.token));
        startPolling();
        return;
      } catch (e) {
        localStorage.removeItem(LS);
        S.token = "";
      }
    }
    showForm();
  }

  function showForm() {
    $("#formView").classList.remove("hidden");
    $("#ticketView").classList.add("hidden");
    stopPolling();
    $("#wName").focus();
  }

  async function showTicket(ticket) {
    S.ticket = ticket;
    $("#formView").classList.add("hidden");
    $("#ticketView").classList.remove("hidden");
    $("#tkNo").textContent = ticket.ticketNo;
    $("#tkStatus").textContent = ticket.statusLabel;
    $("#tkStatus").className = "tk-status " + (ticket.status === "CALLED" ? "called" : ticket.status);
    const ahead = ticket.ahead;
    if (ticket.status === "CALLED") {
      $("#tkLine").textContent = "지금 입장해 주세요";
      $("#tkLine").classList.add("called");
    } else if (ticket.status === "WAITING") {
      const est = ticket.estimatedMinutes == null ? "계산 중" : `약 ${ticket.estimatedMinutes}분`;
      $("#tkLine").textContent = `앞에 ${Math.max(0, ahead ?? 0)}팀 · ${est}`;
      $("#tkLine").classList.remove("called");
    } else {
      $("#tkLine").textContent = ticket.statusLabel;
      $("#tkLine").className = "tk-line";
    }
    const bits = [`${ticket.name} 님`, `${ticket.partySize}명`];
    if (ticket.phoneMasked) bits.push(ticket.phoneMasked);
    if (ticket.status === "WAITING" && ticket.estimateAvailable === false) bits.push("예상 시간은 조금 뒤 안내");
    $("#tkMeta").textContent = bits.join(" · ");
    const pre = $("#preorderBtn");
    if (pre) {
      pre.href = "/?preorder=" + encodeURIComponent(ticket.token);
      pre.classList.toggle("hidden", ["SEATED", "CANCELED", "NOSHOW"].includes(ticket.status));
    }
    const link = `${location.origin}/wait/t/${ticket.token}`;
    $("#tkLink").value = link;
    if (ticket.status === "SEATED" || ticket.status === "CANCELED" || ticket.status === "NOSHOW") {
      $("#notifyState").textContent = "대기가 끝났습니다. 이용해 주셔서 감사합니다.";
      $("#notifyBtn").classList.add("hidden");
    }
  }

  async function fetchTicket(token) {
    const data = await api(`/api/wait/t/${encodeURIComponent(token)}`);
    return data.ticket;
  }

  async function refresh() {
    if (!S.token) return;
    try {
      const ticket = await fetchTicket(S.token);
      await showTicket(ticket);
      await maybeNotify(ticket);
      if (["SEATED", "CANCELED", "NOSHOW"].includes(ticket.status)) stopPolling();
    } catch (e) {
      if (String(e.message).includes("찾을 수 없")) {
        stopPolling();
        localStorage.removeItem(LS);
        S.token = "";
        showForm();
        toast("대기 정보가 정리되었습니다(입장·취소 후 하루 경과).", "err");
      }
    }
  }

  function startPolling() {
    stopPolling();
    S.pollTimer = setInterval(() => {
      if (document.visibilityState === "visible") refresh();
    }, 10000);
  }
  function stopPolling() {
    if (S.pollTimer) clearInterval(S.pollTimer);
    S.pollTimer = null;
  }

  /* ---------- 브라우저 알림 ---------- */
  async function initNotify() {
    if (!("Notification" in window)) {
      $("#notifyState").textContent = "이 브라우저는 알림을 지원하지 않습니다. 화면 갱신으로 알려 드립니다.";
      $("#notifyBtn").classList.add("hidden");
      return;
    }
    if (window.isSecureContext === false) {
      $("#notifyState").textContent = "알림은 https 또는 localhost에서만 켜집니다. 화면 갱신으로 알려 드립니다.";
      $("#notifyBtn").classList.add("hidden");
      return;
    }
    if (navigator.serviceWorker) {
      try {
        await navigator.serviceWorker.register("/sw.js");
        S.swReady = true;
      } catch (e) { S.swReady = false; }
    }
    updateNotifyButton();
    $("#notifyBtn").onclick = requestNotify;
  }

  function updateNotifyButton() {
    if (!("Notification" in window)) return;
    if (Notification.permission === "granted") {
      $("#notifyBtn").textContent = "알림 켜짐";
      $("#notifyBtn").disabled = true;
      $("#notifyState").textContent = "앞 2팀·호출 시 브라우저 알림을 보냅니다";
    } else if (Notification.permission === "denied") {
      $("#notifyBtn").textContent = "알림 꺼짐";
      $("#notifyBtn").disabled = true;
      $("#notifyState").textContent = "알림이 차단되어 있습니다. 화면 갱신으로 알려 드립니다.";
    }
  }

  async function requestNotify() {
    try {
      const perm = await Notification.requestPermission();
      updateNotifyButton();
      if (perm !== "granted") {
        toast("알림을 켜지 않아도 화면이 자동으로 새로 고침됩니다", "err");
      } else {
        toast("알림을 켰습니다", "ok");
      }
    } catch (e) {
      toast("이 브라우저에서는 알림을 켤 수 없습니다", "err");
    }
  }

  async function notify(title, body) {
    if (!("Notification" in window) || Notification.permission !== "granted") return false;
    try {
      if (S.swReady && navigator.serviceWorker) {
        const reg = await navigator.serviceWorker.ready;
        await reg.showNotification(title, { body, tag: "mangjip-wait", icon: "/assets/icon-192.png", badge: "/assets/icon-192.png" });
      } else {
        new Notification(title, { body });
      }
      return true;
    } catch (e) { return false; }
  }

  async function maybeNotify(ticket) {
    const seen = loadSeen();
    const alerts = waitAlerts(ticket, seen);
    for (const a of alerts) {
      const ok = await notify(a.title, a.body);
      seen[a.key] = true;
      saveSeen(seen);
      if (ok) beep(2, 880);
      // 서버 이력에도 남긴다(실패해도 화면은 계속)
      try {
        await api(`/api/wait/t/${encodeURIComponent(S.token)}/notified`, {
          method: "POST",
          body: { event: a.event, status: ok ? "sent" : "denied",
                  detail: ok ? "브라우저 화면에서 표시" : "브라우저 알림 권한 없음" },
        });
      } catch (e) { /* 기록 실패는 무시 */ }
    }
  }

  /* ---------- 접수 ---------- */
  $("#submitBtn").onclick = async () => {
    const btn = $("#submitBtn");
    btn.disabled = true;
    $("#formMsg").textContent = "";
    try {
      const data = await api("/api/wait" + STORE_Q, { method: "POST", body: {
        name: $("#wName").value.trim(),
        phone: $("#wPhone").value.trim(),
        party: Number($("#wParty").value || 1),
        consent: $("#wConsent").checked,
        note: $("#wNote").value.trim(),
      } });
      S.token = data.ticket.token;
      localStorage.setItem(LS, S.token);
      saveSeen({});
      await showTicket(data.ticket);
      startPolling();
      await maybeNotify(data.ticket);
      if (data.reused) toast("이미 접수된 대기가 있어 그 번호를 보여 드립니다", "ok");
      if (Notification.permission !== "granted" && "Notification" in window) {
        toast("‘알림 받기’를 누르면 순서가 될 때 알려 드립니다", "ok");
      }
    } catch (e) {
      $("#formMsg").textContent = e.message;
      btn.disabled = false;
    }
  };

  $("#copyBtn").onclick = async () => {
    try {
      await navigator.clipboard.writeText($("#tkLink").value);
      toast("링크를 복사했습니다", "ok");
    } catch (e) {
      $("#tkLink").select();
      toast("링크를 길게 눌러 복사해 주세요");
    }
  };

  $("#anotherBtn").onclick = () => {
    localStorage.removeItem(LS);
    S.token = "";
    showForm();
  };

  $("#findLink").onclick = (e) => {
    e.preventDefault();
    $("#findBox").classList.toggle("hidden");
    $("#findPhone").focus();
  };

  $("#findBtn").onclick = async () => {
    $("#findMsg").textContent = "";
    try {
      const data = await api(`/api/wait/find?phone=${encodeURIComponent($("#findPhone").value.trim())}` + STORE_AMP);
      S.token = data.ticket.token;
      localStorage.setItem(LS, S.token);
      await showTicket(data.ticket);
      startPolling();
    } catch (e) { $("#findMsg").textContent = e.message; }
  };

  window.__waitTest = { waitAlerts };   // 점검 도구가 같은 함수를 그대로 부른다
  boot();
})();
