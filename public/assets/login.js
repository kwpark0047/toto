// 사업자 로그인
(() => {
  const next = new URLSearchParams(location.search).get("next") || "/admin";

  async function init() {
    try {
      const data = await api("/api/auth/me");
      if (data.user) { location.href = next; return; }
      if (data.store && data.store.name) {
        $("#storeName").textContent = data.store.name;
        $("#logo").textContent = data.store.name.slice(0, 1);
      }
      if (!data.setup.hasOwner) {
        $("#signupLine").innerHTML = '아직 계정이 없습니다. <a href="/signup">사업자 계정 만들기</a>';
        $("#msg").textContent = "처음이시면 '사업자 계정 만들기'로 매장 이름과 아이디·비밀번호만 넣어 주세요.";
        $("#msg").style.color = "var(--brand)";
      }
    } catch (e) { /* 로그인 화면은 로그인 없이도 떠야 한다 */ }
    $("#username").focus();
  }

  $("#loginForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = $("#loginBtn");
    btn.disabled = true;
    $("#msg").textContent = "";
    try {
      await api("/api/auth/login", {
        method: "POST",
        body: { username: $("#username").value.trim(), password: $("#password").value },
      });
      location.href = next.startsWith("/login") ? "/admin" : next;
    } catch (err) {
      $("#msg").style.color = "var(--red)";
      $("#msg").textContent = err.message;
      btn.disabled = false;
      $("#password").select();
    }
  });

  init();
})();
