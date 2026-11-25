// 내 계정: 내 정보·비밀번호 변경·로그인한 기기
(() => {
  renderNav("account");

  async function load() {
    const data = await api("/api/auth/me");
    const u = data.user;
    if (!u) return;
    const perms = (data.permissionCatalog || []).filter((p) => (u.permissions || []).includes(p.code));
    $("#who").innerHTML = `
      <div><b style="font-size:16.5px">${esc(u.name)}</b> <span class="badge line">${esc(u.roleLabel)}</span>
        ${u.mustChange ? '<span class="badge red">비밀번호 변경 필요</span>' : ""}</div>
      <div style="margin-top:6px">아이디 <b>${esc(u.username)}</b> · 매장 <b>${esc(data.store.name)}</b></div>
      <div style="margin-top:6px">내 권한: ${perms.length ? perms.map((p) => `<span class="badge">${esc(p.label)}</span>`).join(" ") : "없음"}</div>`;
    const sessions = await api("/api/account/sessions");
    $("#sessions").innerHTML = sessions.sessions.map((s) => `<div class="srow">
        <span>${esc(s.device)}${s.current ? ' <span class="badge green">지금 기기</span>' : ""}</span>
        <span class="muted small">마지막 사용 ${esc(s.lastSeen || "")}</span></div>`).join("");
  }

  $("#pwSave").onclick = async () => {
    const btn = $("#pwSave");
    btn.disabled = true;
    try {
      await api("/api/account/password", {
        method: "POST",
        body: { current: $("#curPw").value, new: $("#newPw").value },
      });
      toast("비밀번호를 바꿨습니다", "ok");
      $("#curPw").value = ""; $("#newPw").value = "";
      await load();
    } catch (e) {
      toast(e.message, "err");
    } finally {
      btn.disabled = false;
    }
  };

  load().catch((e) => toast(e.message, "err"));
})();
