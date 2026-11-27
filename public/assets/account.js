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

    // 이메일 · 최고관리자 안내
    const hint = data.superAdminHint || {};
    if ($("#emailInput")) $("#emailInput").value = u.email || "";
    if ($("#emailSave")) $("#emailSave").disabled = u.role !== "admin";
    let note = "";
    if (u.isSuperAdmin) {
      note = `<span class="badge brand">최고관리자</span> 플랫폼 전체 현황을 볼 수 있습니다.`;
    } else if (hint.eligible) {
      note = `이 배포의 최고관리자 이메일 <b>${esc(hint.email)}</b>을 등록하면 최고관리자 메뉴가 열립니다.`;
    } else if (u.email && hint.email && u.email === hint.email) {
      note = "이메일은 등록되어 있지만 최고관리자 자격이 없습니다. 관리자에게 문의해 주세요.";
    } else if (u.role !== "admin") {
      note = "이메일은 사업자(관리자) 계정에서만 등록할 수 있습니다.";
    } else {
      note = "알림·영수증에 쓸 이메일을 등록해 두면 좋습니다. 최고관리자 이메일은 자격이 있는 계정만 등록됩니다.";
    }
    if ($("#emailHint")) $("#emailHint").innerHTML = note;
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

  $("#emailSave").onclick = async () => {
    const btn = $("#emailSave");
    btn.disabled = true;
    try {
      const r = await api("/api/account", {
        method: "PATCH",
        body: { email: ($("#emailInput").value || "").trim() },
      });
      toast(r.isSuperAdmin ? "이메일을 저장했습니다. 최고관리자 메뉴가 열렸습니다" : "이메일을 저장했습니다", "ok");
      await renderNavRefresh();
      await load();
    } catch (e) {
      toast(e.message, "err");
    } finally {
      btn.disabled = false;
    }
  };

  load().catch((e) => toast(e.message, "err"));
})();
