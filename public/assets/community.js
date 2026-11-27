// 로컬 커뮤니티 — 동네 소식·단골 공지·동네 이벤트·공동 프로모션
(() => {
  renderNav("community");
  const S = { data: null, posts: [], kinds: [], editing: null };

  async function load() {
    S.data = await api("/api/community");
    S.posts = S.data.posts || [];
    S.kinds = S.data.kinds || [];
    render();
  }

  function render() {
    const c = S.data.config || {};
    $("comState").textContent = c.enabled
      ? `커뮤니티 켜짐 · 손님에게 ${c.showToCustomers ? "보임" : "숨김"}`
      : "커뮤니티 꺼짐";
    $("comState").className = `badge ${c.enabled ? "green" : "red"}`;
    $("comCount").textContent = `글 ${S.posts.length}`;
    $("comIntro").textContent = [c.neighborhood, c.intro].filter(Boolean).join(" · ");
    $("postKind").innerHTML = S.kinds.map((k) =>
      `<option value="${k.code}">${esc(k.label)}</option>`).join("");

    if (!S.posts.length) {
      $("postList").innerHTML = `<div class="empty"><div class="ico">🏘</div>아직 글이 없습니다<br>
        <span class="small">동네 소식이나 단골 공지를 하나 올려 보세요.</span></div>`;
      return;
    }
    $("postList").innerHTML = S.posts.map((p) => `<div class="row between wrap" style="padding:12px 16px;border-bottom:1px solid var(--line);gap:8px">
      <div style="min-width:0">
        <div><span class="badge ${p.kind === "promo" ? "amber" : p.kind === "notice" ? "brand" : ""}">${esc(p.kindLabel)}</span>
          ${p.pinned ? '<span class="badge">고정</span>' : ""}
          ${p.visible ? "" : '<span class="badge red">숨김</span>'}
          <b>${esc(p.title)}</b></div>
        <div class="small muted" style="margin-top:2px">${esc((p.body || "").slice(0, 80))}${(p.body || "").length > 80 ? "…" : ""}</div>
        <div class="small muted">${esc(p.storeName || "")}${p.groupId ? " · 그룹 공동" : ""} · ${esc((p.createdAt || "").slice(0, 16))}</div>
      </div>
      <div class="row" style="gap:6px">
        <button class="btn sm ghost" data-vis="${p.id}">${p.visible ? "숨기기" : "보이기"}</button>
        <button class="btn sm" data-edit="${p.id}">수정</button>
      </div></div>`).join("");
    $$("#postList [data-edit]").forEach((b) => b.onclick = () => openPost(Number(b.dataset.edit)));
    $$("#postList [data-vis]").forEach((b) => b.onclick = async () => {
      const p = S.posts.find((x) => x.id === Number(b.dataset.vis));
      try {
        await api(`/api/community/${p.id}`, { method: "PATCH", body: { visible: !p.visible } });
        toast(p.visible ? "손님 화면에서 숨겼습니다" : "손님 화면에 보이게 했습니다", "ok");
        await load();
      } catch (e) { toast(e.message, "err"); }
    });
  }

  function openPost(id) {
    S.editing = id ? S.posts.find((p) => p.id === id) : null;
    const p = S.editing;
    $("postTitle").textContent = p ? "글 수정" : "글쓰기";
    $("postKind").value = p ? p.kind : (S.kinds[0] ? S.kinds[0].code : "neighbor");
    $("postScope").value = p && p.groupId ? "group" : "store";
    $("postScope").disabled = !!p;
    $("postHead").value = p ? p.title : "";
    $("postBody").value = p ? p.body : "";
    $("postPinned").checked = p ? p.pinned : false;
    $("postDelete").classList.toggle("hidden", !p);
    $("back").classList.add("on");
    $("postSheet").classList.add("on");
  }

  function closeSheet() {
    $("back").classList.remove("on");
    $("postSheet").classList.remove("on");
  }
  $("back").onclick = closeSheet;
  $$("[data-close]").forEach((b) => b.onclick = closeSheet);
  $("newBtn").onclick = () => openPost(null);

  $("postSave").onclick = async () => {
    const body = { kind: $("postKind").value, title: $("postHead").value.trim(),
                   body: $("postBody").value.trim(), pinned: $("postPinned").checked };
    try {
      if (S.editing) {
        await api(`/api/community/${S.editing.id}`, { method: "PATCH", body });
        toast("글을 저장했습니다", "ok");
      } else {
        body.scope = $("postScope").value;
        await api("/api/community", { method: "POST", body });
        toast("글을 올렸습니다", "ok");
      }
      closeSheet();
      await load();
    } catch (e) { toast(e.message, "err"); }
  };

  $("postDelete").onclick = async () => {
    if (!S.editing) return;
    if (!confirm("이 글을 삭제할까요? 되돌릴 수 없습니다.")) return;
    try {
      await api(`/api/community/${S.editing.id}`, { method: "DELETE" });
      toast("글을 삭제했습니다", "ok");
      closeSheet();
      await load();
    } catch (e) { toast(e.message, "err"); }
  };

  load().catch((e) => toast(e.message, "err"));
})();
