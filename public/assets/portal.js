// w-toto 공개 포털 — 공통 내비게이션·스크롤 등장·연도
(() => {
  const toggle = $("#navToggle");
  const drawer = $("#navDrawer");
  if (toggle && drawer) {
    const close = () => {
      drawer.classList.remove("open");
      toggle.setAttribute("aria-expanded", "false");
      toggle.textContent = "☰";
      toggle.setAttribute("aria-label", "메뉴 열기");
    };
    toggle.addEventListener("click", () => {
      const open = drawer.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.textContent = open ? "✕" : "☰";
      toggle.setAttribute("aria-label", open ? "메뉴 닫기" : "메뉴 열기");
    });
    drawer.querySelectorAll("a").forEach((a) => a.addEventListener("click", close));
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
  }

  const items = $$(".reveal");
  if (items.length) {
    if ("IntersectionObserver" in window) {
      const io = new IntersectionObserver((entries) => {
        entries.forEach((en) => {
          if (en.isIntersecting) { en.target.classList.add("in"); io.unobserve(en.target); }
        });
      }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });
      items.forEach((el) => io.observe(el));
    } else {
      items.forEach((el) => el.classList.add("in"));
    }
  }

  $$("[data-year]").forEach((el) => { el.textContent = String(new Date().getFullYear()); });
})();
