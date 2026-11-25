// 매장 공통 진입(/order) — 손님이 테이블을 고른다
(() => {
  const PREORDER = new URLSearchParams(location.search).get("preorder") || "";
  const STORE = new URLSearchParams(location.search).get("store") || "";
  const storeQ = STORE ? `store=${encodeURIComponent(STORE)}` : "";
  const link = (code) => {
    const params = [];
    if (PREORDER) params.push("preorder=" + encodeURIComponent(PREORDER));
    if (storeQ) params.push(storeQ);
    return "/t/" + encodeURIComponent(code) + (params.length ? "?" + params.join("&") : "");
  };

  async function init() {
    try {
      const data = await api("/api/tables/public" + (STORE ? `?store=${encodeURIComponent(STORE)}` : ""));
      const st = data.store || {};
      $("#storeName").textContent = st.name || "맛집";
      $("#logo").textContent = (st.name || "맛").slice(0, 1);
      document.title = `${st.name || "맛집"} · 테이블을 골라 주문`;
      if (st.tagline) $("#storeLine").textContent = st.tagline;
      $("#hoursLine").textContent = st.hours ? `영업시간 ${st.hours}` : "";

      $("#tableRow").innerHTML = (data.tables || []).length
        ? data.tables.map((t) => `<a class="tbtn" href="${link(t.code)}">
            <b>${esc(t.label)}</b><span>${t.seats ? t.seats + "석" : "메뉴 보기"}</span></a>`).join("")
        : '<p class="small muted">등록된 테이블이 없습니다. 직원에게 문의해 주세요.</p>';
    } catch (e) {
      $("#tableRow").innerHTML = `<p class="small muted">${esc(e.message)}</p>`;
    }
  }

  $("#manualGo").onclick = () => {
    const code = $("#manualCode").value.trim();
    if (!code) return;
    location.href = link(code);
  };
  $("#manualCode").addEventListener("keydown", (e) => {
    if (e.key === "Enter") $("#manualGo").click();
  });
  init();
})();
