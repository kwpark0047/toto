// 메인 랜딩 — 손님/사장님 흐름 애니메이션(4단계)
(() => {
  const STEPS = {
    guest: [
      { label: "QR·NFC 스캔",
        title: "테이블에서 QR만 찍으면 끝",
        desc: "앱 설치도, 회원가입도 없습니다. 테이블의 QR·NFC를 대면 그 테이블 메뉴가 바로 열리고, 처음 온 손님도 3초 만에 주문 화면을 봅니다." },
      { label: "메뉴 선택 · 음성 주문",
        title: "사진·원산지·알레르기까지 한눈에",
        desc: "큰 글씨와 고대비 화면, 한국어·영어·중국어·일본어 전환. 말로 “김치찌개 하나 담아줘”라고 해도 장바구니에 담깁니다." },
      { label: "4단계 실시간 현황",
        title: "기다리는 동안 진행 상황이 보입니다",
        desc: "접수 → 조리중 → 조리완료 → 서빙완료. 손님 화면과 주방 화면이 같은 상태를 보고 있어, “주문 들어갔어요?”를 묻지 않아도 됩니다." },
      { label: "서빙 완료",
        title: "결제는 계산대에서, 기록은 자동으로",
        desc: "현금 결제를 확인하면 매출·포인트·재고가 한 번에 정리됩니다. 주문 내역과 영수증 요청도 손님 화면에 그대로 남습니다." },
    ],
    owner: [
      { label: "주문 자동 접수",
        title: "홀을 뛰지 않아도 주문이 들어옵니다",
        desc: "새 주문은 사장님 화면과 주방 화면에 소리와 함께 표시됩니다. 테이블별 현황과 결제 전 금액이 한 화면에 모입니다." },
      { label: "주방 KDS",
        title: "알레르기는 크게, 같은 메뉴는 묶어서",
        desc: "주문서에 알레르기가 있으면 주방 카드에 경고가 뜹니다. 메뉴별 묶음 보기로 여러 테이블의 같은 메뉴를 한 번에 조리합니다." },
      { label: "매출 · 재고 자동 정리",
        title: "결제 확인 한 번에 매출과 재고가 맞춰집니다",
        desc: "레시피를 정해 두면 결제 확인 때 재료가 자동으로 빠지고, 안전재고 아래로 내려가면 품절 제안이 뜹니다." },
      { label: "단골 · 웨이팅 관리",
        title: "다시 오는 손님을 데이터로 챙깁니다",
        desc: "방문·결제 기준 등급과 포인트, 생일 목록, 쿠폰 발송 화면. 웨이팅은 번호표·호출·예상 대기까지 매장 앞 보드에 나옵니다." },
    ],
  };

  const tabs = $$(".flow-tab");
  const stage = $(".flow-stage");
  const titleEl = $("#flowTitle");
  const descEl = $("#flowDesc");
  const stepsBox = $("#flowSteps");
  const art = $(".flow-art");
  if (!tabs.length || !titleEl || !stepsBox || !art) return;

  let flow = "guest";
  let index = 0;
  let timer = null;
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function scenes(selector) { return $$(selector); }

  function paint() {
    const list = STEPS[flow];
    const step = list[index];
    titleEl.textContent = step.title;
    descEl.textContent = step.desc;
    tabs.forEach((t) => {
      const on = t.dataset.flow === flow;
      t.classList.toggle("on", on);
      t.setAttribute("aria-selected", on ? "true" : "false");
    });
    art.dataset.flow = flow;
    $$(".flow-art .dev").forEach((d) => d.classList.toggle("on", d.dataset.flow === flow));

    stepsBox.innerHTML = list.map((s, i) =>
      `<button class="flow-step ${i === index ? "on" : ""} ${i < index ? "done" : ""}" data-step="${i}" type="button">
        <span class="n">${i < index ? "✓" : i + 1}</span>
        <b>${s.label}</b>
        <span class="bar"><i></i></span>
      </button>`).join("");
    $$("#flowSteps .flow-step").forEach((b) =>
      b.addEventListener("click", () => { index = Number(b.dataset.step); paint(); restart(); }));

    scenes(`.flow-art .dev[data-flow="${flow}"] .scene`).forEach((el) =>
      el.classList.toggle("on", Number(el.dataset.scene) === index + 1));
    scenes(`.flow-art .dev[data-flow="${flow}"] .k-scene`).forEach((el) =>
      el.classList.toggle("on", Number(el.dataset.scene) === index + 1));
  }

  function stop() { if (timer) { clearInterval(timer); timer = null; } }
  function restart() {
    stop();
    if (reduce) return;
    timer = setInterval(() => { index = (index + 1) % STEPS[flow].length; paint(); }, 3800);
  }

  tabs.forEach((t) => t.addEventListener("click", () => {
    flow = t.dataset.flow === "owner" ? "owner" : "guest";
    index = 0;
    paint();
    restart();
  }));

  if (stage) {
    stage.addEventListener("pointerenter", stop);
    stage.addEventListener("pointerleave", restart);
    stage.addEventListener("focusin", stop);
  }
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") stop(); else restart();
  });

  paint();
  restart();
})();
