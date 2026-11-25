// 게시판 — 목록·상세·댓글·글쓰기 (공개)
(() => {
  const S = { category: "", posts: [], current: null, categories: [] };

  const CATS = [
    { code: "", label: "전체" },
    { code: "notice", label: "공지" },
    { code: "update", label: "업데이트" },
    { code: "review", label: "매장 후기" },
  ];

  function when(ts) {
    return String(ts || "").slice(0, 16).replace("T", " ");
  }

  function chip(code, label) {
    return `<button class="chip ${S.category === code ? "on" : ""}" data-cat="${code}" type="button">${label}</button>`;
  }

  function renderChips() {
    const box = $("#catChips");
    if (!box) return;
    const cats = S.categories.length ? [{ code: "", label: "전체" }]
      .concat(S.categories.map((c) => ({ code: c.code, label: c.label }))) : CATS;
    box.innerHTML = cats.map((c) => chip(c.code, c.label)).join("");
    $$("#catChips .chip").forEach((b) => b.addEventListener("click", () => {
      S.category = b.dataset.cat || "";
      renderChips();
      load();
    }));
  }

  function renderList() {
    const box = $("#postList");
    const count = $("#postCount");
    if (!box) return;
    if (count) count.textContent = `${S.posts.length}건`;
    if (!S.posts.length) {
      box.innerHTML = `<div class="post" style="grid-template-columns:1fr;text-align:center">
        <div><h3>아직 글이 없습니다</h3><p class="meta" style="justify-content:center">첫 글을 남겨 보세요.</p></div></div>`;
      return;
    }
    box.innerHTML = S.posts.map((p) => `<button class="post" data-post="${p.id}" type="button">
      <span class="cat ${esc(p.category)}">${esc(p.categoryLabel)}</span>
      <span>
        <h3>${esc(p.title)}</h3>
        <span class="meta"><span>${esc(p.author)}</span><span>${esc(when(p.createdAt))}</span></span>
      </span>
      <span class="count">💬 ${p.commentCount || 0}</span>
    </button>`).join("");
    $$("#postList .post[data-post]").forEach((b) =>
      b.addEventListener("click", () => openPost(b.dataset.post)));
  }

  async function load() {
    try {
      const q = S.category ? `?category=${encodeURIComponent(S.category)}` : "";
      const data = await api("/api/public/board" + q);
      S.posts = data.posts || [];
      S.categories = data.categories || [];
      renderChips();
      renderList();
    } catch (e) {
      $("#postList").innerHTML = `<div class="post" style="grid-template-columns:1fr">
        <div><h3>게시판을 불러오지 못했습니다</h3><p class="meta">${esc(e.message)}</p></div></div>`;
    }
  }

  async function openPost(id) {
    const view = $("#postView");
    if (!view) return;
    try {
      const data = await api(`/api/public/board/${encodeURIComponent(id)}`);
      S.current = data.post;
      const p = data.post;
      view.innerHTML = `
        <div class="row" style="gap:8px;flex-wrap:wrap">
          <span class="cat ${esc(p.category)}">${esc(p.categoryLabel)}</span>
          <span class="small muted">${esc(p.author)} · ${esc(when(p.createdAt))}</span>
          <button class="btn sm ghost" id="closePost" style="margin-left:auto" type="button">목록으로</button>
        </div>
        <h2 style="margin-top:10px">${esc(p.title)}</h2>
        <div class="body">${esc(p.body)}</div>
        <div class="comments">
          <h3>댓글 ${p.commentCount || 0}</h3>
          <div id="cmtList">${(p.comments || []).map((c) => `<div class="cmt">
            <div class="who"><b>${esc(c.author)}</b><span>${esc(when(c.createdAt))}</span></div>
            <p>${esc(c.body)}</p>
          </div>`).join("") || '<p class="small muted">첫 댓글을 남겨 보세요.</p>'}</div>
          <form class="cmt-form" id="cmtForm">
            <input class="input" id="cmtAuthor" maxlength="20" placeholder="이름" style="max-width:120px">
            <input class="input grow" id="cmtBody" maxlength="1000" placeholder="댓글을 남겨 주세요">
            <button class="btn sm primary" id="cmtSend" type="submit">등록</button>
          </form>
          <div class="msg" id="cmtMsg" style="min-height:18px"></div>
        </div>`;
      view.classList.remove("hidden");
      $("#closePost").onclick = () => view.classList.add("hidden");
      $("#cmtForm").addEventListener("submit", (e) => {
        e.preventDefault();
        sendComment(p.id);
      });
      view.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e) {
      view.classList.remove("hidden");
      view.innerHTML = `<h2>글을 불러오지 못했습니다</h2><p class="muted small">${esc(e.message)}</p>`;
    }
  }

  async function sendComment(postId) {
    const body = $("#cmtBody").value.trim();
    const author = $("#cmtAuthor").value.trim();
    const msg = $("#cmtMsg");
    msg.textContent = "";
    msg.style.color = "var(--red)";
    if (!body) { msg.textContent = "댓글 내용을 넣어 주세요."; return; }
    const btn = $("#cmtSend");
    btn.disabled = true;
    try {
      const data = await api(`/api/public/board/${postId}/comments`, {
        method: "POST", body: { author, body },
      });
      await openPost(postId);
      await load();
      const again = $("#cmtMsg");
      if (again) { again.textContent = "댓글을 남겼습니다."; again.style.color = "var(--green)"; }
      void data;
    } catch (e) {
      msg.textContent = e.message;
      btn.disabled = false;
    }
  }

  const toggle = $("#writeToggle");
  if (toggle) {
    toggle.addEventListener("click", () => {
      const card = $("#writeCard");
      card.classList.toggle("hidden");
      if (!card.classList.contains("hidden")) $("#bTitle").focus();
    });
  }
  const cancel = $("#bCancel");
  if (cancel) cancel.addEventListener("click", () => $("#writeCard").classList.add("hidden"));

  const form = $("#writeForm");
  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const msg = $("#bMsg");
      msg.textContent = "";
      const body = {
        category: $("#bCategory").value,
        title: $("#bTitle").value.trim(),
        body: $("#bBody").value.trim(),
        author: $("#bAuthor").value.trim(),
      };
      if (body.title.length < 2) { msg.textContent = "제목을 2자 이상 넣어 주세요."; return; }
      if (body.body.length < 5) { msg.textContent = "내용을 5자 이상 넣어 주세요."; return; }
      const btn = $("#bSubmit");
      btn.disabled = true;
      try {
        const data = await api("/api/public/board", { method: "POST", body });
        form.reset();
        $("#writeCard").classList.add("hidden");
        S.category = "";
        await load();
        if (data.post) openPost(data.post.id);
      } catch (err) {
        msg.textContent = err.message;
        btn.disabled = false;
      }
    });
  }

  renderChips();
  load();
})();
