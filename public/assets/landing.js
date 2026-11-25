// w-toto 메인 v2 — 실시간 매장 연결 보드 + 이중 시선 라이브 스위치
(() => {
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const two = (n) => String(n).padStart(2, "0");
  const clock = () => {
    const d = new Date();
    return `${two(d.getHours())}:${two(d.getMinutes())}`;
  };
  const stamp = () => {
    const d = new Date();
    return `${two(d.getHours())}:${two(d.getMinutes())}:${two(d.getSeconds())}`;
  };

  /* ============================================================ 1. 연결 보드 */
  const SEQ = [
    { state: "sent", label: "주문 전송", rail: 0, sec: 0,
      feed: "테이블 03 · 떡볶이 2 · 김밥 1 · 주문 전송" },
    { state: "cooking", label: "주방 접수", rail: 1, sec: 12,
      feed: "주방 접수 #A-104 · 예상 6분" },
    { state: "cooking", label: "조리 중", rail: 2, sec: 220,
      feed: "조리 시작 · 알레르기(난류) 확인" },
    { state: "done", label: "서빙 완료", rail: 3, sec: 372,
      feed: "서빙 완료 · 테이블 03 · 12,500원" },
    { state: "paid", label: "결제 확인", rail: 4, sec: 388,
      feed: "결제 확인 12,500원 · 다점포 매출 반영", paid: true },
  ];
  const BASE_REVENUE = 412000;
  const ORDER_TOTAL = 12500;
  const BASE_STORE = 182000;

  const board = { step: 0, running: !reduce, sec: 0 };
  const el = {
    clock: $("#boardClock"),
    state: $("#boardOrderState"),
    rail: $("#boardRail"),
    timer: $("#boardTimer"),
    revenue: $("#boardRevenue"),
    delta: $("#boardDelta"),
    stores: $("#boardStores"),
    spark: $("#boardSpark"),
    feed: $("#boardFeed"),
    play: $("#boardPlay"),
  };

  function money(n) { return Number(n).toLocaleString("ko-KR"); }

  function paintBoard(fresh) {
    const s = SEQ[board.step];
    board.sec = s.sec;

    if (el.state) {
      el.state.textContent = s.label;
      el.state.dataset.state = s.state;
    }
    $$("#boardRail li").forEach((li) => {
      const n = Number(li.dataset.step);
      li.classList.toggle("on", n === s.rail);
      li.classList.toggle("done", n < s.rail);
    });
    if (el.timer) el.timer.textContent = `${two(Math.floor(board.sec / 60))}:${two(board.sec % 60)}`;
    if (el.revenue) el.revenue.textContent = money(BASE_REVENUE + (s.paid ? ORDER_TOTAL : 0));
    if (el.delta) el.delta.textContent = s.paid ? `+${money(ORDER_TOTAL)} 반영` : "3개 매장 동기화 중";
    if (el.stores) {
      const first = el.stores.querySelector("li");
      const hot = el.stores.querySelector("li.hot") || first;
      if (hot) {
        const base = hot.querySelector("b");
        if (base) base.textContent = money(BASE_STORE + (s.paid ? ORDER_TOTAL : 0));
      }
    }
    if (el.spark) {
      const bars = $$("#boardSpark i");
      bars.forEach((b, i) => {
        if (i === bars.length - 1) b.style.height = s.paid ? "100%" : "92%";
      });
    }
    if (el.feed && fresh) {
      el.feed.innerHTML = `<span>${stamp()}</span>${esc(s.feed)}`;
      el.feed.classList.add("fade");
      window.setTimeout(() => el.feed.classList.remove("fade"), 180);
    }
  }

  let boardTimer = null;
  function boardNext() {
    board.step = (board.step + 1) % SEQ.length;
    paintBoard(true);
  }
  function boardStart() {
    if (boardTimer || reduce) return;
    boardTimer = window.setInterval(boardNext, 2800);
  }
  function boardStop() {
    if (boardTimer) { window.clearInterval(boardTimer); boardTimer = null; }
  }
  function boardSetRunning(on) {
    board.running = on;
    if (el.play) {
      el.play.textContent = on ? "⏸ 일시정지" : "▶ 재생";
      el.play.setAttribute("aria-pressed", on ? "true" : "false");
    }
    if (on) boardStart(); else boardStop();
  }

  if (el.play) {
    el.play.addEventListener("click", () => boardSetRunning(!board.running));
  }
  if (el.clock) {
    el.clock.textContent = clock();
    window.setInterval(() => {
      if (el.clock) el.clock.textContent = clock();
    }, 30000);
  }
  if (!reduce) {
    // 화면 밖으로 나가면 멈춘다
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") boardStop();
      else if (board.running) boardStart();
    });
  }
  paintBoard(false);
  boardStart();

  /* ============================================================ 2. 이중 시선 */
  const STEPS = {
    guest: [
      { label: "QR · NFC 접촉",
        title: "테이블에 앉아 QR만 찍으면 메뉴가 열립니다",
        desc: "앱 설치도, 회원가입도 없습니다. 테이블의 QR·NFC를 대면 그 테이블의 메뉴판이 바로 열리고, 사진·원산지·알레르기까지 한 화면에서 확인합니다." },
      { label: "메뉴 선택 · 음성 주문",
        title: "말로 담아도, 손으로 담아도 같은 주문",
        desc: "큰 글씨와 고대비 화면, 한국어·영어·중국어·일본어 전환. “떡볶이 두 개 매운맛으로”라고 말해도 장바구니에 담깁니다." },
      { label: "4단계 실시간 현황",
        title: "기다리는 동안 진행 상황이 보입니다",
        desc: "접수 → 조리중 → 조리완료 → 서빙완료. 손님 화면과 주방 화면이 같은 상태를 보고 있어, “주문 들어갔어요?”를 묻지 않아도 됩니다." },
      { label: "서빙 · 결제 확인",
        title: "결제는 계산대에서, 기록은 자동으로",
        desc: "서빙이 끝나면 손님 화면에 영수증과 적립 예정 포인트가 남습니다. 현금 결제를 확인하면 매출·재고·포인트가 한 번에 정리됩니다." },
    ],
    owner: [
      { label: "주문 자동 접수",
        title: "홀을 뛰지 않아도 주문이 들어옵니다",
        desc: "새 주문은 사장님 화면과 주방 화면에 동시에 뜹니다. 테이블별 현황과 결제 전 금액이 한 화면에 모입니다." },
      { label: "주방 KDS",
        title: "알레르기는 크게, 같은 메뉴는 묶어서",
        desc: "주문서에 알레르기가 있으면 주방 카드에 경고가 뜹니다. 메뉴별 묶음 보기로 여러 테이블의 같은 메뉴를 한 번에 조리합니다." },
      { label: "매출 · 재고 자동 정리",
        title: "결제 확인 한 번에 매출과 재고가 맞춰집니다",
        desc: "레시피를 정해 두면 결제 확인 때 재료가 자동으로 빠지고, 안전재고 아래로 내려가면 품절 제안이 뜹니다. 여러 매장은 합산해서 봅니다." },
      { label: "단골 · 재방문",
        title: "다시 오는 손님을 데이터로 챙깁니다",
        desc: "방문·결제 기준 등급과 포인트, 생일 목록, 30일 미방문 목록. 쿠폰은 동의한 손님에게만, 보낸 성공 건에만 청구됩니다." },
    ],
  };

  const tabs = $$("#duoSwitch .flow-tab");
  const nodes = $$("#duoTimeline .tl-node");
  const stage = $(".flow-stage");
  const art = $(".flow-art");
  const kicker = $("#flowKicker");
  const titleEl = $("#flowTitle");
  const descEl = $("#flowDesc");
  const stepsBox = $("#flowSteps");
  if (!tabs.length || !titleEl || !stepsBox || !art) return;

  let flow = "guest";
  let index = 0;
  let timer = null;

  function paint() {
    const list = STEPS[flow];
    const step = list[index] || list[0];
    if (kicker) kicker.textContent = flow === "owner" ? "사장님 흐름" : "이용고객 흐름";
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

    nodes.forEach((n) => {
      const pos = Number(n.dataset.step);
      n.classList.toggle("on", pos === index);
      n.classList.toggle("done", pos < index);
      if (pos === index) n.setAttribute("aria-current", "step");
      else n.removeAttribute("aria-current");
    });

    $$(`.flow-art .dev[data-flow="${flow}"] .scene`).forEach((el2) => {
      el2.classList.toggle("on", Number(el2.dataset.scene) === index + 1);
    });
  }

  function stop() { if (timer) { window.clearInterval(timer); timer = null; } }
  function restart() {
    stop();
    if (reduce) return;
    timer = window.setInterval(() => {
      index = (index + 1) % STEPS[flow].length;
      paint();
    }, 4400);
  }

  tabs.forEach((t) => t.addEventListener("click", () => {
    flow = t.dataset.flow === "owner" ? "owner" : "guest";
    index = 0;
    paint();
    restart();
  }));

  nodes.forEach((n) => n.addEventListener("click", () => {
    index = Number(n.dataset.step) || 0;
    paint();
    restart();
  }));

  if (stage) {
    stage.addEventListener("pointerenter", stop);
    stage.addEventListener("pointerleave", restart);
    stage.addEventListener("focusin", stop);
    stage.addEventListener("focusout", restart);
  }
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") stop(); else restart();
  });

  paint();
  restart();
})();
