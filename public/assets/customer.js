// 고객 화면: QR로 들어온 테이블에서 메뉴 → 장바구니 → 주문(현금 결제)
(() => {
  const TABLE_CODE = decodeURIComponent((location.pathname.match(/\/t\/([^\/?#]+)/) || [])[1] || "1");
  const TABLE = 0;                       // 서버에서 테이블 정보를 받아 채운다
  const LS_CART = `mangjip.cart.${TABLE_CODE}`;
  const LS_ORDERS = "mangjip.orders";
  const LS_PROFILE = "mangjip.profile";
  const LS_A11Y = "mangjip.a11y";
  const LS_LANG = "mangjip.lang";
  const LANG = ["ko", "en", "zh", "ja"].includes(localStorage.getItem(LS_LANG)) ? localStorage.getItem(LS_LANG) : "ko";
  const PREORDER = new URLSearchParams(location.search).get("preorder") || "";
  const VIA = (new URLSearchParams(location.search).get("via") || "qr").toLowerCase();

  // QR·NFC 어느 쪽으로 들어왔는지 매장에 알린다(개인정보 없음). 실패해도 화면은 그대로.
  if (typeof api === "function") {
    api("/api/public/visit", { method: "POST",
      body: { code: TABLE_CODE, via: VIA, path: location.pathname + location.search } }).catch(() => {});
  }

  const state = {
    store: null,
    categories: [],
    items: [],
    cart: loadJSON(LS_CART, []),
    myOrders: loadJSON(LS_ORDERS, []),
    table: null,
    pointsBalance: 0,
    pointsUsed: 0,
    optionTarget: null,
    optionPick: {},
    currentOrder: null,
    payMethods: [],
    payPick: "CASH",
  };

  function loadJSON(k, d) {
    try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; }
  }
  const saveJSON = (k, v) => localStorage.setItem(k, JSON.stringify(v));

  const itemById = (id) => state.items.find((i) => i.id === id);

  // ---------------------------------------------------------------- 메뉴
  // 응답이 없으면 화면이 '불러오는 중'에서 쌓이지 않게 타임아웃을 둔다.
  async function apiTimeout(path, opts = {}, ms = 15000) {
    if (typeof AbortController === "undefined") return api(path, opts);
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), ms);
    try {
      return await api(path, { ...opts, signal: ctrl.signal });
    } finally {
      clearTimeout(timer);
    }
  }

  async function loadMenu(first) {
    const data = await apiTimeout(`/api/menu?lang=${LANG}`);
    const prev = JSON.stringify(state.items.map((i) => [i.id, i.soldout, i.price, i.image]));
    state.store = data.store;
    if (data.store) {
      const bn = document.querySelector(".cust-head .brand-txt b");
      const tg = document.querySelector(".cust-head .brand-txt span");
      if (bn) bn.textContent = data.store.name;
      if (tg) tg.textContent = data.store.tagline;
      document.title = `${data.store.name} · 테이블 주문`;
    }
    state.categories = data.categories;
    state.items = data.items;
    state.featured = data.featured || { items: [] };
    if (first) loadRecommend();
    document.getElementById("tableNo").textContent = state.table ? state.table.label : TABLE_CODE;
    const now = JSON.stringify(state.items.map((i) => [i.id, i.soldout, i.price, i.image]));
    const changed = prev !== now;
    if (first) renderTabs();
    if (first || changed || JSON.stringify(data.featured) !== state._featSig) {
      state._featSig = JSON.stringify(data.featured);
      renderFeatured();
    }
    if (first || changed) renderMenu();
    return changed;
  }

  // 메뉴를 못 불러왔을 때: 스켈레톤을 닫고 다시 시도 버튼을 보여 준다.
  function showMenuError(e) {
    const loading = document.getElementById("menuLoading");
    if (loading) loading.classList.add("hidden");
    const msg = e && e.name === "AbortError"
      ? "메뉴를 불러오는 데 시간이 오래 걸립니다."
      : (e && e.message) || "메뉴를 불러오지 못했습니다.";
    $("#menuList").innerHTML = `<div class="card pad" style="text-align:center;margin:16px">
      <p style="font-weight:800;margin:6px 0">${esc(msg)}</p>
      <p class="small muted">잠시 뒤 다시 시도하거나 직원에게 말씀해 주세요.</p>
      <button class="btn primary" id="menuRetry" style="margin-top:8px">다시 시도</button></div>`;
    const btn = $("#menuRetry");
    if (btn) btn.onclick = () => {
      btn.disabled = true;
      loadMenu(true).then(() => renderCartBar())
        .catch((err) => { toast(err.message, "err"); btn.disabled = false; });
    };
  }

  function renderTabs() {
    $("#tabs").innerHTML = state.categories
      .map((c) => `<button class="chip" data-cat="${c.id}">${esc(c.name)}</button>`)
      .join("");
    $$("#tabs .chip").forEach((b) =>
      b.addEventListener("click", () => {
        const sec = document.getElementById("cat-" + b.dataset.cat);
        if (sec) sec.scrollIntoView({ behavior: "smooth", block: "start" });
        setActiveTab(b.dataset.cat);
      })
    );
    if (state.categories[0]) setActiveTab(state.categories[0].id);
  }

  function setActiveTab(catId) {
    $$("#tabs .chip").forEach((b) => b.classList.toggle("on", b.dataset.cat === String(catId)));
  }

  function renderMenu() {
    const html = state.categories
      .map((c) => {
        const items = state.items.filter((i) => i.categoryId === c.id);
        if (!items.length) return "";
        return `<section class="cat-sec" id="cat-${c.id}">
          <h2>${esc(c.name)} <small>${items.length}가지</small></h2>
          <div class="grid">${items.map(cardHTML).join("")}</div>
        </section>`;
      })
      .join("");
    $("#menuList").innerHTML = html || `<div class="empty"><div class="ico">🍽️</div>준비된 메뉴가 없습니다</div>`;
    const loading = document.getElementById("menuLoading");
    if (loading) loading.classList.add("hidden");
    $$("#menuList .add").forEach((btn) =>
      btn.addEventListener("click", () => onAdd(Number(btn.dataset.id)))
    );
    $$("#menuList [data-speak]").forEach((btn) => btn.onclick = (e) => {
      e.stopPropagation();
      const it = itemById(Number(btn.dataset.speak));
      if (!it) return;
      if (speaking) { stopSpeak(); btn.textContent = "🔊"; return; }
      speak(it);
      btn.textContent = "⏹";
      setTimeout(() => { if (!window.speechSynthesis.speaking) btn.textContent = "🔊"; }, 300);
    });
  }

  function cardHTML(it) {
    const hasOpt = it.options && it.options.length > 0;
    const img = it.image
      ? `<img src="${esc(it.image)}" alt="${esc(it.name)}" loading="lazy" decoding="async" width="400" height="300">`
      : `<span class="noimg-ico">🍽️</span>`;
    // 원산지·알레르기·매운맛 중 있는 것만 보여 준다(없으면 '정보 없음'으로 채우지 않는다)
    const info = [];
    if (it.origin) info.push(`원산지 ${esc(it.origin)}`);
    if ((it.allergens || []).length) info.push(`알레르기 ${esc(it.allergens.join(", "))}`);
    if (it.spice) info.push("🌶".repeat(it.spice));
    const infoHTML = info.length ? `<div class="info-line">${info.join(" · ")}</div>` : "";
    return `<article class="mcard ${it.soldout ? "out" : ""}">
      <div class="ph ${it.image ? "" : "noimg"}">${img}${hasOpt ? '<span class="opt-tag">옵션 선택</span>' : ""}${it.soldout ? '<div class="soldout">품절</div>' : ""}</div>
      <div class="body">
        <div class="nm">${esc(it.name)}</div>
        <div class="ds">${esc(it.description || "")}</div>
        ${infoHTML}
        <div class="foot">
          <span class="pr nums">${won(it.price)}</span>
          <div class="row" style="gap:6px">
            ${speakerButton(it.id)}
            <button class="add" data-id="${it.id}" ${it.soldout ? "disabled" : ""} aria-label="${esc(it.name)} 담기">+</button>
          </div>
        </div>
      </div>
    </article>`;
  }

  // ---------------------------------------------------------------- 장바구니
  function onAdd(itemId) {
    const it = itemById(itemId);
    if (!it || it.soldout) return;
    if (it.options && it.options.length) {
      state.optionTarget = it;
      state.optionPick = {};
      it.options.forEach((g) => (state.optionPick[g.name] = g.default));
      renderOptionSheet();
      openSheet("optionSheet");
      return;
    }
    pushCart(it.id, {});
    toast(`${it.name} 담았어요`, "ok");
  }

  function pushCart(itemId, options, qty = 1) {
    const key = (o) => itemId + "|" + JSON.stringify(o);
    const found = state.cart.find((l) => l.key === key(options));
    if (found) found.qty += qty;
    else state.cart.push({ key: key(options), itemId, qty, options: options || {} });
    saveJSON(LS_CART, state.cart);
    renderCartBar();
    if (typeof loadPairs === "function") loadPairs();
  }

  function cartTotal() {
    return state.cart.reduce((s, l) => s + (itemById(l.itemId)?.price || 0) * l.qty, 0);
  }
  function cartCount() {
    return state.cart.reduce((s, l) => s + l.qty, 0);
  }

  function renderCartBar() {
    const n = cartCount();
    $("#cartbar").classList.toggle("hidden", n === 0);
    $("#cartCount").textContent = n;
    $("#cartTotal").textContent = won(cartTotal());
    const oc = state.myOrders.length;
    $("#ordersCnt").textContent = oc;
    $("#ordersCnt").classList.toggle("hidden", oc === 0);
  }

  function renderCartSheet() {
    if (!state.cart.length) {
      $("#cartBody").innerHTML = `<div class="empty"><div class="ico">🛒</div>장바구니가 비어 있습니다</div>`;
      $("#cartSum").textContent = "0원";
      return;
    }
    $("#cartBody").innerHTML = state.cart
      .map((l) => {
        const it = itemById(l.itemId);
        if (!it) return "";
        const opt = Object.entries(l.options).map(([k, v]) => `${k}: ${v}`).join(" · ");
        return `<div class="cart-line">
          <div class="th">${it.image ? `<img src="${esc(it.image)}" alt="" loading="lazy">` : ""}</div>
          <div class="grow">
            <div class="nm">${esc(it.name)}</div>
            ${opt ? `<div class="op">${esc(opt)}</div>` : ""}
            <div class="pr nums">${won(it.price * l.qty)}</div>
          </div>
          <div class="qty">
            <button data-dec="${l.key}" aria-label="줄이기">−</button>
            <b class="nums">${l.qty}</b>
            <button data-inc="${l.key}" aria-label="늘리기">+</button>
          </div>
        </div>`;
      })
      .join("");
    $("#cartSum").textContent = won(cartTotal());
    $$("#cartBody [data-inc]").forEach((b) => b.onclick = () => changeQty(b.dataset.inc, 1));
    $$("#cartBody [data-dec]").forEach((b) => b.onclick = () => changeQty(b.dataset.dec, -1));
  }

  function changeQty(key, d) {
    const line = state.cart.find((l) => l.key === key);
    if (!line) return;
    line.qty += d;
    if (line.qty <= 0) state.cart = state.cart.filter((l) => l.key !== key);
    saveJSON(LS_CART, state.cart);
    renderCartSheet();
    renderCartBar();
  }

  // ---------------------------------------------------------------- 옵션
  function renderOptionSheet() {
    const it = state.optionTarget;
    $("#optTitle").textContent = it.name;
    $("#optBody").innerHTML =
      it.options
        .map(
          (g) => `<div class="optgroup">
        <div class="gh">${esc(g.name)}</div>
        <div class="opt-row">${g.choices
          .map(
            (c) =>
              `<button data-g="${esc(g.name)}" data-c="${esc(c)}" class="${
                state.optionPick[g.name] === c ? "on" : ""
              }">${esc(c)}</button>`
          )
          .join("")}</div>
      </div>`
        )
        .join("") + `<p class="muted small">옵션에 따른 추가 금액은 없습니다(시제품).</p>`;
    $$("#optBody .opt-row button").forEach((b) =>
      b.addEventListener("click", () => {
        state.optionPick[b.dataset.g] = b.dataset.c;
        renderOptionSheet();
      })
    );
  }

  $("#optAdd").addEventListener("click", () => {
    const it = state.optionTarget;
    if (!it) return;
    pushCart(it.id, { ...state.optionPick });
    toast(`${it.name} 담았어요`, "ok");
    closeSheets();
  });

  // ---------------------------------------------------------------- 주문서
  function openCheckout() {
    if (!state.cart.length) return;
    closeSheets();
    const lines = state.cart
      .map((l) => {
        const it = itemById(l.itemId);
        const opt = Object.entries(l.options).map(([k, v]) => `${k}: ${v}`).join(", ");
        return `<div class="li"><span>${esc(it.name)}${opt ? ` <span class="muted small">(${esc(opt)})</span>` : ""} × ${l.qty}</span><b class="nums">${won(it.price * l.qty)}</b></div>`;
      })
      .join("");
    if (PREORDER) {
      $("#checkoutSummary").innerHTML = `<div class="pay-note" style="margin-bottom:10px">🍽️ <b>미리 주문</b>입니다. 입장(테이블 배정)하면 조리가 시작됩니다.</div>`;
    }
    $("#checkoutSummary").innerHTML = (PREORDER ? $("#checkoutSummary").innerHTML : "") + `${lines}
      <div class="total"><span>합계</span><span class="nums">${won(cartTotal())}</span></div>`;
    setSubmitLabel(cartTotal());
    loadPayMethods();
    const p = loadJSON(LS_PROFILE, {});
    $("#ckName").value = p.name || "";
    $("#ckPhone").value = p.phone || "";
    $("#ckConsent").checked = !!p.consent;
    openSheet("checkoutSheet");
    setTimeout(() => $("#ckName").focus({ preventScroll: true }), 300);
  }

  // 동네 소식(매장 설정에서 켠 경우에만)
  async function loadCommunity() {
    const box = $("#communityWrap");
    if (!box) return;
    try {
      const d = await api("/api/public/community");
      if (!d.enabled || !(d.posts || []).length) { box.innerHTML = ""; return; }
      box.innerHTML = `<div class="card pad" style="margin:16px 0">
        <h3 style="font-size:17px;margin-bottom:4px">동네 소식</h3>
        ${d.intro ? `<p class="small muted" style="margin:0 0 8px">${esc(d.intro)}</p>` : ""}
        ${d.posts.slice(0, 4).map((p) => `<div style="padding:6px 0;border-bottom:1px solid var(--line)">
          <span class="badge">${esc(p.kindLabel)}</span> <b>${esc(p.title)}</b>
          <div class="small muted">${esc((p.body || "").slice(0, 120))}</div></div>`).join("")}
      </div>`;
    } catch (e) { box.innerHTML = ""; }
  }

  function setSubmitLabel(amount) {
    $("#submitOrder").innerHTML =
      `주문 완료 · <span class="nums" id="ckTotal">${won(amount)}</span>`;
  }

  // ---------------------------------------------------------------- 결제 방법
  async function loadPayMethods() {
    const box = $("#ckPayMethods");
    if (!box) return;
    try {
      const data = await api("/api/payments/methods" + (PREORDER ? "" : ""));
      state.payMethods = data.methods || [];
    } catch (e) {
      state.payMethods = [];
    }
    if (!state.payMethods.length) {
      state.payMethods = [{ code: "CASH", label: "현금", note: "계산대에서 결제" }];
    }
    if (!state.payMethods.some((m) => m.code === state.payPick)) {
      state.payPick = state.payMethods[0].code;
    }
    box.innerHTML = state.payMethods.map((m) =>
      `<label class="row" style="gap:6px;border:1px solid var(--line);border-radius:10px;padding:8px 12px">
        <input type="radio" name="ckPay" value="${esc(m.code)}" ${m.code === state.payPick ? "checked" : ""} style="width:18px;height:18px">
        <span><b>${esc(m.label)}</b>${m.note ? `<span class="small muted"> · ${esc(m.note)}</span>` : ""}</span></label>`).join("");
    $$('#ckPayMethods input[name="ckPay"]').forEach((r) => r.onchange = () => {
      state.payPick = r.value;
      renderTransferBox();
    });
    renderTransferBox();
  }

  function renderTransferBox() {
    const box = $("#ckTransferBox");
    if (!box) return;
    const isTransfer = state.payPick === "TRANSFER";
    box.classList.toggle("hidden", !isTransfer);
    if (!isTransfer) return;
    const m = state.payMethods.find((x) => x.code === "TRANSFER") || {};
    $("#ckBankLine").innerHTML = `<b>${esc(m.bank || "")} ${esc(m.accountNo || "")}</b>` +
      (m.holder ? ` <span class="small muted">예금주 ${esc(m.holder)}</span>` : "");
  }

  $("#submitOrder").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    const name = $("#ckName").value.trim();
    const phone = $("#ckPhone").value.trim();
    const consent = $("#ckConsent").checked;
    if (phone && !consent) {
      toast("연락처를 남기려면 동의에 체크해 주세요", "err");
      return;
    }
    btn.disabled = true;
    btn.textContent = "주문 접수 중…";
    const payMethod = state.payPick || "CASH";
    if (payMethod === "TRANSFER" && !$("#ckDepositor").value.trim()) {
      toast("계좌이체는 입금자명을 넣어 주세요", "err");
      btn.disabled = false;
      setSubmitLabel(cartTotal());
      return;
    }
    try {
      const order = await api("/api/orders", {
        method: "POST",
        body: {
          table: PREORDER ? 0 : state.table.id,
          preorderToken: PREORDER || undefined,
          payMethod,
          receipt: $("#ckReceipt").checked
            ? { type: $("#ckReceiptType").value, no: $("#ckReceiptNo").value.trim() }
            : { type: "none" },
          pointsUsed: state.pointsUsed || 0,
          items: state.cart.map((l) => ({ itemId: l.itemId, qty: l.qty, options: l.options })),
          customer: { name, phone, consent },
          note: $("#ckNote").value.trim(),
        },
      });
      if (payMethod === "TRANSFER") {
        try {
          await api(`/api/orders/${order.id}/transfer`, { method: "POST",
            body: { table: PREORDER ? 0 : state.table.id, depositor: $("#ckDepositor").value.trim() } });
          order.transferAccount = (state.payMethods.find((m) => m.code === "TRANSFER") || {});
        } catch (err2) { toast(err2.message, "err"); }
      }
      saveJSON(LS_PROFILE, { name, phone, consent });
      state.cart = [];
      saveJSON(LS_CART, []);
      state.myOrders = [order.id, ...state.myOrders].slice(0, 20);
      saveJSON(LS_ORDERS, state.myOrders);
      renderCartBar();
      state.currentOrder = order;
      closeSheets();
      renderDone(order);
      openSheet("doneSheet");
      beep(1, 660);
      loadOrders();
    } catch (err) {
      toast(err.message, "err");
    } finally {
      btn.disabled = false;
      setSubmitLabel(0);
    }
  });

  // ---------------------------------------------------------------- 주문 접수/진행
  const STATUS_TEXT = { NEW: "접수 완료", ACCEPTED: "접수 완료", COOKING: "조리 중",
                        DONE: "조리 완료 · 서빙 준비", SERVED: "서빙 완료", CANCELED: "취소됨" };
  const STATUS_CLASS = { NEW: "brand", ACCEPTED: "brand", COOKING: "amber", DONE: "amber",
                          SERVED: "green", CANCELED: "red" };

  // 주방과 같은 4단계: 접수 → 조리중 → 조리완료(서빙 대기) → 서빙 완료
  function stepIndex(st) {
    if (st === "SERVED") return 3;
    if (st === "DONE") return 2;
    if (st === "COOKING") return 1;
    return 0;
  }

  const NOTIFIED = new Set();
  async function notifyProgress(order) {
    if (!("Notification" in window) || Notification.permission !== "granted") return;
    if (order.status === "COOKING" && !NOTIFIED.has(order.id + ":c")) {
      NOTIFIED.add(order.id + ":c");
      notifyNow("조리 시작", `${order.tableLabel || ""} 주문 #${order.orderNo} 조리를 시작했습니다`);
    }
    if (order.status === "DONE" && !NOTIFIED.has(order.id + ":d")) {
      NOTIFIED.add(order.id + ":d");
      notifyNow("준비 완료", `주문 #${order.orderNo} 준비되었습니다 · 테이블에서 기다려 주세요`);
    }
  }
  function notifyNow(title, body) {
    try {
      if (navigator.serviceWorker) {
        navigator.serviceWorker.ready.then((reg) => reg.showNotification(title, { body, tag: "mangjip-order" }))
          .catch(() => { try { new Notification(title, { body }); } catch (e) {} });
      } else { new Notification(title, { body }); }
      beep(2, 880);
    } catch (e) { /* 알림 실패는 무시 */ }
  }

  function progressLine(order) {
    const bits = [`접수 ${(order.createdAt || "").slice(11, 16)}`];
    if (order.acceptedAt) bits.push(`접수확인 ${order.acceptedAt.slice(11, 16)}`);
    if (order.cookingAt) bits.push(`조리 ${order.cookingAt.slice(11, 16)}`);
    if (order.doneAt) bits.push(`조리완료 ${order.doneAt.slice(11, 16)}`);
    if (order.servedAt) bits.push(`서빙 ${order.servedAt.slice(11, 16)}`);
    const est = order.cookEstimate == null ? "계산 중" : `약 ${order.cookEstimate}분`;
    const elapsed = order.elapsedMin != null ? `${order.elapsedMin}분 경과` : "";
    return `<div class="small muted" style="margin-top:6px;line-height:1.6">
      ${bits.join(" · ")}<br>${elapsed}${["NEW", "ACCEPTED", "COOKING"].includes(order.status) ? ` · 예상 ${est}` : ""}
    </div>`;
  }

  function renderDone(order) {
    const step = stepIndex(order.status);
    const steps = ["접수", "조리중", "조리완료", "서빙완료"]
      .map((lbl, i) => `<div class="st ${i < step ? "done" : i === step ? "on" : ""}">
        <div class="bar"></div><div class="lbl">${lbl}</div></div>`)
      .join("");
    const payLabel = order.paymentMethodLabel ||
      { CASH: "현금", TRANSFER: "계좌이체", CARD: "카드", PAY: "간편결제" }[order.paymentMethod] || "현금";
    const acct = order.transferAccount || state.payMethods.find((m) => m.code === "TRANSFER") || {};
    let payNote;
    if (order.paymentStatus === "PAID") {
      payNote = `<div class="pay-note" style="background:var(--green-soft);color:#1f6b38">${esc(payLabel)} 결제가 확인되었습니다. 감사합니다.</div>`;
    } else if (order.paymentMethod === "TRANSFER") {
      payNote = `<div class="pay-note">🏦 <b>${esc(acct.bank || "")} ${esc(acct.accountNo || "")}</b>${acct.holder ? ` (예금주 ${esc(acct.holder)})` : ""}로<br><b class="nums">${won(order.total)}</b>을 입금해 주세요.<br>
        <span style="font-weight:600">입금자명을 남겼습니다. 사장님이 입금을 확인하면 '결제 완료'로 바뀝니다.</span></div>`;
    } else if (order.paymentMethod === "CARD" || order.paymentMethod === "PAY") {
      payNote = `<div class="pay-note">💳 <b>${won(order.total)}</b>은 카운터에서 ${esc(payLabel)}로 결제해 주세요.<br><span style="font-weight:600">사장님이 확인하면 '결제 완료'로 바뀝니다.</span></div>`;
    } else {
      payNote = `<div class="pay-note">💵 <b>${won(order.total)}</b>은 계산대에서 현금으로 결제해 주세요.<br><span style="font-weight:600">사장님이 결제를 확인하면 '결제 완료'로 바뀝니다.</span></div>`;
    }
    $("#doneBody").innerHTML = `
      <div class="done-hero">
        <div class="ok">✓</div>
        <h3 id="doneTitle">${order.status === "SERVED" ? "서빙 완료" : order.status === "DONE" ? "조리가 끝났습니다 (서빙 준비)" : "주문이 접수됐어요"}</h3>
        <p>잠시만 기다려 주세요. 화면이 자동으로 바뀝니다.</p>
      </div>
      <div class="done-meta">
        <div><div class="k">주문번호</div><div class="v">#${esc(order.orderNo)}</div></div>
        <div><div class="k">테이블</div><div class="v">${order.table}번</div></div>
        <div><div class="k">결제</div><div class="v" id="donePay">${order.paymentStatus === "PAID" ? `${esc(payLabel)} 결제 완료` : `${esc(payLabel)} · 확인 전`}</div></div>
        <div><div class="k">금액</div><div class="v nums">${won(order.total)}</div></div>
      </div>
      <h4>진행 상황</h4>
      <div class="steps" id="doneSteps">${steps}</div>
      <div class="muted small" id="doneStatus" style="margin-top:8px">현재: ${STATUS_TEXT[order.status] || order.status}</div>
      ${progressLine(order)}
      ${["NEW", "ACCEPTED"].includes(order.status)
        ? `<button class="btn sm danger" id="cancelOrder" style="margin-top:10px">주문 취소</button>
           <p class="small muted" style="margin:6px 0 0">조리가 시작되기 전까지만 취소할 수 있습니다.</p>`
        : order.status === "COOKING"
          ? `<p class="small muted" style="margin:10px 0 0">조리 중이라 앱에서는 취소할 수 없습니다. 직원에게 말씀해 주세요.</p>`
          : ""}
      ${payNote}
      <div id="reviewBox"></div>
      <div class="cart-line" style="border-top:1px solid var(--line);border-bottom:0;margin-top:8px;padding-bottom:0">
        <div class="grow">${order.items
          .map((i) => `<div style="font-size:14.5px">${esc(i.name)} × ${i.qty}${i.options ? ` <span class="muted small">(${esc(i.options)})</span>` : ""}</div>`)
          .join("")}</div>
      </div>`;
    const cbtn = $("#cancelOrder");
    if (cbtn) cbtn.onclick = () => cancelOrder(order);
    loadReview(order);
    notifyProgress(order);
  }

  // ---------------------------------------------------------------- 리뷰(별점·한 줄)
  async function loadReview(order) {
    const box = $("#reviewBox");
    if (!box) return;
    if (!["DONE", "SERVED"].includes(order.status) && order.paymentStatus !== "PAID") { box.innerHTML = ""; return; }
    try {
      const data = await api(`/api/reviews/order/${order.id}`);
      if (data.review) {
        box.innerHTML = `<div class="review-done">
          <div class="rv-stars">${"★".repeat(data.review.rating)}${"☆".repeat(5 - data.review.rating)}</div>
          <div class="small">${esc(data.review.comment || "평가를 남겨 주셨습니다")}${data.review.reply ? `<br><b>사장님 답글</b> ${esc(data.review.reply)}` : ""}</div>
        </div>`;
        return;
      }
      if (!data.canReview) { box.innerHTML = ""; return; }
      box.innerHTML = `<div class="review-box">
        <div class="rv-title">오늘 어떠셨어요? <span class="small muted">(선택 · 별점·한 줄만 저장)</span></div>
        <div class="rv-pick" id="rvPick">${[1, 2, 3, 4, 5].map((n) => `<button type="button" data-star="${n}" aria-label="${n}점">★</button>`).join("")}</div>
        <input class="input" id="rvComment" maxlength="120" placeholder="한 줄 평가 (선택)">
        <button class="btn sm primary" id="rvSend" style="margin-top:8px">리뷰 남기기</button>
      </div>`;
      let picked = 0;
      $$("#rvPick [data-star]").forEach((b) => b.onclick = () => {
        picked = Number(b.dataset.star);
        $$("#rvPick [data-star]").forEach((x) => x.classList.toggle("on", Number(x.dataset.star) <= picked));
      });
      const send = async () => {
        if (!picked) { toast("별점을 먼저 골라 주세요", "err"); return; }
        const btn = $("#rvSend");
        btn.disabled = true;
        try {
          await api("/api/reviews", { method: "POST", body: { orderId: order.id, rating: picked, comment: $("#rvComment").value } });
          toast("리뷰를 남겼습니다. 감사합니다!", "ok");
          await loadReview(order);
        } catch (e) { toast(e.message, "err"); btn.disabled = false; }
      };
      $("#rvSend").onclick = send;
    } catch (e) { box.innerHTML = ""; }
  }

  async function refreshCurrent() {
    if (!state.currentOrder) return;
    try {
      const o = await api("/api/orders/" + state.currentOrder.id);
      const changed = o.status !== state.currentOrder.status || o.paymentStatus !== state.currentOrder.paymentStatus;
      state.currentOrder = o;
      if (changed && $("#doneSheet").classList.contains("on")) {
        renderDone(o);
        if (o.status === "COOKING") toast("조리를 시작했어요", "ok");
        if (o.status === "DONE") { toast("조리가 끝났습니다. 곧 서빙해 드릴게요", "ok"); beep(2, 720); }
        if (o.status === "SERVED") toast("맛있게 드세요!", "ok");
      }
    } catch (e) { /* 무시 */ }
  }

  // ---------------------------------------------------------------- 내 주문 내역
  async function loadOrders() {
    if (!state.myOrders.length) {
      $("#orderList").innerHTML = `<div class="empty"><div class="ico">🧾</div>아직 주문한 내역이 없습니다</div>`;
      renderTrack();
      return;
    }
    const rows = [];
    for (const id of state.myOrders.slice(-10)) {
      try { rows.push(await api("/api/orders/" + id)); } catch (e) { /* 지워진 주문 */ }
    }
    state.orders = rows.sort((a, b) => b.id - a.id);
    renderOrders();
    renderTrack();
    renderCartBar();
  }

  function renderOrders() {
    const list = (state.orders || []).slice().sort((a, b) => b.id - a.id);
    $("#orderList").innerHTML = list.length
      ? list.map(orderCard).join("")
      : `<div class="empty"><div class="ico">🧾</div>아직 주문한 내역이 없습니다</div>`;
    $$("#orderList [data-cancel]").forEach((b) =>
      b.addEventListener("click", () => {
        const o = state.orders.find((x) => x.id === Number(b.dataset.cancel));
        if (o) cancelOrder(o);
      })
    );
    $$("#orderList [data-open]").forEach((b) =>
      b.addEventListener("click", () => {
        state.currentOrder = state.orders.find((o) => o.id === Number(b.dataset.open));
        renderDone(state.currentOrder);
        openSheet("doneSheet");
      })
    );
  }

  function orderCard(o) {
    return `<article class="card order-card">
      <div class="hd">
        <span class="no">#${esc(o.orderNo)}</span>
        <span class="badge ${STATUS_CLASS[o.status] || ""}">${STATUS_TEXT[o.status] || o.status}</span>
        <span class="when">${hhmm(o.createdAt)} · ${esc(o.tableLabel || o.table + "번")}</span>
      </div>
      <div class="items">${o.items.map((i) => `${esc(i.name)} ×${i.qty}`).join(", ")}</div>
      <div class="ft">
        <span class="total nums">${won(o.total)}</span>
        <span class="badge ${o.paymentStatus === "PAID" ? "green" : "amber"}">${o.paymentStatus === "PAID" ? "현금 결제 완료" : "결제 전"}</span>
        ${["NEW", "ACCEPTED"].includes(o.status) ? `<button class="btn sm danger" data-cancel="${o.id}">취소</button>` : ""}
        <button class="btn sm ghost" style="margin-left:auto" data-open="${o.id}">상세</button>
      </div>
    </article>`;
  }

  function renderTrack() {
    const active = (state.orders || []).find((o) => ["NEW", "ACCEPTED", "COOKING", "DONE"].includes(o.status));
    if (!active) { $("#trackWrap").innerHTML = ""; return; }
    $("#trackWrap").innerHTML = `<div class="track"><button class="track-card" id="trackBtn">
      <div><div class="no">#${esc(active.orderNo)} 주문</div>
      <div class="st">${ago(active.createdAt)} · ${won(active.total)} · ${active.paymentStatus === "PAID" ? "결제 완료" : "계산대에서 현금 결제"}</div></div>
      <span class="badge ${STATUS_CLASS[active.status]}">${STATUS_TEXT[active.status]}</span>
    </button></div>`;
    $("#trackBtn").onclick = () => {
      state.currentOrder = active;
      renderDone(active);
      openSheet("doneSheet");
    };
  }

  // ---------------------------------------------------------------- 시트 제어
  // 닫힌 시트는 화면 낭독기·키보드 탭에서 빠지게 한다(aria-hidden · inert).
  function syncSheets() {
    $$(".sheet").forEach((s) => {
      const open = s.classList.contains("on");
      s.setAttribute("aria-hidden", open ? "false" : "true");
      if (open) s.removeAttribute("inert");
      else s.setAttribute("inert", "");
    });
    const back = $("#back");
    if (back) back.setAttribute("aria-hidden", back.classList.contains("on") ? "false" : "true");
  }

  function openSheet(id) {
    $("#back").classList.add("on");
    $$(".sheet").forEach((s) => s.classList.remove("on"));
    const el = document.getElementById(id);
    el.classList.add("on");
    el.dataset.open = "1";
    syncSheets();
  }
  function closeSheets() {
    $("#back").classList.remove("on");
    $$(".sheet").forEach((s) => s.classList.remove("on"));
    const done = $("#doneSheet");
    if (done) done.dataset.open = "";
    syncSheets();
  }
  syncSheets();
  $("#back").addEventListener("click", closeSheets);
  $$("[data-close]").forEach((b) => b.addEventListener("click", closeSheets));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeSheets(); });

  $("#cartOpen").addEventListener("click", () => { renderCartSheet(); openSheet("cartSheet"); });
  $("#toCheckout").addEventListener("click", openCheckout);

  // 세그먼트 탭
  $$("#seg .seg-btn").forEach((b) =>
    b.addEventListener("click", () => {
      $$("#seg .seg-btn").forEach((x) => x.classList.toggle("on", x === b));
      const v = b.dataset.view;
      $("#viewMenu").classList.toggle("hidden", v !== "menu");
      $("#viewOrders").classList.toggle("hidden", v !== "orders");
      $("#tabs").classList.toggle("hidden", v !== "menu");
      if (v === "orders") loadOrders();
      window.scrollTo({ top: 0 });
    })
  );

  // 스크롤하면 카테고리 탭 표시가 따라간다
  let scrollLock = false;
  window.addEventListener("scroll", () => {
    if (scrollLock) return;
    const tabsBottom = 180;
    let current = null;
    $$(".cat-sec").forEach((sec) => {
      if (sec.getBoundingClientRect().top <= tabsBottom) current = sec.id.replace("cat-", "");
    });
    if (current) setActiveTab(current);
  }, { passive: true });

  // ---------------------------------------------------------------- 추천·예상시간
  async function loadRecommend() {
    try {
      const data = await api(`/api/recommend?table=${state.table ? state.table.id : ""}`);
      renderReorder(data.reorder || []);
      renderEstimate(data.estimate || {});
    } catch (e) { /* 무시 */ }
  }

  function renderReorder(items) {
    const wrap = $("#reorderWrap");
    if (!wrap) return;
    const list = (items || []).filter((i) => itemById(i.id) && !itemById(i.id).soldout);
    if (!list.length) { wrap.innerHTML = ""; return; }
    wrap.innerHTML = `<section class="feat">
      <h2>🔁 또 시킬까요? <span class="small muted">· 이 테이블에서 시킨 메뉴</span></h2>
      <div class="feat-row">${list.map((i) => {
        const live = itemById(i.id);
        return `<article class="fcard" data-reorder="${i.id}">
          <div class="ph">${live.image ? `<img src="${esc(live.image)}" alt="${esc(live.name)}" loading="lazy">` : ""}</div>
          <div class="body"><div class="nm">${esc(live.name)}</div>
            <div class="pr nums">${won(live.price)}</div></div>
        </article>`;
      }).join("")}</div></section>`;
    $$("#reorderWrap .fcard").forEach((c) => c.onclick = () => {
      const it = itemById(Number(c.dataset.reorder));
      if (!it || it.soldout) { toast("품절된 메뉴입니다", "err"); return; }
      onAdd(it.id);
    });
  }

  function renderEstimate(est) {
    const el = $("#estimateLine");
    if (!el) return;
    if (!est || est.minutes == null) {
      el.className = "estimate unknown";
      el.innerHTML = `<span class="dot"></span> 지금 주문하면 <b>계산 중</b>`;
      return;
    }
    el.className = `estimate ${est.level}`;
    el.innerHTML = `<span class="dot"></span> 지금 주문하면 약 <b>${est.minutes}분</b>
      <span class="badge ${est.level === "busy" ? "red" : est.level === "normal" ? "amber" : "green"}">${esc(est.label)}</span>`;
  }

  async function loadPairs() {
    const box = $("#pairBox");
    if (!box) return;
    const ids = state.cart.map((l) => l.itemId);
    if (!ids.length) { box.innerHTML = ""; return; }
    try {
      const data = await api(`/api/recommend?table=${state.table ? state.table.id : ""}&items=${ids.join(",")}`);
      const pairs = (data.pairs || []).filter((p) => !itemById(p.id)?.soldout);
      box.innerHTML = pairs.length ? `<div class="pair-box">
        <b class="small">함께 많이 시키는 메뉴</b>
        <div class="row wrap" style="gap:8px;margin-top:6px">
          ${pairs.map((p) => `<button class="btn sm" data-pair="${p.id}">+ ${esc(itemById(p.id)?.name || p.name)} <span class="muted tiny">${p.togetherCount}회</span></button>`).join("")}
        </div></div>` : "";
      $$("#pairBox [data-pair]").forEach((b) => b.onclick = () => {
        const it = itemById(Number(b.dataset.pair));
        if (it) onAdd(it.id);
      });
    } catch (e) { box.innerHTML = ""; }
  }

  // ---------------------------------------------------------------- 접근성 설정
  const A11Y_DEFAULT = { font: 1, contrast: false, motion: false, voice: false };

  function loadA11y() {
    let cfg = A11Y_DEFAULT;
    try { cfg = { ...A11Y_DEFAULT, ...(JSON.parse(localStorage.getItem(LS_A11Y)) || {}) }; } catch (e) {}
    return cfg;
  }

  function applyA11y(cfg) {
    document.body.classList.toggle("font2", cfg.font === 2);
    document.body.classList.toggle("font3", cfg.font === 3);
    document.body.classList.toggle("contrast", !!cfg.contrast);
    document.body.classList.toggle("nomotion", !!cfg.motion);
    document.body.classList.toggle("voice-big", !!cfg.voice);
    localStorage.setItem(LS_A11Y, JSON.stringify(cfg));
  }

  function initA11y() {
    const cfg = loadA11y();
    applyA11y(cfg);
    $$("#a11yPanel [data-font]").forEach((b) => {
      b.classList.toggle("primary", Number(b.dataset.font) === cfg.font);
      b.onclick = () => {
        cfg.font = Number(b.dataset.font);
        $$("#a11yPanel [data-font]").forEach((x) => x.classList.toggle("primary", x === b));
        applyA11y(cfg);
      };
    });
    $("#a11yContrast").checked = !!cfg.contrast;
    $("#a11yMotion").checked = !!cfg.motion;
    $("#a11yVoice").checked = !!cfg.voice;
    $("#a11yContrast").onchange = (e) => { cfg.contrast = e.target.checked; applyA11y(cfg); };
    $("#a11yMotion").onchange = (e) => { cfg.motion = e.target.checked; applyA11y(cfg); };
    $("#a11yVoice").onchange = (e) => { cfg.voice = e.target.checked; applyA11y(cfg); };
    $("#a11yBtn").onclick = () => {
      const panel = $("#a11yPanel");
      panel.classList.toggle("hidden");
      $("#a11yBtn").setAttribute("aria-expanded", String(!panel.classList.contains("hidden")));
      if (!panel.classList.contains("hidden")) $("#a11yClose").focus();
    };
    $("#a11yClose").onclick = () => {
      $("#a11yPanel").classList.add("hidden");
      $("#a11yBtn").setAttribute("aria-expanded", "false");
      $("#a11yBtn").focus();
    };
    if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches && cfg.motion === false) {
      document.body.classList.add("nomotion");
    }
  }

  // ---------------------------------------------------------------- 읽어 주기(TTS)
  const TTS = "speechSynthesis" in window;
  let speaking = null;

  function readItemText(item) {
    const bits = [item.name, `${item.price.toLocaleString()}원`, item.description || ""];
    if (item.origin) bits.push(`원산지 ${item.origin}`);
    if (item.allergens && item.allergens.length) bits.push(`알레르기: ${item.allergens.join(", ")}`);
    if (item.spice) bits.push(`매운맛 ${item.spice}단계`);
    if (item.options && item.options.length) {
      bits.push(item.options.map((g) => `${g.name}: ${g.options ? g.choices.join(", ") : g.choices.join(", ")}`).join(". "));
    }
    return bits.filter(Boolean).join(". ");
  }

  function speak(item) {
    if (!TTS) return;
    stopSpeak();
    const u = new SpeechSynthesisUtterance(readItemText(item));
    u.lang = "ko-KR";
    u.rate = 0.98;
    u.onend = () => { speaking = null; };
    speaking = u;
    window.speechSynthesis.speak(u);
  }

  function stopSpeak() {
    if (TTS && window.speechSynthesis.speaking) window.speechSynthesis.cancel();
    speaking = null;
  }

  function speakerButton(itemId) {
    if (!TTS) return "";
    return `<button class="spk" data-speak="${itemId}" aria-label="${esc(itemById(itemId)?.name || "메뉴")} 읽어 주기">🔊</button>`;
  }

  // ---------------------------------------------------------------- 테이블·추천
  async function loadTable() {
    const data = await api(`/api/table/${encodeURIComponent(TABLE_CODE)}`);
    state.table = data.table;
    const chip = document.querySelector(".table-chip b");
    if (chip) chip.textContent = data.table.label;
    if (!data.table.active) {
      renderBlocked(`'${data.table.label}' 테이블은 지금 주문을 받지 않습니다. 직원에게 문의해 주세요.`);
      throw new Error("inactive-table");
    }
  }

  function renderBlocked(message) {
    document.body.innerHTML = `<main style="max-width:520px;margin:56px auto;padding:0 18px">
      <div class="card pad" style="text-align:center">
        <div style="font-size:42px">🙏</div>
        <h1 style="font-size:23px;margin:10px 0 6px">지금은 주문을 받지 않습니다</h1>
        <p class="muted" style="line-height:1.6">${esc(message)}</p>
        <a class="btn primary" href="/order" style="margin-top:14px">테이블 다시 고르기</a>
      </div></main>`;
  }

  function renderFeatured() {
    const wrap = $("#featuredWrap");
    if (!wrap) return;
    const f = state.featured || { items: [] };
    const items = (f.items || []).filter((i) => itemById(i.id));
    if (!items.length) { wrap.innerHTML = ""; return; }
    wrap.innerHTML = `<section class="feat">
      <h2>🔥 추천 메뉴 ${f.auto ? '<span class="small muted">· 잘 팔리는 메뉴</span>' : ""}</h2>
      <div class="feat-row">${items.map((i) => {
        const live = itemById(i.id);
        return `<article class="fcard ${live.soldout ? "out" : ""}" data-id="${i.id}">
          <div class="ph">${live.image ? `<img src="${esc(live.image)}" alt="${esc(live.name)}" loading="lazy">` : ""}
            ${live.soldout ? '<div class="soldout">품절</div>' : ""}</div>
          <div class="body">
            <div class="nm">${esc(live.name)}</div>
            ${i.featuredNote ? `<div class="nt">${esc(i.featuredNote)}</div>` : ""}
            <div class="pr nums">${won(live.price)}</div>
          </div>
        </article>`;
      }).join("")}</div></section>`;
    $$("#featuredWrap .fcard").forEach((card) => card.onclick = () => {
      const it = itemById(Number(card.dataset.id));
      if (!it || it.soldout) { toast("품절된 메뉴입니다", "err"); return; }
      onAdd(it.id);
    });
  }

  // ---------------------------------------------------------------- 포인트
  function maxPoints() {
    return Math.max(0, Math.min(state.pointsBalance || 0, Math.floor(cartTotal() / 2)));
  }

  function updateCheckoutTotals() {
    state.pointsUsed = Math.max(0, Math.min(Number(state.pointsUsed || 0), maxPoints()));
    const amount = Math.max(0, cartTotal() - state.pointsUsed);
    setSubmitLabel(amount);
    const total = $("#checkoutSummary .total");
    if (total) {
      total.innerHTML = `<span>합계</span><span class="nums">${won(amount)}</span>`
        + (state.pointsUsed ? `<div class="small muted" style="width:100%;text-align:right">포인트 ${state.pointsUsed.toLocaleString()}P 사용</div>` : "");
    }
  }

  async function refreshPoints() {
    const box = $("#pointsBox");
    if (!box) return;
    const phone = ($("#ckPhone").value || "").trim();
    const digits = phone.replace(/[^0-9]/g, "");
    state.pointsBalance = 0;
    state.pointsUsed = 0;
    if (digits.length < 10) { box.classList.add("hidden"); updateCheckoutTotals(); return; }
    try {
      const r = await api(`/api/member/lookup?phone=${encodeURIComponent(phone)}`);
      if (!r.member || !r.points) { box.classList.add("hidden"); updateCheckoutTotals(); return; }
      state.pointsBalance = r.points;
      box.classList.remove("hidden");
      $("#pointsHave").textContent = `보유 ${r.points.toLocaleString()}P`;
      const max = maxPoints();
      $("#pointsInput").max = String(max);
      $("#pointsInput").value = "0";
      $("#pointsNote").textContent = `이번 주문에서는 최대 ${max.toLocaleString()}P까지 쓸 수 있습니다.`;
      updateCheckoutTotals();
    } catch (e) { box.classList.add("hidden"); updateCheckoutTotals(); }
  }

  // ---------------------------------------------------------------- 음성 주문
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const V = { rec: null, listening: false, last: null, permission: "unknown" };

  function initVoice() {
    const btn = $("#voiceBtn"), hint = $("#micHint");
    if (!btn) return;
    if (!SR) {
      btn.textContent = "⌨️ 메뉴로 주문";
      btn.onclick = () => toast("이 브라우저는 음성 주문이 안 됩니다. 메뉴를 눌러 주문해 주세요", "err");
      if (hint) hint.textContent = "이 브라우저는 음성 미지원 · 메뉴를 눌러 주문해 주세요";
      return;
    }
    if (location.protocol !== "https:" && !["localhost", "127.0.0.1"].includes(location.hostname)) {
      if (hint) hint.textContent = "음성은 https(localhost)에서만 동작합니다";
    }
    btn.onclick = openVoice;
    checkMicPermission();
  }

  async function checkMicPermission() {
    const hint = $("#micHint");
    if (!hint || !navigator.permissions || !navigator.permissions.query) return;
    try {
      const st = await navigator.permissions.query({ name: "microphone" });
      V.permission = st.state;
      hint.textContent = st.state === "granted"
        ? "마이크 허용됨 · 버튼 한 번이면 바로 인식합니다"
        : st.state === "denied"
          ? "마이크가 꺼져 있습니다 · 주소창 자물쇠 → 마이크 허용"
          : "음성은 브라우저 음성인식(구글)으로 처리됩니다";
      st.onchange = checkMicPermission;
    } catch (e) { /* 권한 이름을 지원하지 않는 브라우저 */ }
  }

  function openVoice() {
    $("#voiceHeard").textContent = "";
    $("#voiceHeard").className = "voice-heard empty";
    $("#voiceResult").innerHTML = "";
    $("#voiceConfirm").classList.add("hidden");
    V.last = null;
    openSheet("voiceSheet");
    if (V.permission === "denied") {
      $("#micState").textContent = "마이크가 꺼져 있습니다. 주소창 자물쇠 → 마이크 허용 후 다시 시도해 주세요.";
      $("#micStart").classList.add("hidden");
      return;
    }
    $("#micState").textContent = "듣고 있습니다… 메뉴와 수량을 말해 주세요";
    $("#micStart").classList.remove("hidden");
    startVoice();   // 버튼을 누른 그 순간이라 권한 요청이 바로 뜬다
  }

  function startVoice() {
    if (!SR) return;
    if (V.rec) { try { V.rec.stop(); } catch (e) {} }
    const rec = new SR();
    rec.lang = "ko-KR";
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    rec.continuous = false;
    rec.onstart = () => {
      V.listening = true;
      $("#micState").textContent = "듣고 있습니다… 말씀해 주세요";
      $("#micStart").textContent = "🎤 다시 말하기";
      $("#voiceBtn").classList.add("listening");
    };
    rec.onerror = (e) => {
      V.listening = false;
      $("#voiceBtn").classList.remove("listening");
      if (e.error === "not-allowed" || e.error === "service-not-allowed") {
        V.permission = "denied";
        $("#micState").textContent = "마이크 권한이 없습니다. 주소창 자물쇠 → 마이크 허용으로 바꿔 주세요.";
      } else if (e.error === "no-speech") {
        $("#micState").textContent = "잘 듣지 못했습니다. 다시 한 번 말해 주세요.";
      } else if (e.error === "network") {
        $("#micState").textContent = "음성인식 서버(구글)에 연결하지 못했습니다. 메뉴를 눌러 주문해 주세요.";
      } else {
        $("#micState").textContent = "인식하지 못했습니다. 다시 시도하거나 메뉴를 눌러 주문해 주세요.";
      }
      checkMicPermission();
    };
    rec.onend = () => {
      V.listening = false;
      $("#voiceBtn").classList.remove("listening");
    };
    rec.onresult = (ev) => {
      const text = (ev.results[0] && ev.results[0][0] ? ev.results[0][0].transcript : "").trim();
      if (text) handleHeard(text);
    };
    V.rec = rec;
    try { rec.start(); } catch (e) {
      $("#micState").textContent = "음성인식을 시작하지 못했습니다. 메뉴를 눌러 주문해 주세요.";
    }
  }

  async function handleHeard(text) {
    $("#voiceHeard").textContent = `“${text}”`;
    $("#voiceHeard").className = "voice-heard";
    $("#micState").textContent = "해석하는 중…";
    try {
      const r = await api("/api/voice/parse", { method: "POST", body: { text } });
      V.last = r;
      renderVoiceResult(r);
    } catch (e) {
      $("#micState").textContent = e.message;
    }
  }

  function renderVoiceResult(r) {
    const parts = [];
    (r.lines || []).forEach((l) => {
      const opt = Object.entries(l.options || {}).map(([k, v]) => `${k}: ${v}`).join(", ");
      parts.push(`<div class="voice-line"><span>담기 · ${esc(l.name)}${opt ? `<span class="muted small"> (${esc(opt)})</span>` : ""}</span><b>${l.qty}개</b></div>`);
    });
    (r.removed || []).forEach((l) => {
      parts.push(`<div class="voice-line"><span>빼기 · ${esc(l.name)}</span><b>${l.qty}개</b></div>`);
    });
    (r.unknown || []).forEach((u) => parts.push(`<div class="small" style="color:var(--brand);padding:6px 0">${esc(u)}</div>`));
    if ((r.candidates || []).length) {
      parts.push(`<p class="small muted" style="margin:10px 0 4px">어떤 메뉴인가요?</p>
        <div class="voice-cand">${r.candidates.map((c) => `<button class="btn sm" data-cand="${c.itemId}" ${c.soldout ? "disabled" : ""}>${esc(c.name)}${c.soldout ? " (품절)" : ""}</button>`).join("")}</div>`);
    }
    $("#voiceResult").innerHTML = parts.join("") || `<p class="small muted">${esc(r.message || "")}</p>`;
    $("#micState").textContent = r.message || "";
    $("#voiceConfirm").classList.toggle("hidden", !((r.lines || []).length || (r.removed || []).length));
    $$("#voiceResult [data-cand]").forEach((b) => b.onclick = () => {
      const it = itemById(Number(b.dataset.cand));
      if (it) { onAdd(it.id); closeSheets(); }
    });
  }

  function removeFromCart(itemId, options, qty) {
    const key = itemId + "|" + JSON.stringify(options || {});
    let line = state.cart.find((l) => l.key === key);
    if (!line) line = state.cart.find((l) => l.itemId === itemId);
    if (!line) return false;
    line.qty = Math.max(0, line.qty - Math.max(1, qty || 1));
    state.cart = state.cart.filter((l) => l.qty > 0);
    saveJSON(LS_CART, state.cart);
    renderCartBar();
    return true;
  }

  $("#voiceConfirm").onclick = () => {
    const r = V.last;
    if (!r) return;
    let added = 0, removed = 0;
    (r.lines || []).forEach((l) => { pushCart(l.itemId, l.options || {}, l.qty); added += l.qty; });
    (r.removed || []).forEach((l) => { if (removeFromCart(l.itemId, l.options || {}, l.qty)) removed += 1; });
    toast(`${added ? `${added}개 담았습니다` : ""}${added && removed ? " · " : ""}${removed ? `${removed}개 뺐습니다` : ""}`, "ok");
    closeSheets();
  };
  $("#voiceCancel").onclick = () => {
    V.last = null;
    $("#voiceResult").innerHTML = "";
    $("#voiceHeard").textContent = "";
    $("#voiceConfirm").classList.add("hidden");
    $("#micState").textContent = "취소했습니다. 다시 말하거나 메뉴를 눌러 주문해 주세요.";
  };
  $("#micStart").onclick = startVoice;

  // ---------------------------------------------------------------- 직원 호출
  async function callStaff() {
    if (!state.table) return;
    try {
      const r = await api("/api/calls", { method: "POST", body: { table: state.table.id } });
      toast(r.reused ? "이미 호출되어 있습니다. 곧 가겠습니다" : "직원을 불렀습니다. 곧 가겠습니다", "ok");
      renderCall(r.call);
    } catch (e) { toast(e.message, "err"); }
  }

  function renderCall(call) {
    const bar = $("#callBar");
    if (!bar) return;
    if (!call) { bar.classList.add("hidden"); return; }
    bar.classList.remove("hidden");
    $("#callTime").textContent = `${(call.createdAt || "").slice(11, 16)} 호출`;
  }

  async function loadCall() {
    if (!state.table) return;
    try {
      const data = await api(`/api/calls?table=${state.table.id}`);
      renderCall((data.calls || [])[0]);
    } catch (e) { /* 네트워크 끊김은 조용히 넘어간다 */ }
  }

  // ---------------------------------------------------------------- 손님 주문 취소
  async function cancelOrder(order) {
    if (!["NEW", "ACCEPTED"].includes(order.status)) {
      toast("조리가 시작되어 앱에서는 취소할 수 없습니다. 직원에게 말씀해 주세요", "err");
      return;
    }
    const reason = window.prompt("주문을 취소할까요? 취소 후에는 되돌릴 수 없습니다.\n사유(선택): 주문 실수 / 메뉴 변경 / 기타", "");
    if (reason === null) return;
    try {
      await api(`/api/orders/${order.id}/cancel`, {
        method: "POST", body: { table: state.table.id, reason } });
      toast("주문을 취소했습니다", "ok");
      await loadOrders();
      await refreshCurrent();
    } catch (e) { toast(e.message, "err"); }
  }

  // ---------------------------------------------------------------- 첫 방문 안내
  function initGuide() {
    const key = `mangjip.guide.${TABLE_CODE}`;
    if (localStorage.getItem(key) === "done") { $("#guide")?.classList.add("hidden"); return; }
    $("#guide")?.classList.remove("hidden");
    const close = () => {
      localStorage.setItem(key, "done");
      $("#guide").classList.add("hidden");
    };
    $("#guideOk").onclick = close;
    $("#guideVoice").onclick = () => { close(); openVoice(); };
  }

  // ---------------------------------------------------------------- 시작
  (async function init() {
    initGuide();
    initA11y();
    window.addEventListener("beforeunload", stopSpeak);
    document.addEventListener("visibilitychange", () => { if (document.hidden) stopSpeak(); });
    $("#callBtn").onclick = callStaff;
    $("#langSelect").value = LANG;
    $("#langSelect").onchange = (e) => {
      localStorage.setItem(LS_LANG, e.target.value);
      location.reload();
    };
    $("#ckReceipt").onchange = (e) => {
      $("#receiptFields").style.display = e.target.checked ? "flex" : "none";
      if (e.target.checked) $("#ckReceiptNo").focus();
    };
    $("#ckReceiptType").onchange = () => {
      $("#ckReceiptNo").placeholder = $("#ckReceiptType").value === "biz" ? "000-00-00000" : "010-0000-0000";
    };
    if (!SR) { /* 음성 미지원 브라우저 */ }
    initVoice();
    // 메뉴를 먼저 요청해 두고 테이블 확인과 동시에 진행한다(첫 화면이 더 빨리 짜진다).
    const menuReady = loadMenu(true).catch((e) => {
      if (document.getElementById("menuList")) showMenuError(e);
    });
    try {
      await loadTable();
    } catch (e) {
      return;   // 비활성·없는 테이블은 안내 화면만 보여 준다
    }
    await menuReady;
    renderCartBar();
    await loadOrders();
    loadCall();
    loadCommunity();
    pollEvery(async () => {
      await refreshCurrent();
      let changed = false;
      try {
        changed = await loadMenu(false);
      } catch (e) {
        return;   // 잠시 통신이 끊겨도 화면을 지우지 않는다(다음 차례에 다시 시도)
      }
      if (changed) renderCartSheet();
      await loadOrders();
      await loadCall();
    }, 4000);
  })();

  // 주문서: 연락처를 넣으면 보유 포인트를 확인한다
  $("#ckPhone").addEventListener("change", refreshPoints);
  $("#ckPhone").addEventListener("blur", refreshPoints);
  $("#pointsInput").addEventListener("input", () => {
    state.pointsUsed = Number($("#pointsInput").value || 0);
    updateCheckoutTotals();
    $("#pointsInput").value = String(state.pointsUsed);
  });
  $("#pointsAll").addEventListener("click", () => {
    state.pointsUsed = maxPoints();
    $("#pointsInput").value = String(state.pointsUsed);
    updateCheckoutTotals();
  });
})();
