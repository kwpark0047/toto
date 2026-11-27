// 공통 유틸 — 모든 화면이 함께 쓴다.
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const won = (n) => Number(n || 0).toLocaleString("ko-KR") + "원";
const points = (n) => Number(n || 0).toLocaleString("ko-KR") + "P";
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
));

// 로그인이 풀리면 로그인 화면으로 보낸다(주소는 기억해 두고 돌아온다).
function goLogin() {
  const here = location.pathname + location.search;
  location.href = "/login?next=" + encodeURIComponent(here);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    method: opts.method || "GET",
    headers: opts.body ? { "Content-Type": "application/json" } : {},
    body: opts.body ? JSON.stringify(opts.body) : undefined,
    credentials: "same-origin",
    signal: opts.signal,
  });
  if (res.status === 401 && !String(path).startsWith("/api/auth/")) {
    goLogin();
    throw new Error("로그인이 필요합니다");
  }
  const type = res.headers.get("Content-Type") || "";
  const data = type.includes("json") ? await res.json() : await res.text();
  if (!res.ok) throw new Error((data && data.error) || "요청을 처리하지 못했습니다");
  return data;
}

let toastBox;
function toast(msg, kind = "") {
  if (!toastBox) {
    toastBox = document.createElement("div");
    toastBox.id = "toasts";
    document.body.appendChild(toastBox);
  }
  const el = document.createElement("div");
  el.className = "toast " + kind;
  el.textContent = msg;
  toastBox.appendChild(el);
  requestAnimationFrame(() => el.classList.add("on"));
  setTimeout(() => {
    el.classList.remove("on");
    setTimeout(() => el.remove(), 250);
  }, kind === "err" ? 3600 : 2200);
}

// 알림음 (외부 파일 없이 브라우저에서 생성)
let audioCtx;
function beep(times = 1, freq = 880) {
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === "suspended") audioCtx.resume();
    for (let i = 0; i < times; i++) {
      const t = audioCtx.currentTime + i * 0.28;
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(freq, t);
      osc.frequency.setValueAtTime(freq * 1.5, t + 0.09);
      gain.gain.setValueAtTime(0.0001, t);
      gain.gain.exponentialRampToValueAtTime(0.28, t + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.24);
      osc.connect(gain).connect(audioCtx.destination);
      osc.start(t);
      osc.stop(t + 0.26);
    }
  } catch (e) { /* 소리 재생이 막힌 브라우저는 조용히 넘어간다 */ }
}

// 폴링: 화면이 보일 때만 돈다
function pollEvery(fn, ms) {
  let timer = null;
  const tick = async () => {
    if (document.visibilityState === "visible") {
      try { await fn(); } catch (e) { console.warn(e); }
    }
    timer = setTimeout(tick, ms);
  };
  tick();
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") fn().catch(() => {});
  });
  return () => clearTimeout(timer);
}

const pad2 = (n) => String(n).padStart(2, "0");
function parseTs(s) {
  if (!s) return null;
  const d = new Date(s.replace(" ", "T"));
  return isNaN(d) ? null : d;
}
function hhmm(s) {
  const d = parseTs(s);
  return d ? `${pad2(d.getHours())}:${pad2(d.getMinutes())}` : "";
}
function ago(s) {
  const d = parseTs(s);
  if (!d) return "";
  const m = Math.max(0, Math.floor((Date.now() - d.getTime()) / 60000));
  if (m < 1) return "방금";
  if (m < 60) return `${m}분 전`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}시간 전`;
  return `${Math.floor(h / 24)}일 전`;
}
function mmss(sec) {
  const m = Math.floor(sec / 60), s = sec % 60;
  return `${pad2(m)}:${pad2(s)}`;
}
// 125 → "2시간 5분"
function minutesText(min) {
  min = Math.max(0, Number(min) || 0);
  if (min < 60) return `${min}분`;
  return `${Math.floor(min / 60)}시간 ${min % 60}분`;
}

// 간단한 확인 시트가 필요할 때
function confirmDialog(text) {
  return window.confirm(text);
}
