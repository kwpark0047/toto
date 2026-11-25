// 인쇄 화면 — 용도(테이블 메뉴판 / 웨이팅 안내) · 용지 크기 · 배치
(() => {
  const q = new URLSearchParams(location.search);
  const kind = q.get("kind") === "wait" ? "wait" : "table";
  let size = (q.get("size") || (kind === "wait" ? "B4" : "A5")).toUpperCase();
  let layout = Number(q.get("layout") || 1);
  const PAPERS = { A6: [105, 148], A5: [148, 210], A4: [210, 297], B4: [250, 353], A3: [297, 420] };
  const MULTI = ["A4", "B4", "A3"];

  async function load() {
    if (layout > 1 && !MULTI.includes(size)) layout = 1;
    const url = kind === "wait"
      ? `/api/print/stands?kind=wait&size=${size}&layout=1`
      : `/api/print/stands?kind=table&size=${size}&layout=${layout}`;
    const data = await api(url);
    render(data);
  }

  function render(data) {
    const tables = data.tables || [];
    $("#meta").textContent = `${kind === "wait" ? "웨이팅 안내" : "테이블 메뉴판"} · ${size} · ${tables.length}개`;
    $("#pdf").href = `/api/print/stands.pdf?kind=${kind}&size=${size}&layout=${layout}`;
    $("#pdf").textContent = `PDF 내려받기 (${size})`;

    let sheetW = data.sheet[0], sheetH = data.sheet[1];
    let cols = 1, rows = 1;
    if (kind === "table" && layout === 2) { cols, rows = 1, 2; }
    if (kind === "table" && layout === 4) { cols, rows = 2, 2; }
    if (kind === "table" && layout === 1) { cols, rows = 1, 1; }
    const perSheet = cols * rows;

    // 인쇄 CSS 용지 지정
    const style = document.createElement("style");
    style.textContent = `@page { size: ${sheetW}mm ${sheetH}mm; margin: 0; }`;
    document.head.appendChild(style);

    const sheets = [];
    for (let i = 0; i < tables.length; i += perSheet) {
      const batch = tables.slice(i, i + perSheet);
      const cells = batch.map((t, j) => {
        const col = j % cols, row = Math.floor(j / cols);
        const cw = 100 / cols, ch = 100 / rows;
        return `<img src="${t.image}&v=${Date.now()}" alt="${esc(t.label)}"
          style="left:${col * cw + 2}%;top:${row * ch + 2}%;width:${cw - 4}%;height:${ch - 4}%">`;
      }).join("");
      sheets.push(`<div class="sheet" style="width:${sheetW}mm;height:${sheetH}mm">${cells}</div>`);
    }
    $("#sheets").innerHTML = sheets.join("");
    document.title = `${kind === "wait" ? "웨이팅 안내" : "테이블 메뉴판"} · ${size}`;
  }

  $("#printBtn").onclick = () => window.print();
  load().catch((e) => {
    $("#sheets").innerHTML = `<div class="card pad">${esc(e.message)}</div>`;
  });
})();
