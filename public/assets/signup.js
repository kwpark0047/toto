// 사업자 계정 만들기 — ① 매장 이름·아이디·비밀번호 ② 테이블 수 ③ 끝
(() => {
  const S = { storeName: "맛집", username: "", password: "", email: "", tables: 8 };
  const params = new URLSearchParams(location.search);
  const oauthCode = params.get("oauth");

  const OAUTH_MESSAGES = {
    not_configured:
      "구글/카카오 로그인은 아직 앱 키(환경변수)가 연결되지 않았습니다. " +
      "아래 일반 회원가입을 이용하거나, Vercel 환경변수에 키를 등록해 주세요.",
    state: "로그인 요청이 만료되었거나 올바르지 않습니다. 다시 시도해 주세요.",
    denied: "로그인을 취소하셨습니다. 필요하시면 다시 시도해 주세요.",
    token: "구글/카카오 인증 처리에 실패했습니다. 잠시 뒤 다시 시도해 주세요.",
    profile: "소셜 계정의 프로필 정보를 받지 못했습니다. 다시 시도해 주세요.",
    unlinked: "이 소셜 계정은 아직 매장과 연결되어 있지 않습니다. 아이디로 로그인해 주세요.",
    server: "가입 처리 중 문제가 생겼습니다. 잠시 뒤 다시 시도해 주세요.",
  };

  function note(text, kind) {
    const box = $("#oauthNote");
    if (!box) return;
    const body = box.querySelector("span:last-child") || box;
    body.textContent = text;
    box.classList.remove("hidden");
    if (kind === "err") box.style.background = "var(--red-soft)";
  }

  function showOauthError() {
    const msg = OAUTH_MESSAGES[oauthCode];
    if (!msg) return;
    note(msg, oauthCode === "unlinked" ? "err" : "");
    const el = $("#msg");
    if (el) { el.textContent = msg; el.style.color = "var(--red)"; }
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
        state.textContent = pending.length
          ? "소셜 가입은 앱 키를 연결하면 바로 켜집니다 · 지금은 아래에서 만들어 주세요"
          : "";
      }
    } catch (e) {
      // 키 상태를 못 읽어도 직접 가입은 그대로 된다
    }
  }

  function bindToggle(btnSel, inputSel) {
    const btn = $(btnSel);
    if (!btn) return;
    btn.addEventListener("click", () => {
      const input = $(inputSel);
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      btn.textContent = show ? "🙈" : "👁";
      btn.setAttribute("aria-pressed", show ? "true" : "false");
      input.focus();
    });
  }
  bindToggle("#pwToggle", "#password");
  bindToggle("#pwToggle2", "#password2");

  const pwInput = $("#password");
  if (pwInput) {
    pwInput.addEventListener("input", () => {
      const bar = $("#strength");
      if (!bar) return;
      const v = pwInput.value || "";
      const score = v.length >= 10 && /[^A-Za-z0-9]/.test(v) ? 3 : v.length >= 8 ? 2 : v.length >= 4 ? 1 : 0;
      bar.className = "strength" + (score ? " s" + score : "");
    });
  }

  api("/api/auth/me").then((d) => {
    if (d.user) location.href = "/admin";
    else if (d.setup && d.setup.hasOwner) {
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
    S.email = ($("#email") && $("#email").value || "").trim();
    showStep(2);
  };

  async function finish(tables) {
    const btn = $("#finishBtn");
    btn.disabled = true;
    $("#msg2").textContent = "";
    try {
      await api("/api/auth/signup", {
        method: "POST",
        body: { storeName: S.storeName, username: S.username, password: S.password, tables,
                email: S.email },
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

  showOauthError();
  loadProviders();
})();
