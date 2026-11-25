// 요금제 — 문자 발송량 시뮬레이터 (사업계획 초안의 구간 단가)
(() => {
  const SMS_TIERS = [
    { min: 1, max: 1000, rate: 20 },
    { min: 1001, max: 5000, rate: 17 },
    { min: 5001, max: 20000, rate: 15 },
    { min: 20001, max: Infinity, rate: 13 },
  ];
  const FLAT = { lms: 60, mms: 120 };

  const count = $("#msgCount");
  const kind = $("#charType");
  if (!count) return;

  function rateFor(n, type) {
    if (type === "lms") return FLAT.lms;
    if (type === "mms") return FLAT.mms;
    const tier = SMS_TIERS.find((t) => n >= t.min && n <= t.max) || SMS_TIERS[0];
    return tier.rate;
  }

  function paint() {
    const n = Math.max(0, Number(count.value) || 1000);
    const type = (kind && kind.value) || "sms";
    const rate = rateFor(n, type);
    const total = n * rate;
    const vat = Math.round(total * 1.1);
    const set = (sel, text) => { const el = $(sel); if (el) el.textContent = text; };
    set("#msgCountLabel", n.toLocaleString("ko-KR"));
    set("#simTotal", total.toLocaleString("ko-KR"));
    set("#simRate", `${rate.toLocaleString("ko-KR")}원`);
    set("#simCount", `${n.toLocaleString("ko-KR")}건`);
    set("#simVat", `${vat.toLocaleString("ko-KR")}원`);
  }

  if (count) count.addEventListener("input", paint);
  if (kind) kind.addEventListener("change", paint);
  paint();
})();
