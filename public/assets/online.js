// 포장·배달 주문(온라인) — 매장 설정에서 온라인 주문을 켠 매장만 열립니다.
(() => {
  const STORE = new URLSearchParams(location.search).get("store") || "";
  const Q = STORE ? `?store=${encodeURIComponent(STORE)}` : "";
  const S = { store: null, categories: [], items: [], cart: [], channel: "", pay: "CASH",
              methods: [], tab: "" };

  const won = (n) => `${Number(n || 0).toLocaleString()}원`;
  const itemById = (id) => S.items.find((i) => i.id === Number(id));

  async function init() {
    try {
      const data = await api("/api/menu" + (Q ? Q + "&lang=ko" : "?lang=ko"));
      S.store = data.store || {};
      S.categories = data.categories || [];
      S.items = data.items || [];
      $("onName").textContent = S.store.name || "맛집";
      document.title = `${S.store.name || "맛집"} · 포장 주문`;
      const ch = S.store.channel || {};
      const parts = [];
      if (ch.pickup) parts.push(`포장${ch.pickupMin ? ` ${ch.pickupMin}분` : ""}`);
      if (ch.delivery) parts.push(`배달${ch.deliveryFee ? ` ${won(ch.deliveryFee)}` : ""}`);
      $("onLine").textContent = parts.length ? parts.join(" · ") : "온라인 주문";
      $("onNote").textContent = ch.onlineNote || "";
      const open = ["online", "both"].includes(ch.mode) && (ch.pickup || ch.delivery);
      $("onClosed").classList.toggle("hidden", !!open);
      if (!open) { $("onMenu").innerHTML = ""; return; }
      S.channel = ch.pickup ? "pickup" : "delivery";
      await loadPayments();
      renderTabs();
      renderMenu();
    } catch (e) {
      $("onMenu").innerHTML = `<p class="small muted">${esc(e.message)}</p>`;
    }
  }

  async function loadPayments() {
    try {
      const d = await api("/api/payments/methods" + (Q || ""));
      S.methods = d.methods || [];
    } catch (e) { S.methods = []; }
    if (!S.methods.length) S.methods = [{ code: "CASH", label: "현금", note: "" }];
  }

  function renderTabs() {
    S.tab = S.categories.length ? S.categories[0].id : "";
    $("onTabs").innerHTML = S.categories.map((c) =>
      `<button class="chip" data-cat="${c.id}">${esc(c.name)}</button>`).join("");
    bindTabs();
  }
  function bindTabs() {
    $$("#onTabs [data-cat]").forEach((b) => b.onclick = () => {
      S.tab = Number(b.dataset.cat);
      $$("#onTabs [data-cat]").forEach((x) => x.classList.toggle("on", x === b));
      renderMenu();
    });
    const first = document.querySelector("#onTabs [data-cat]");
    if (first) first.classList.add("on");
  }

  function renderMenu() {
    const list = S.items.filter((i) => i.categoryId === S.tab || i.category === (S.categories.find((c) => c.id === S.tab) || {}).name);
    const rows = (list.length ? list : S.items).map((i) => {
      const inCart = S.cart.find((l) => l.itemId === i.id);
      return `<div class="on-item">
        ${i.image ? `<img src="${esc(i.image)}" alt="" loading="lazy">` : '<div style="width:68px;height:68px;border-radius:10px;background:#eee"></div>'}
        <div class="grow"><b>${esc(i.name)}</b>
          <div class="small muted">${esc(i.description || "")}</div>
          <div class="nums" style="font-weight:800;margin-top:2px">${won(i.price)}</div></div>
        <div class="qtybox"><button data-minus="${i.id}">−</button><b>${inCart ? inCart.qty : 0}</b>
          <button data-plus="${i.id}" ${i.soldout ? "disabled" : ""}>+</button></div>
      </div>`;
    }).join("");
    $("onMenu").innerHTML = rows || '<p class="small muted">메뉴가 없습니다.</p>';
    $$("#onMenu [data-plus]").forEach((b) => b.onclick = () => add(Number(b.dataset.plus), 1));
    $$("#onMenu [data-minus]").forEach((b) => b.onclick = () => add(Number(b.dataset.minus), -1));
  }

  function add(id, delta) {
    const it = itemById(id);
    if (!it) return;
    if (it.soldout && delta > 0) { toast("품절입니다", "err"); return; }
    let line = S.cart.find((l) => l.itemId === id);
    if (!line) {
      if (delta < 0) return;
      line = { itemId: id, qty: 0, options: {} };
      S.cart.push(line);
    }
    line.qty += delta;
    S.cart = S.cart.filter((l) => l.qty > 0);
    renderMenu();
    renderCart();
  }

  function cartTotal() {
    return S.cart.reduce((sum, l) => sum + (itemById(l.itemId)?.price || 0) * l.qty, 0);
  }

  function renderCart() {
    const n = S.cart.reduce((a, l) => a + l.qty, 0);
    $("onCart").classList.toggle("hidden", n === 0);
    $("cartCount").textContent = `${n}개`;
    $("cartTotal").textContent = won(cartTotal());
  }

  $("cartGo").onclick = () => openSheet();

  function openSheet() {
    if (!S.cart.length) return;
    const ch = S.store.channel || {};
    $("onSummary").innerHTML = S.cart.map((l) => {
      const it = itemById(l.itemId);
      return `<div class="row between" style="padding:3px 0"><span>${esc(it.name)} × ${l.qty}</span><b class="nums">${won(it.price * l.qty)}</b></div>`;
    }).join("") + `<div class="row between" style="padding:6px 0;border-top:1px solid var(--line)"><b>합계</b><b class="nums">${won(cartTotal())}</b></div>`;
    const chans = [];
    if (ch.pickup) chans.push(["pickup", "포장"]);
    if (ch.delivery) chans.push(["delivery", "배달"]);
    $("onChannels").innerHTML = chans.map(([code, label]) =>
      `<label class="row" style="gap:6px;border:1px solid var(--line);border-radius:10px;padding:8px 12px">
        <input type="radio" name="onCh" value="${code}" ${S.channel === code ? "checked" : ""} style="width:18px;height:18px"><span>${label}</span></label>`).join("");
    $$('#onChannels input[name="onCh"]').forEach((r) => r.onchange = () => {
      S.channel = r.value;
      $("onAddrField").classList.toggle("hidden", S.channel !== "delivery");
    });
    $("onAddrField").classList.toggle("hidden", S.channel !== "delivery");
    $("onPays").innerHTML = S.methods.map((m) =>
      `<label class="row" style="gap:6px;border:1px solid var(--line);border-radius:10px;padding:8px 12px">
        <input type="radio" name="onPay" value="${esc(m.code)}" ${S.pay === m.code ? "checked" : ""} style="width:18px;height:18px">
        <span><b>${esc(m.label)}</b></span></label>`).join("");
    $$('#onPays input[name="onPay"]').forEach((r) => r.onchange = () => { S.pay = r.value; renderPay(); });
    renderPay();
    $("back").classList.add("on");
    $("onSheet").classList.add("on");
  }

  function renderPay() {
    const m = S.methods.find((x) => x.code === S.pay) || {};
    const tr = S.pay === "TRANSFER";
    $("onDepField").classList.toggle("hidden", !tr);
    $("onBank").classList.toggle("hidden", !tr);
    if (tr) $("onBank").innerHTML = `🏦 <b>${esc(m.bank || "")} ${esc(m.accountNo || "")}</b>${m.holder ? ` (예금주 ${esc(m.holder)})` : ""}`;
  }

  function closeSheet() {
    $("back").classList.remove("on");
    $("onSheet").classList.remove("on");
  }
  $("back").onclick = closeSheet;
  $$("[data-close]").forEach((b) => b.onclick = closeSheet);

  $("onSubmit").onclick = async () => {
    const name = $("onNameInput").value.trim();
    const phone = $("onPhone").value.trim();
    const consent = $("onConsent").checked;
    if (!name || !phone) { toast("이름과 연락처를 넣어 주세요", "err"); return; }
    if (!consent) { toast("연락처 이용 동의에 체크해 주세요", "err"); return; }
    const addr = $("onAddr").value.trim();
    if (S.channel === "delivery" && !addr) { toast("배달 주소를 넣어 주세요", "err"); return; }
    if (S.pay === "TRANSFER" && !$("onDepositor").value.trim()) { toast("입금자명을 넣어 주세요", "err"); return; }
    const memo = [$("onMemo").value.trim(), S.channel === "delivery" ? `배달 주소: ${addr}` : ""]
      .filter(Boolean).join(" / ");
    const btn = $("onSubmit");
    btn.disabled = true;
    try {
      const order = await api("/api/orders" + (Q ? Q + "&" : "?"),
        { method: "POST", body: {
          channel: S.channel, payMethod: S.pay,
          items: S.cart.map((l) => ({ itemId: l.itemId, qty: l.qty })),
          customer: { name, phone, consent }, note: memo,
        } });
      if (S.pay === "TRANSFER") {
        await api(`/api/orders/${order.id}/transfer`, { method: "POST",
          body: { depositor: $("onDepositor").value.trim() } });
      }
      S.cart = [];
      renderCart();
      closeSheet();
      $("onCart").classList.add("hidden");
      $("onMenu").innerHTML = `<div class="card pad" style="text-align:center">
        <div style="font-size:38px">✓</div><h2 style="margin:8px 0">주문이 접수됐어요</h2>
        <p>주문번호 <b>#${esc(order.orderNo)}</b> · ${won(order.total)}</p>
        <p class="small muted">${S.pay === "TRANSFER" ? "입금 후 사장님이 확인하면 결제 완료로 바뀝니다." : "준비되면 연락드립니다."}</p>
        <p class="small muted">진행 상황은 사장님 화면에서 확인됩니다.</p></div>`;
    } catch (e) {
      toast(e.message, "err");
    } finally {
      btn.disabled = false;
    }
  };

  init();
})();
