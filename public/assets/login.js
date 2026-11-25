// 사장님 로그인 — 아이디 로그인 + 구글/카카오 소셜 로그인
(() => {
  const params = new URLSearchParams(location.search);
  const next = params.get("next") || "/admin";
  const oauthCode = params.get("oauth");

  const OAUTH_MESSAGES = {
    not_configured:
      "구글/카카오 로그인은 아직 앱 키(환경변수)가 연결되지 않았습니다. " +
      "아래 일반 로그인·회원가입을 이용하거나, Vercel 환경변수에 키를 등록해 주세요.",
    state: "로그인 요청이 만료되었거나 올바르지 않습니다. 다시 시도해 주세요.",
    denied: "로그인을 취소하셨습니다. 필요하시면 다시 시도해 주세요.",
    token: "구글/카카오 인증 처리에 실패했습니다. 잠시 뒤 다시 시도해 주세요.",
    profile: "소셜 계정의 프로필 정보를 받지 못했습니다. 다시 시도해 주세요.",
    unlinked:
      "이 소셜 계정은 아직 매장과 연결되어 있지 않습니다. " +
      "아이디·비밀번호로 로그인해 주세요.",
    server: "로그인 처리 중 문제가 생겼습니다. 잠시 뒤 다시 시도해 주세요.",
  };

  function note(text, kind) {
    const box = $("#oauthNote");
    if (!box) return;
    const body = box.querySelector("span:last-child") || box;
    body.textContent = text;
    box.classList.remove("hidden");
    box.style.background = kind === "err" ? "var(--red-soft)" : "";
  }

  function showOauthError() {
    const msg = OAUTH_MESSAGES[oauthCode];
    if (!msg) return;
    note(msg);
    const el = $("#msg");
    if (el) { el.textContent = msg; el.style.color = "var(--red)"; }
  }

  // 비밀번호 보기/숨기기
  const toggle = $("#pwToggle");
  if (toggle) {
    toggle.addEventListener("click", () => {
      const input = $("#password");
      if (!input) return;
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      toggle.textContent = show ? "🙈" : "👁";
      toggle.setAttribute("aria-pressed", show ? "true" : "false");
      toggle.setAttribute("aria-label", show ? "비밀번호 숨기기" : "비밀번호 보기");
      input.focus();
    });
  }

  function bindProvider(sel, info) {
    const el = $(sel);
    if (!el || !info) return;
    if (!info.configured) {
      el.classList.add("pending");
      el.setAttribute("title", "앱 키(환경변수)를 연결하면 바로 사용할 수 있습니다");
      el.addEventListener("click", (ev) => {
        ev.preventDefault();
        note(OAUTH_MESSAGES.not_configured);
        el.blur();
      });
    } else {
      el.classList.add("ready");
    }
  }

  async function loadProviders() {
    try {
      const data = await api("/api/auth/oauth/providers");
      const p = (data && data.providers) || {};
      bindProvider("#googleBtn", p.google);
      bindProvider("#kakaoBtn", p.kakao);
      const state = $("#oauthState");
      if (state) {
        const pending = ["google", "kakao"].filter((k) => p[k] && !p[k].configured);
        if (pending.length === 2) {
          state.textContent = "소셜 로그인은 앱 키를 연결하면 바로 켜집니다 · 지금은 아이디 로그인을 이용해 주세요";
        } else if (pending.length) {
          state.textContent = "일부 소셜 로그인은 앱 키 연결 후 사용할 수 있습니다";
        }
      }
    } catch (e) {
      // 키 상태를 못 읽어도 아이디 로그인은 그대로 쓸 수 있다
    }
  }

  async function init() {
    try {
      const data = await api("/api/auth/me");
      if (data.user) { location.href = next; return; }
      if (data.store && data.store.name) {
        $("#storeName").textContent = data.store.name;
        $("#logo").textContent = data.store.name.slice(0, 1);
        document.title = `${data.store.name} · 사장님 로그인`;
      }
      if (data.setup && !data.setup.hasOwner) {
        $("#signupLine").innerHTML = '<span>아직 계정이 없습니다.</span><a href="/signup">사업자 계정 만들기</a>';
        const msg = $("#msg");
        msg.textContent = "처음이시면 '사업자 계정 만들기'로 매장 이름과 아이디·비밀번호만 넣어 주세요.";
        msg.style.color = "var(--brand)";
      }
    } catch (e) { /* 로그인 화면은 로그인 없이도 떠야 한다 */ }
    showOauthError();
    loadProviders();
    if (!oauthCode && $("#username")) $("#username").focus();
  }

  $("#loginForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = $("#loginBtn");
    const msg = $("#msg");
    btn.disabled = true;
    msg.textContent = "";
    msg.style.color = "var(--red)";
    try {
      await api("/api/auth/login", {
        method: "POST",
        body: { username: $("#username").value.trim(), password: $("#password").value },
      });
      location.href = next.startsWith("/login") ? "/admin" : next;
    } catch (err) {
      msg.textContent = err.message;
      btn.disabled = false;
      $("#password").select();
    }
  });

  init();
})();
