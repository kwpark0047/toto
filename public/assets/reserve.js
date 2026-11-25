// 손님 예약 신청(확정은 사장님이 직접). ?store=<매장id>, ?t=<토큰> 으로 상태 확인.
(() => {
  const params = new URLSearchParams(location.search);
  const storeId = Number(params.get("store") || 0);
  const token = params.get("t") || "";

  async function loadStore() {
    const q = storeId ? `?store=${storeId}` : "";
    const data = await api("/api/store" + q);
    const s = data.store || {};
    $("#shopName").textContent = s.name || "맛집";
    $("#shopInitial").textContent = (s.name || "맛").slice(0, 1);
    $("#shopLine").textContent = [s.hours, "예약 신청 · 사장님 확인 후 확정"].filter(Boolean).join(" · ");
    document.title = `${s.name || "맛집"} · 예약 신청`;
  }

  const today = new Date();
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  $("#rDate").value = iso(today);
  $("#rDate").min = iso(today);

  const STATUS_TEXT = { PENDING: "신청 접수", CONFIRMED: "확정", ARRIVED: "도착", NOSHOW: "노쇼", CANCELED: "취소" };

  async function showToken() {
    try {
      const data = await api(`/api/reservations/t/${encodeURIComponent(token)}`);
      const r = data.reservation;
      $("#formCard").classList.add("hidden");
      $("#resultCard").classList.remove("hidden");
      $("#resultTitle").textContent = `예약 ${STATUS_TEXT[r.status] || r.statusLabel}`;
      $("#resultBody").innerHTML = `
        <div><b>${esc(r.date)} ${esc(r.time)}</b> · ${r.partySize}명</div>
        <div>${esc(r.name)} · ${esc(r.phone)}</div>
        ${r.memo ? `<div class="muted">요청: ${esc(r.memo)}</div>` : ""}
        <div style="margin-top:8px" class="badge ${r.status === "CONFIRMED" ? "green" : "amber"}">${esc(r.statusLabel)}</div>
        <div class="muted" style="margin-top:8px">${r.status === "CONFIRMED" ? "예약이 확정되었습니다. 시간에 맞춰 와 주세요." : r.status === "PENDING" ? "사장님이 확인하면 확정됩니다." : "매장에 문의해 주세요."}</div>`;
    } catch (e) {
      $("#resultBody").textContent = e.message;
    }
  }

  $("#rSend").onclick = async () => {
    const btn = $("#rSend");
    const body = {
      date: $("#rDate").value, time: $("#rTime").value, party: Number($("#rParty").value || 2),
      name: $("#rName").value, phone: $("#rPhone").value, memo: $("#rMemo").value,
      consent: $("#rConsent").checked,
    };
    if (!body.consent) { toast("연락처 수집·이용 동의가 필요합니다", "err"); return; }
    btn.disabled = true;
    try {
      const q = storeId ? `?store=${storeId}` : "";
      const r = await api("/api/reservations/public" + q, { method: "POST", body });
      $("#formCard").classList.add("hidden");
      $("#resultCard").classList.remove("hidden");
      $("#resultTitle").textContent = "신청이 접수됐습니다";
      $("#resultBody").innerHTML = `
        <div><b>${esc(r.date)} ${esc(r.time)}</b> · ${r.partySize}명</div>
        <div>${esc(r.name)} · ${esc(r.phone)}</div>
        <div style="margin-top:8px"><span class="badge amber">신청 접수</span> 사장님이 확인하면 <b>확정</b>됩니다.</div>
        <div class="muted" style="margin-top:8px">확정 여부는 매장(<b>${esc((await api("/api/store" + q)).store.phone || "전화")}</b>)에 문의해 주세요.<br>
          이 화면 주소를 저장해 두면 상태를 다시 볼 수 있습니다.</div>`;
      history.replaceState(null, "", `/reserve?t=${encodeURIComponent(r.token)}${storeId ? `&store=${storeId}` : ""}`);
    } catch (e) {
      toast(e.message, "err");
      btn.disabled = false;
    }
  };

  $("#againBtn").onclick = () => {
    history.replaceState(null, "", "/reserve");
    $("#resultCard").classList.add("hidden");
    $("#formCard").classList.remove("hidden");
    $("#rSend").disabled = false;
  };

  loadStore().catch(() => {});
  if (token) showToken();
})();
