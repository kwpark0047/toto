// 매장위치 — 공개 매장 목록(지역·검색 필터)
(() => {
  const S = { stores: [], regions: [], region: "", q: "" };

  function chip(label, value, on) {
    return `<button class="chip ${on ? "on" : ""}" data-region="${esc(value)}">${esc(label)}</button>`;
  }

  function renderChips() {
    const box = $("#regionChips");
    if (!box) return;
    box.innerHTML = [chip("전체", "", !S.region)]
      .concat(S.regions.map((r) => chip(r, r, S.region === r)))
      .join("");
    $$("#regionChips .chip").forEach((b) => b.addEventListener("click", () => {
      S.region = b.dataset.region || "";
      renderChips();
      render();
    }));
  }

  function matched() {
    const q = S.q.trim().toLowerCase();
    return S.stores.filter((s) => {
      if (S.region && s.region !== S.region) return false;
      if (!q) return true;
      return [s.name, s.tagline, s.address, s.region, s.phone]
        .join(" ").toLowerCase().includes(q);
    });
  }

  function render() {
    const grid = $("#placeGrid");
    const count = $("#placeCount");
    if (!grid) return;
    const list = matched();
    if (count) count.textContent = `${list.length}곳`;
    if (!list.length) {
      grid.innerHTML = `<div class="place" style="grid-column:1/-1;text-align:center">
        <div style="font-size:34px">🔍</div>
        <h3 style="margin-top:8px">조건에 맞는 매장이 없습니다</h3>
        <p class="muted small" style="margin-top:6px">검색어를 지우거나 다른 지역을 골라 보세요.</p>
      </div>`;
      return;
    }
    grid.innerHTML = list.map((s) => `<article class="place">
      <div class="ph-line">
        <span class="badge brand">${esc(s.region || "매장")}</span>
        <span class="badge line">테이블 ${s.tableCount}개</span>
      </div>
      <div>
        <h3>${esc(s.name)}</h3>
        <div class="tag">${esc(s.tagline || "QR로 주문하는 매장")}</div>
      </div>
      <dl>
        ${s.address ? `<div><dt>주소</dt><dd>${esc(s.address)}</dd></div>` : ""}
        ${s.phone ? `<div><dt>전화</dt><dd>${esc(s.phone)}</dd></div>` : ""}
        ${s.hours ? `<div><dt>영업</dt><dd>${esc(s.hours)}</dd></div>` : ""}
      </dl>
      <div class="actions">
        <a class="btn sm primary" href="${esc(s.orderUrl)}">주문 화면</a>
        <a class="btn sm" href="${esc(s.waitUrl)}">웨이팅</a>
        <a class="btn sm ghost" href="${esc(s.reserveUrl)}">예약</a>
      </div>
    </article>`).join("");
  }

  async function load() {
    try {
      const data = await api("/api/public/stores");
      S.stores = data.stores || [];
      S.regions = data.regions || [];
      renderChips();
      render();
    } catch (e) {
      $("#placeGrid").innerHTML = `<div class="place" style="grid-column:1/-1">
        <h3>매장 목록을 불러오지 못했습니다</h3>
        <p class="muted small" style="margin-top:6px">${esc(e.message)}</p></div>`;
    }
  }

  const search = $("#placeSearch");
  if (search) {
    search.addEventListener("input", () => { S.q = search.value || ""; render(); });
  }
  load();
})();
