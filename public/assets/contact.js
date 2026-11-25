// 문의하기 — 접수번호 발급까지
(() => {
  const form = $("#inquiryForm");
  if (!form) return;

  function fail(text) {
    const msg = $("#qMsg");
    msg.textContent = text;
    msg.style.color = "var(--red)";
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = $("#qSend");
    const msg = $("#qMsg");
    msg.textContent = "";
    const body = {
      kind: $("#qKind").value,
      storeName: $("#qStore").value.trim(),
      name: $("#qName").value.trim(),
      phone: $("#qPhone").value.trim(),
      email: $("#qEmail").value.trim(),
      message: $("#qMessage").value.trim(),
      consent: $("#qConsent").checked,
    };
    if (!body.name) { fail("이름을 넣어 주세요."); return; }
    if (!body.phone && !body.email) { fail("전화번호 또는 이메일 중 하나를 넣어 주세요."); return; }
    if (body.message.length < 5) { fail("문의 내용을 5자 이상 넣어 주세요."); return; }
    if (!body.consent) { fail("개인정보 수집·이용에 동의해 주세요."); return; }

    btn.disabled = true;
    btn.textContent = "접수 중…";
    try {
      const data = await api("/api/public/inquiries", { method: "POST", body });
      $("#doneNo").textContent = data.receiptNo;
      $("#formPane").classList.add("hidden");
      $("#doneCard").classList.remove("hidden");
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err) {
      fail(err.message);
      btn.disabled = false;
      btn.textContent = "문의 접수하기";
    }
  });

  const again = $("#againBtn");
  if (again) {
    again.addEventListener("click", () => {
      form.reset();
      $("#qMsg").textContent = "";
      $("#doneCard").classList.add("hidden");
      $("#formPane").classList.remove("hidden");
      $("#qName").focus();
    });
  }
})();
