// QR · NFC · 메뉴판/웨이팅 안내물 인쇄
(() => {
  renderNav("qr");
  const S = { base: location.origin, options: {}, stand: {}, tables: [], nfc: [], tab: "tables", v: Date.now() };

  async function init() {
    const [info, cfg] = await Promise.all([api("/api/server-info"), api("/api/qr/config")]);
    const isLocal = ["localhost", "127.0.0.1", "::1"].includes(location.hostname);
    const lan = info.lanIps?.[0];
    S.base = (lan && isLocal) ? `http://${lan}:${location.port || info.port}` : location.origin;
    $("#baseInput").value = S.base;
    $("#baseHint").textContent = lan ? `같은 와이파이 주소: http://${lan}:${location.port || info.port}` : "";
    S.options = cfg.options;
    S.stand = cfg.stand;
    S.tables = cfg.tables;
    S.nfc = cfg.nfc;
    S.storeUrl = cfg.storeUrl;
    fillDesign();
    fillStand();
    renderTables();
    renderStore();
    renderNfc();
    updatePrintLinks();
  }

  /* ---------- 탭 ---------- */
  $$("#tabs .chip").forEach((b) => b.onclick = () => {
    S.tab = b.dataset.tab;
    $$("#tabs .chip").forEach((x) => x.classList.toggle("on", x === b));
    $("#viewTables").classList.toggle("hidden", S.tab !== "tables");
    $("#viewStore").classList.toggle("hidden", S.tab !== "store");
    $("#viewNfc").classList.toggle("hidden", S.tab !== "nfc");
    $("#viewPrint").classList.toggle("hidden", S.tab !== "print");
    $("#designCard").classList.toggle("hidden", !["tables", "store"].includes(S.tab));
    if (S.tab === "store") renderStore();
  });

  /* ---------- 디자인 ---------- */
  function fillDesign() {
    const o = S.options;
    $("#optDot").value = o.dot || "rounded";
    $("#optEye").value = o.eye || "rounded";
    $("#optFg").value = o.fg || "#1f2a44";
    $("#optFgText").value = o.fg || "#1f2a44";
    $("#optBg").value = o.bg || "#fdf3e3";
    $("#optBgText").value = o.bg || "#fdf3e3";
    $("#optBadge").value = o.badge || "initial";
    $("#optCaption").value = o.caption || "auto";
  }

  function designPayload() {
    return {
      dot: $("#optDot").value, eye: $("#optEye").value,
      fg: $("#optFgText").value.trim(), bg: $("#optBgText").value.trim(),
      badge: $("#optBadge").value, caption: $("#optCaption").value.trim(),
    };
  }

  $("#optFg").oninput = (e) => { $("#optFgText").value = e.target.value; previewDesign(); };
  $("#optBg").oninput = (e) => { $("#optBgText").value = e.target.value; previewDesign(); };
  $("#optFgText").onchange = (e) => { $("#optFg").value = e.target.value; };
  $("#optBgText").onchange = (e) => { $("#optBg").value = e.target.value; };
  ["#optDot", "#optEye", "#optBadge", "#optCaption"].forEach((sel) => $(sel).onchange = previewDesign);

  let previewTimer;
  function previewDesign() {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(async () => {
      try {
        await api("/api/qr/config", { method: "PATCH", body: { options: designPayload() } });
        S.options = { ...S.options, ...designPayload() };
        S.v = Date.now();
        renderTables();
        renderStore();
        verifyDesign();
        updatePrintLinks();
      } catch (e) { toast(e.message, "err"); }
    }, 350);
  }

  async function verifyDesign() {
    try {
      const code = (S.tables.find((t) => t.active) || S.tables[0] || {}).code;
      const r = await api(`/api/qr/verify?base=${encodeURIComponent(S.base)}${code ? `&code=${code}` : ""}`);
      if (r.ok === true) {
        $("#verifyState").innerHTML = `✅ 스캔 확인됨 · <span class="muted">${esc(r.url)}</span>`;
      } else if (r.ok === false) {
        $("#verifyState").innerHTML = `⚠️ 스캔 확인 실패 — 단순 QR로 대체됩니다`;
      } else {
        $("#verifyState").textContent = "스캔 확인 도구 없음(자동 확인 생략)";
      }
    } catch (e) { $("#verifyState").textContent = ""; }
  }

  $("#saveDesign").onclick = async () => {
    try {
      await api("/api/qr/config", { method: "PATCH", body: { options: designPayload() } });
      toast("디자인을 저장했습니다", "ok");
      await refresh();
    } catch (e) { toast(e.message, "err"); }
  };

  $("#badgeFile").onchange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      const dataUrl = await shrinkImage(file, 320);
      const res = await api("/api/qr/badge", { method: "POST", body: { dataUrl } });
      S.options = res.options;
      fillDesign();
      await refresh();
      toast("배지 이미지를 올렸습니다", "ok");
    } catch (err) { toast(err.message, "err"); }
  };

  function shrinkImage(file, max) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      const url = URL.createObjectURL(file);
      img.onload = () => {
        const s = Math.min(1, max / Math.max(img.width, img.height));
        const c = document.createElement("canvas");
        c.width = Math.round(img.width * s); c.height = Math.round(img.height * s);
        c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
        URL.revokeObjectURL(url);
        resolve(c.toDataURL("image/png"));
      };
      img.onerror = () => reject(new Error("이미지를 읽지 못했습니다"));
      img.src = url;
    });
  }

  async function refresh() {
    const cfg = await api("/api/qr/config");
    S.options = cfg.options; S.tables = cfg.tables; S.nfc = cfg.nfc; S.v = Date.now();
    renderTables(); renderStore(); renderNfc(); updatePrintLinks();
    verifyDesign();
  }

  /* ---------- 테이블 QR ---------- */
  function renderTables() {
    const list = S.tables.filter((t) => t.active);
    $("#tableCount").textContent = `사용 중인 테이블 ${list.length}개`;
    $("#qgrid").innerHTML = list.map((t) => {
      const url = `${S.base}/t/${t.code}`;
      const q = `base=${encodeURIComponent(S.base)}&v=${S.v}`;
      return `<div class="qcard">
        <div class="tno">${esc(t.label)}</div>
        <div class="shop">${esc((S.storeName || ""))}</div>
        <img class="qr" src="/api/qr/${t.code}.png?${q}&px=8" alt="${esc(t.label)} QR" width="210" height="210">
        <div class="url">${esc(url)}</div>
        <div class="dl no-print">
          <a class="btn sm ghost" href="/api/qr/${t.code}.png?${q}&px=16" download="table-${esc(t.code)}-qr.png">PNG</a>
          <a class="btn sm ghost" href="/api/qr/${t.code}.svg?${q}&px=10" download="table-${t.code}-qr.svg">SVG</a>
          <a class="btn sm ghost" href="/t/${esc(t.code)}" target="_blank">열어 보기</a>
        </div>
      </div>`;
    }).join("") || '<div class="empty">사용 중인 테이블이 없습니다. <a href="/tables">테이블을 추가</a>해 주세요.</div>';
  }

  /* ---------- 매장 공통 ---------- */
  function renderStore() {
    const q = `base=${encodeURIComponent(S.base)}&v=${S.v}`;
    $("#storeQr").src = `/api/qr/store.png?${q}&px=10`;
    $("#storeUrl").textContent = S.base + "/";
    $("#storePng").href = `/api/qr/store.png?${q}&px=16`;
    $("#storeSvg").href = `/api/qr/store.svg?${q}&px=10`;
  }

  /* ---------- NFC ---------- */
  function renderNfc() {
    $("#nfcList").innerHTML = `<table class="table">
      <thead><tr><th>테이블</th><th>NFC / QR 주소</th><th></th></tr></thead>
      <tbody>${S.nfc.map((n) => `<tr>
        <td><b>${esc(n.label)}</b> ${n.active ? "" : '<span class="badge red">비활성</span>'}</td>
        <td class="small" style="word-break:break-all">${esc(n.url)}</td>
        <td class="nowrap"><button class="btn sm ghost" data-copy="${esc(n.url)}">복사</button></td>
      </tr>`).join("")}</tbody></table>`;
    $$("#nfcList [data-copy]").forEach((b) => b.onclick = async () => {
      try { await navigator.clipboard.writeText(b.dataset.copy); toast("주소를 복사했습니다", "ok"); }
      catch (e) { toast(b.dataset.copy); }
    });
  }

  $("#nfcCsv").onclick = () => {
    const rows = [["테이블", "코드", "주소", "상태"]].concat(
      S.nfc.map((n) => [n.label, n.code, n.url, n.active ? "사용" : "비활성"]));
    const csv = "\ufeff" + rows.map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = "nfc-urls.csv";
    a.click();
  };

  $("#nfcPrint").onclick = () => {
    const w = window.open("", "_blank");
    if (!w) { toast("팝업이 막혔습니다", "err"); return; }
    w.document.write(`<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>NFC 주소 목록</title>
      <style>body{font-family:sans-serif;padding:18px}h1{font-size:20px}table{width:100%;border-collapse:collapse;font-size:13px}
      td,th{border:1px solid #ccc;padding:6px 8px;text-align:left}</style></head><body>
      <h1>NFC 태그 주소 목록</h1><table><tr><th>테이블</th><th>주소</th></tr>
      ${S.nfc.map((n) => `<tr><td>${esc(n.label)}</td><td>${esc(n.url)}</td></tr>`).join("")}</table>
      <script>window.onload=()=>window.print();</script></body></html>`);
    w.document.close();
  };

  /* ---------- 인쇄물 ---------- */
  function fillStand() {
    const st = S.stand || {};
    $("#stTitle").value = st.title || "메뉴 보기 · 주문";
    $("#stSubtitle").value = st.subtitle || "휴대폰으로 찍어 주문하세요";
    $("#stSteps").value = st.steps || "1. 카메라로 QR 찍기|2. 메뉴 고르기|3. 장바구니로 주문";
    $("#stNfc").value = st.nfc || "";
    $("#stFooter").value = st.footer || "";
    $("#stAccent").value = st.accent || "#d9480f";
  }

  function standPayload() {
    return {
      title: $("#stTitle").value.trim(), subtitle: $("#stSubtitle").value.trim(),
      steps: $("#stSteps").value.trim(), nfc: $("#stNfc").value.trim(),
      footer: $("#stFooter").value.trim(), accent: $("#stAccent").value,
    };
  }

  $("#saveStand").onclick = async () => {
    try {
      await api("/api/qr/config", { method: "PATCH", body: { stand: standPayload() } });
      S.stand = { ...S.stand, ...standPayload() };
      toast("인쇄물 문구를 저장했습니다", "ok");
      updatePrintLinks();
    } catch (e) { toast(e.message, "err"); }
  };

  function updatePrintLinks() {
    const size = $("#printSize").value || "A5";
    const layout = $("#printLayout").value || "1";
    const first = (S.tables.find((t) => t.active) || {}).code;
    const firstWait = `?code=${first || 1}&size=${size === "A6" ? "A5" : size}&v=${S.v}`;
    $("#pdfBtn").href = `/api/print/stands.pdf?size=${size}&layout=${layout}`;
    $("#standPreview").src = `/api/print/stand.png${firstWait}`;
    $("#openPrint").onclick = () => window.open(`/print?kind=table&size=${size}&layout=${layout}`, "_blank");
    if (typeof updateWaitLinks === "function" && $("#waitSize")) updateWaitLinks();
  }

  $("#printSize").onchange = updatePrintLinks;
  $("#printLayout").onchange = updatePrintLinks;
  $("#waitSize").onchange = updateWaitLinks;
  $("#waitPrintOpen").onclick = () => window.open(`/print?kind=wait&size=${$("#waitSize").value}`, "_blank");

  function updateWaitLinks() {
    const size = $("#waitSize").value || "B4";
    $("#waitPdfLink").href = `/api/print/stands.pdf?kind=wait&size=${size}`;
    $("#waitPreview").src = `/api/print/wait.png?size=${size}&v=${S.v}`;
  }
  $("#stAccent").onchange = () => { saveStandSilent(); };
  async function saveStandSilent() {
    try {
      await api("/api/qr/config", { method: "PATCH", body: { stand: standPayload() } });
      S.stand = { ...S.stand, ...standPayload() };
      updatePrintLinks();
    } catch (e) { toast(e.message, "err"); }
  }

  $("#applyBase").onclick = () => {
    S.base = $("#baseInput").value.trim().replace(/\/$/, "");
    S.v = Date.now();
    renderTables(); renderStore(); updatePrintLinks(); verifyDesign();
    toast("주소를 적용했습니다", "ok");
  };

  $("#pngAll").onclick = () => {
    const list = S.tables.filter((t) => t.active);
    list.forEach((t, i) => setTimeout(() => {
      const a = document.createElement("a");
      a.href = `/api/qr/${t.code}.png?base=${encodeURIComponent(S.base)}&px=16&v=${S.v}`;
      a.download = `table-${t.code}-qr.png`;
      a.click();
    }, i * 400));
  };

  init().then(verifyDesign).catch((e) => toast(e.message, "err"));
})();
