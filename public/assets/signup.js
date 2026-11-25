// 사업자 계정 만들기 — ① 매장 이름·아이디·비밀번호 ② 테이블 수 ③ 끝
(() => {
  const S = { storeName: "맛집", username: "", password: "", tables: 8 };

  api("/api/auth/me").then((d) => {
    if (d.user) location.href = "/admin";
    else if (d.setup && d.setup.hasOwner) {
      $("#msg").textContent = "이미 계정이 있습니다. 로그인해 주세요.";
      $("#msg").innerHTML = '이미 계정이 있습니다. <a href="/login">로그인</a>';
      $("#nextBtn").disabled = true;
    }
  }).catch(() => {});

  function showStep(n) {
    $("#step1").classList.toggle("on", n === 1);
    $("#step2").classList.toggle("on", n === 2);
    if (n === 2) $("#tables").focus();
  }

  $("#nextBtn").onclick = () => {
    const store = ($("#storeName").value || "").trim() || "맛집";
    const username = ($("#username").value || "").trim();
    const pw = $("#password").value || "";
    const pw2 = $("#password2").value || "";
    const err = $("#msg");
    err.textContent = "";
    if (!username) { err.textContent = "아이디를 넣어 주세요."; return; }
    if (!/^[A-Za-z0-9._-]+$/.test(username)) { err.textContent = "아이디는 영문·숫자로 넣어 주세요."; return; }
    if (pw.length < 4) { err.textContent = "비밀번호는 4자 이상으로 정해 주세요."; return; }
    if (pw !== pw2) { err.textContent = "비밀번호 확인이 맞지 않습니다."; return; }
    S.storeName = store; S.username = username; S.password = pw;
    showStep(2);
  };

  async function finish(tables) {
    const btn = $("#finishBtn");
    btn.disabled = true;
    $("#msg2").textContent = "";
    try {
      await api("/api/auth/signup", {
        method: "POST",
        body: { storeName: S.storeName, username: S.username, password: S.password, tables },
      });
      location.href = "/admin";
    } catch (e) {
      $("#msg2").textContent = e.message;
      btn.disabled = false;
    }
  }

  $("#finishBtn").onclick = () => {
    const n = Number($("#tables").value || 8);
    if (!(n >= 1 && n <= 50)) { $("#msg2").textContent = "테이블 수는 1~50 사이로 넣어 주세요."; return; }
    finish(n);
  };
  $("#skipBtn").onclick = (e) => { e.preventDefault(); finish(8); };
})();
