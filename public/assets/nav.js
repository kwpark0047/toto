// 사장님 콘솔 공통 네비게이션 + 출퇴근 버튼 + 매장 전환.
// 각 페이지에서 renderNav("orders") 처럼 호출한다. 권한(권한 키)에 따라 보이는 메뉴가 다르다.
const NAV_ITEMS = [
  ["/admin", "주문", "orders", ["order.manage"]],
  ["/kitchen", "주방", "kitchen", ["kitchen.view"]],
  ["/reservations", "예약", "reservations", ["order.manage"]],
  ["/customers", "회원", "customers", ["customer.view"]],
  ["/wait/admin", "웨이팅", "wait", ["order.manage"]],
  ["/menu", "메뉴", "menu", ["menu.edit", "price.edit", "soldout.manage"]],
  ["/inventory", "재고", "inventory", ["menu.edit", "soldout.manage"]],
  ["/revenue", "매출", "revenue", ["sales.view"]],
  ["/reviews", "리뷰", "reviews", ["customer.view", "settings.edit"]],
  ["/tables", "테이블", "tables", ["settings.edit"]],
  ["/staff", "직원", "staff", ["staff.manage"]],
  ["/stores", "매장", "stores", ["settings.edit"]],
  ["/community", "동네", "community", ["settings.edit", "order.manage"]],
  ["/settings", "설정", "settings", ["settings.edit"]],
  ["/qr", "QR", "qr", ["settings.edit"]],
];

let __mePromise = null;
function me(force) {
  if (!force) return __mePromise || (__mePromise = api("/api/auth/me"));
  __mePromise = api("/api/auth/me");
  return __mePromise;
}

function roleIcon(role) {
  return { admin: "👑", head: "🎖", manager: "📋", counter: "🧾", hall: "🍽", kitchen: "🍳", part: "⏱" }[role] || "👤";
}

function can(me, perms) {
  if (!me || !me.user) return false;
  if (me.user.role === "admin") return true;
  const mine = me.user.permissions || [];
  return (perms || []).some((p) => mine.includes(p));
}

async function logout() {
  try { await api("/api/auth/logout", { method: "POST", body: {} }); } catch (e) { /* 무시 */ }
  location.href = "/login";
}

/* 출근/퇴근 버튼 한 벌 */
function clockButtonHTML(clock) {
  if (!clock) return "";
  if (clock.open) {
    return `<button class="btn sm green" data-clock="out" title="오늘 ${clock.clockIn ? clock.clockIn.slice(11, 16) : ""} 출근">
      🕒 퇴근 (${minutesText(clock.openMinutes)} 근무 중)</button>`;
  }
  return `<button class="btn sm" data-clock="in">🕒 출근하기</button>`;
}

function bindClock(root) {
  const btn = root.querySelector("[data-clock]");
  if (!btn) return;
  btn.onclick = async () => {
    btn.disabled = true;
    const act = btn.dataset.clock === "out" ? "clock-out" : "clock-in";
    try {
      const r = await api(`/api/attendance/${act}`, { method: "POST", body: {} });
      toast(act === "clock-in"
        ? `출근 기록 · ${r.record.clockIn.slice(11, 16)}`
        : `퇴근 기록 · 오늘 ${minutesText(r.clock.todayMinutes)} 근무`, "ok");
      await renderNavRefresh();
    } catch (e) {
      toast(e.message, "err");
      btn.disabled = false;
    }
  };
}

/* 매장 전환 (관리자) */
function storeSwitchHTML(data) {
  if (!data.canSwitchStore || !(data.stores || []).length) return "";
  const current = data.storeId || (data.user && data.user.storeId) || 1;
  const opts = data.stores.map((s) =>
    `<option value="${s.id}" ${s.id === current ? "selected" : ""}>${esc(s.name)}</option>`).join("");
  return `<select class="select sm" id="storeSwitch" title="일하는 매장 바꾸기"
     style="max-width:140px;min-height:38px">${opts}</select>`;
}

function bindStoreSwitch(root) {
  const sel = root.querySelector("#storeSwitch");
  if (!sel) return;
  sel.onchange = async () => {
    sel.disabled = true;
    try {
      await api("/api/stores/switch", { method: "POST", body: { storeId: Number(sel.value) } });
      toast("매장을 바꿨습니다", "ok");
      location.reload();
    } catch (e) {
      toast(e.message, "err");
      sel.disabled = false;
    }
  };
}

let __active = "";
async function renderNav(active) {
  __active = active || __active;
  const el = document.getElementById("nav");
  if (!el) return;
  let data;
  try { data = await me(); } catch (e) { return; }
  const user = data.user;
  if (!user) return;
  const items = NAV_ITEMS.filter(([, , , perms]) => can(data, perms));
  el.className = "topbar";
  el.innerHTML = `<div class="inner">
    <a class="brandmark" href="/admin">
      <span class="logo">${esc((data.store.name || "맛").slice(0, 1))}</span>
      <span><b>${esc(data.store.name || "맛집")}</b><span>사장님 콘솔 · ${esc(user.roleLabel)}</span></span>
    </a>
    <nav class="mainnav">
      ${items.map(([href, label, key]) =>
        `<a href="${href}" class="${key === __active ? "on" : ""}">${label}</a>`).join("")}
    </nav>
    <div class="row" style="gap:6px;margin-left:6px">
      ${storeSwitchHTML(data)}
      ${clockButtonHTML(data.clock)}
      <a class="badge line" href="/account" title="내 계정·비밀번호 변경">${roleIcon(user.role)} ${esc(user.name)}</a>
      <button class="btn sm ghost" data-logout title="로그아웃">나가기</button>
    </div>
  </div>`;
  const out = el.querySelector("[data-logout]");
  if (out) out.onclick = logout;
  bindClock(el);
  bindStoreSwitch(el);
  if (user.mustChange) {
    toast("임시 비밀번호로 로그인했습니다. 내 계정에서 비밀번호를 바꿔 주세요", "err");
  }
}

async function renderNavRefresh() {
  await me(true);
  await renderNav(__active);
}

/* 주방 화면용: 출퇴근 + 로그아웃만 */
async function renderStaffTools() {
  const el = document.querySelector("[data-staff-tools]");
  if (!el) return;
  let data;
  try { data = await me(); } catch (e) { return; }
  if (!data.user) return;
  el.innerHTML = `${clockButtonHTML(data.clock)}
    <a class="kbtn ghost" href="/account">${esc(data.user.name)} · 내 계정</a>
    <button class="kbtn ghost" data-logout>나가기</button>`;
  el.querySelector("[data-logout]").onclick = logout;
  bindClock(el);
}
