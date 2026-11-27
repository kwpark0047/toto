// 최고관리자(플랫폼 운영자) 대시보드 — 읽기 중심, 매장 공개·글 공개만 바꾼다.
(() => {
  const S = { kind: "all", state: "all", pay: "all", postState: "all", tab: "entities" };
  let loadedOrders = false, loadedPosts = false;

  renderNav("super");

  const num = (n) => Number(n || 0).toLocaleString("ko-KR");
  const short = (s, n = 26) => {
    const t = String(s ?? "");
    return t.length > n ? t.slice(0, n - 1) + "…" : t;
  };
  const timeText = (ts) => (ts ? String(ts).replace("T", " ").slice(0, 16) : "–");

  // ---------------------------------------------------------------- KPI
  function statCard(k, v, s, hot) {
    return `<div class="stat ${hot ? "hot" : ""}">
      <div class="k">${esc(k)}</div><div class="v">${v}</div><div class="s">${s}</div></div>`;
  }

  function miniCard(title, body, foot) {
    return `<div class="card pad sa-mini">
      <div class="sa-mini-hd">${esc(title)}</div>${body}
      ${foot ? `<div class="sa-mini-ft">${foot}</div>` : ""}</div>`;
  }

  async function loadKpi() {
    const d = await api("/api/super-admin/overview");
    const o = d.orders, st = d.stores, ac = d.accounts;
    const db = d.backend === "turso" ? "Turso 영구 DB" : "SQLite";
    const dbEl = $("#dbBadge");
    if (dbEl) { dbEl.textContent = db; dbEl.className = "badge " + (d.backend === "turso" ? "green" : "amber"); }
    const who = $("#whoBadge");
    if (who && d.me) who.textContent = `👑 최고관리자 · ${d.me.username}${d.me.email ? " (" + d.me.email + ")" : ""}`;

    $("#kpi").innerHTML = [
      statCard("사업자 계정", num(ac.total), `사용 중 ${num(ac.active)} · 중지 ${num(ac.inactive)} · 최고관리자 ${num(ac.superAdmins)}`),
      statCard("매장", num(st.total), `공개 ${num(st.public)} · 비공개 ${num(st.private)} · 중지 ${num(st.inactive)}`),
      statCard("매장 그룹", num(d.groups.total), `직원 ${num(d.staff.active)}명 사용 중 · 회원 ${num(d.customers.total)}명`),
      statCard("누적 매출 (결제 완료)", won(o.allTime.paidAmount),
        `누적 주문 ${num(o.allTime.count)}건 · 미수 ${won(o.allTime.unpaidAmount)} · 이번 달 ${won(o.month.paidAmount)}`, true),
    ].join("");

    const methods = (d.payments.methods || []).filter((m) => m.count > 0 || m.amount > 0);
    const payRows = methods.length
      ? methods.map((m) => `<div class="sa-payrow">
          <span>${esc(m.label)}</span><b>${num(m.count)}건</b><em>${won(m.amount)}</em></div>`).join("")
      : `<p class="small muted" style="margin:0">아직 결제 완료 주문이 없습니다.</p>`;
    const via = d.scans.byVia || {};
    const todayVia = d.scans.todayByVia || {};

    $("#kpi2").innerHTML = [
      miniCard("오늘 주문 · 매출",
        `<div class="sa-big">${won(o.today.paidAmount)}</div>
         <p class="small muted" style="margin:6px 0 0">오늘 주문 ${num(o.today.count)}건 · 결제 전 포함 ${won(o.today.amount)}</p>`,
        `누적 주문 ${num(o.allTime.count)}건 · 결제 완료 ${num(o.allTime.paidCount)}건`),
      miniCard("결제수단별 합계", payRows,
        `합계 ${num(d.payments.totalCount)}건 · ${won(d.payments.totalAmount)}`),
      miniCard("QR / NFC 스캔",
        `<div class="sa-big">${num(d.scans.total)}</div>
         <p class="small muted" style="margin:6px 0 0">오늘 ${num(d.scans.today)}회 (QR ${num(todayVia.qr)} · NFC ${num(todayVia.nfc)})</p>
         <div class="sa-chips"><span class="badge line">QR ${num(via.qr)}</span><span class="badge line">NFC ${num(via.nfc)}</span></div>`,
        `테이블 ${num(d.tables.active)}개 · 메뉴 ${num(d.menuItems.total)}개`),
      miniCard("로컬 커뮤니티 글",
        `<div class="sa-big">${num(d.community.total)}</div>
         <p class="small muted" style="margin:6px 0 0">공개 ${num(d.community.visible)} · 숨김 ${num(d.community.hidden)} · 오늘 ${num(d.community.today)}</p>`,
        `리뷰 ${num(d.reviews.total)}건`),
    ].join("");

    renderAudit(d.recentActions || []);
    return d;
  }

  function renderAudit(rows) {
    const el = $("#auditList");
    if (!el) return;
    if (!rows.length) {
      el.innerHTML = `<p class="small muted" style="margin:0">아직 최고관리자가 바꾼 것이 없습니다.</p>`;
      return;
    }
    el.innerHTML = rows.map((a) => `<div class="kv-row">
        <span class="k">${esc(timeText(a.createdAt))} · ${esc(a.staffName)}</span>
        <span class="v">${esc(a.detail || a.action)}</span></div>`).join("");
  }

  // ---------------------------------------------------------------- 통합 목록
  function badgeFor(item) {
    if (item.type === "account") return `<span class="sa-type account">계정</span>`;
    if (item.type === "store") return `<span class="sa-type store">매장</span>`;
    return `<span class="sa-type group">그룹</span>`;
  }

  function entityRow(it) {
    if (it.type === "account") {
      return `<tr>
        <td>${badgeFor(it)}</td>
        <td><b>@${esc(it.username)}</b>${it.isSuperAdmin ? ' <span class="badge brand">최고관리자</span>' : ""}
          ${it.original ? ' <span class="badge line">원래 계정</span>' : ""}
          <div class="small muted">${esc(it.email || "이메일 미등록")}</div></td>
        <td class="small muted">${esc(short(it.storeNames.join(", ") || "–"))}</td>
        <td class="small muted">–</td>
        <td class="num">${num(it.storeCount)}</td>
        <td class="num">${num(it.orderCount)}</td>
        <td class="num">${won(it.paidTotal)}</td>
        <td>${it.active ? '<span class="badge green">사용 중</span>' : '<span class="badge red">중지</span>'}</td>
        <td class="small muted">–</td>
      </tr>`;
    }
    if (it.type === "store") {
      return `<tr>
        <td>${badgeFor(it)}</td>
        <td><b>#${it.id} ${esc(it.name)}</b>
          <div class="small muted">테이블 ${num(it.tableCount)} · 직원 ${num(it.staffCount)} · 글 ${num(it.postCount)}</div></td>
        <td class="small muted">${it.ownerUsername ? "@" + esc(it.ownerUsername) : "–"}</td>
        <td class="small muted">${esc(it.groupName || "–")}</td>
        <td class="num">–</td>
        <td class="num">${num(it.orderCount)}</td>
        <td class="num">${won(it.paidTotal)}</td>
        <td>${it.active ? '<span class="badge green">사용 중</span>' : '<span class="badge amber">중지</span>'}</td>
        <td>${it.listed
          ? `<button class="btn sm soft" data-store="${it.id}" data-listed="1">공개 중</button>`
          : `<button class="btn sm ghost" data-store="${it.id}" data-listed="0">비공개</button>`}</td>
      </tr>`;
    }
    return `<tr>
      <td>${badgeFor(it)}</td>
      <td><b>${esc(it.name)}</b> <span class="badge line">${esc(it.kindLabel)}</span>
        <div class="small muted">${esc(short(it.storeNames.join(", ") || "매장 없음"))}</div></td>
      <td class="small muted">${it.ownerUsername ? "@" + esc(it.ownerUsername) : "–"}</td>
      <td class="small muted">–</td>
      <td class="num">${num(it.storeCount)}</td>
      <td class="num">–</td>
      <td class="num">–</td>
      <td class="small muted">공개 ${num(it.publicCount)}</td>
      <td class="small muted">–</td>
    </tr>`;
  }

  async function loadEntities() {
    const q = ($("#entQ") && $("#entQ").value.trim()) || "";
    const url = `/api/super-admin/entities?q=${encodeURIComponent(q)}&kind=${S.kind}&state=${S.state}`;
    const d = await api(url);
    const items = d.items || [];
    $("#entCount").innerHTML = `계정 <b>${num(d.counts.accounts)}</b> · 매장 <b>${num(d.counts.stores)}</b>`
      + ` (공개 ${num(d.totals.publicStores)} / 비공개 ${num(d.totals.privateStores)})`
      + ` · 그룹 <b>${num(d.counts.groups)}</b> · 화면에 <b>${num(items.length)}</b>개`;
    $("#entityList").innerHTML = items.length
      ? items.map(entityRow).join("")
      : `<tr><td colspan="9"><div class="empty"><div class="ico">🔎</div>조건에 맞는 계정·매장·그룹이 없습니다</div></td></tr>`;
  }

  async function toggleStore(btn) {
    const id = btn.dataset.store;
    const next = btn.dataset.listed !== "1";
    const msg = next
      ? "이 매장을 서비스 소개(동네 매장 찾기)에 공개할까요?"
      : "이 매장을 서비스 소개에서 숨길까요? 손님은 동네 매장 찾기에서 볼 수 없게 됩니다.";
    if (!confirm(msg)) return;
    btn.disabled = true;
    try {
      await api(`/api/super-admin/stores/${id}`, { method: "PATCH", body: { listed: next } });
      toast(next ? "매장을 공개했습니다" : "매장을 비공개로 바꿨습니다", "ok");
      await Promise.all([loadKpi(), loadEntities()]);
    } catch (e) {
      toast(e.message, "err");
      btn.disabled = false;
    }
  }

  // ---------------------------------------------------------------- 주문·결제
  async function loadOrders() {
    const q = ($("#ordQ") && $("#ordQ").value.trim()) || "";
    const d = await api(`/api/super-admin/orders?limit=80&payment=${S.pay}&q=${encodeURIComponent(q)}`);
    const rows = d.orders || [];
    $("#orderCount").innerHTML = `전체 주문 중 <b>${num(rows.length)}</b>건 표시`;
    $("#orderList").innerHTML = rows.length ? rows.map((o) => `<tr>
        <td><b>#${esc(o.orderNo)}</b></td>
        <td class="small muted">${esc(o.storeName)}</td>
        <td class="small muted">${esc(o.channel === "pickup" ? "포장" : o.channel === "delivery" ? "배달"
          : o.channel === "preorder" ? "사전주문" : "매장")}</td>
        <td class="num"><b>${won(o.total)}</b></td>
        <td>${o.paymentStatus === "PAID"
          ? `<span class="badge green">${esc(o.paymentLabel)}</span>`
          : '<span class="badge amber">결제 전</span>'}</td>
        <td class="small muted">${esc(o.statusLabel)}</td>
        <td class="small muted">${esc(timeText(o.createdAt))}</td>
      </tr>`).join("")
      : `<tr><td colspan="7"><div class="empty"><div class="ico">🧾</div>아직 주문이 없습니다</div></td></tr>`;
  }

  // ---------------------------------------------------------------- 커뮤니티
  async function loadPosts() {
    const q = ($("#postQ") && $("#postQ").value.trim()) || "";
    const d = await api(`/api/super-admin/community?limit=80&state=${S.postState}&q=${encodeURIComponent(q)}`);
    const rows = d.posts || [];
    $("#postCount").innerHTML = `글 <b>${num(rows.length)}</b>건 표시`;
    $("#postList").innerHTML = rows.length ? rows.map((p) => `<tr>
        <td><b>${esc(short(p.title, 34))}</b>
          ${p.pinned ? '<span class="badge line">고정</span>' : ""}
          <div class="small muted">${esc(short(p.body, 44))}</div></td>
        <td class="small muted">${esc(p.storeName)}${p.groupName ? `<div class="small muted">그룹 ${esc(p.groupName)}</div>` : ""}</td>
        <td class="small muted">${esc(p.kindLabel)}</td>
        <td class="small muted">${esc(timeText(p.createdAt))}</td>
        <td>${p.visible ? '<span class="badge green">공개</span>' : '<span class="badge amber">숨김</span>'}</td>
        <td>${p.visible
          ? `<button class="btn sm danger" data-post="${p.id}" data-visible="1">숨기기</button>`
          : `<button class="btn sm soft" data-post="${p.id}" data-visible="0">다시 공개</button>`}</td>
      </tr>`).join("")
      : `<tr><td colspan="6"><div class="empty"><div class="ico">📝</div>아직 커뮤니티 글이 없습니다</div></td></tr>`;
  }

  async function togglePost(btn) {
    const id = btn.dataset.post;
    const next = btn.dataset.visible !== "1";
    if (!next && !confirm("이 글을 손님 화면에서 숨길까요? 글 내용은 그대로 남습니다.")) return;
    btn.disabled = true;
    try {
      await api(`/api/super-admin/community/${id}`, { method: "PATCH", body: { visible: next } });
      toast(next ? "글을 다시 공개했습니다" : "글을 숨겼습니다", "ok");
      await Promise.all([loadKpi(), loadPosts()]);
    } catch (e) {
      toast(e.message, "err");
      btn.disabled = false;
    }
  }

  // ---------------------------------------------------------------- 탭·바인딩
  function showTab(name) {
    S.tab = name;
    $$(".sa-tab").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
    ["entities", "orders", "community", "audit"].forEach((key) => {
      const el = $(`#panel-${key}`);
      if (el) el.classList.toggle("hidden", key !== name);
    });
    if (name === "orders" && !loadedOrders) { loadedOrders = true; loadOrders().catch((e) => toast(e.message, "err")); }
    if (name === "community" && !loadedPosts) { loadedPosts = true; loadPosts().catch((e) => toast(e.message, "err")); }
  }

  $("#tabs").addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-tab]");
    if (btn) showTab(btn.dataset.tab);
  });

  $("#entKind").addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-kind]");
    if (!btn) return;
    S.kind = btn.dataset.kind;
    $$("#entKind .chip").forEach((b) => b.classList.toggle("on", b === btn));
    loadEntities().catch((e) => toast(e.message, "err"));
  });

  $("#entState").addEventListener("change", (ev) => {
    S.state = ev.target.value;
    loadEntities().catch((e) => toast(e.message, "err"));
  });

  let entTimer;
  $("#entQ").addEventListener("input", () => {
    clearTimeout(entTimer);
    entTimer = setTimeout(() => loadEntities().catch((e) => toast(e.message, "err")), 260);
  });

  $("#entityList").addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-store]");
    if (btn) toggleStore(btn);
  });

  $("#ordPay").addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-pay]");
    if (!btn) return;
    S.pay = btn.dataset.pay;
    $$("#ordPay .chip").forEach((b) => b.classList.toggle("on", b === btn));
    loadOrders().catch((e) => toast(e.message, "err"));
  });
  $("#ordReload").addEventListener("click", () => loadOrders().catch((e) => toast(e.message, "err")));
  $("#ordQ").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") loadOrders().catch((e) => toast(e.message, "err"));
  });

  $("#postState").addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-state]");
    if (!btn) return;
    S.postState = btn.dataset.state;
    $$("#postState .chip").forEach((b) => b.classList.toggle("on", b === btn));
    loadPosts().catch((e) => toast(e.message, "err"));
  });
  $("#postReload").addEventListener("click", () => loadPosts().catch((e) => toast(e.message, "err")));
  $("#postQ").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") loadPosts().catch((e) => toast(e.message, "err"));
  });
  $("#postList").addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-post]");
    if (btn) togglePost(btn);
  });

  $("#refreshBtn").addEventListener("click", () => {
    Promise.all([loadKpi(), loadEntities(),
      loadedOrders ? loadOrders() : null, loadedPosts ? loadPosts() : null])
      .then(() => toast("새로 불러왔습니다", "ok"))
      .catch((e) => toast(e.message, "err"));
  });

  async function init() {
    try {
      await loadKpi();
      await loadEntities();
    } catch (e) {
      const box = $("#saAlert");
      if (box) {
        box.className = "alert";
        box.textContent = e.message;
      }
    }
  }

  init();
})();
