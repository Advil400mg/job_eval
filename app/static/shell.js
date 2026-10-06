/* Theme preference is applied in <head>, before styles render. No dependency on JEV. */
(() => {
  "use strict";
  const root = document.documentElement;
  let theme = "light";
  try {
    const stored = localStorage.getItem("jev-theme");
    if (stored === "light" || stored === "dark") theme = stored;
  } catch (_) { /* Storage may be disabled; navigation and forms must still work. */ }
  root.dataset.theme = theme;

  function themeLabel() {
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      button.setAttribute("aria-label", `Activer le thème ${root.dataset.theme === "dark" ? "clair" : "sombre"}`);
      button.setAttribute("title", root.dataset.theme === "dark" ? "Passer au thème clair" : "Passer au thème sombre");
    });
  }
  function boot() {
    themeLabel();
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      button.addEventListener("click", () => {
        root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
        try { localStorage.setItem("jev-theme", root.dataset.theme); } catch (_) { /* Optional preference. */ }
        themeLabel();
      });
    });
    const sidebar = document.querySelector("#app_sidebar");
    const toggle = document.querySelector("#app_menu_toggle");
    const backdrop = document.querySelector("#app_menu_backdrop");
    const workspace = document.querySelector("#app_workspace");
    if (!sidebar || !toggle || !backdrop) return;
    const narrow = window.matchMedia("(max-width: 980px)");
    let open = false;
    function setMenu(value, restoreFocus = true) {
      open = Boolean(value && narrow.matches);
      sidebar.classList.toggle("open", open);
      backdrop.classList.toggle("hidden", !open);
      toggle.setAttribute("aria-expanded", String(open));
      toggle.setAttribute("aria-label", open ? "Fermer le menu" : "Ouvrir le menu");
      if (workspace) workspace.inert = open;
      if (open) {
        sidebar.setAttribute("role", "dialog");
        sidebar.setAttribute("aria-modal", "true");
        sidebar.querySelector("a[href]")?.focus();
      } else {
        sidebar.removeAttribute("role");
        sidebar.removeAttribute("aria-modal");
        if (restoreFocus && narrow.matches) toggle.focus();
      }
    }
    toggle.addEventListener("click", () => setMenu(!open));
    backdrop.addEventListener("click", () => setMenu(false));
    sidebar.addEventListener("click", (event) => { if (event.target.closest("a[href]")) setMenu(false, false); });
    document.addEventListener("keydown", (event) => {
      if (!open) return;
      if (event.key === "Escape") { setMenu(false); return; }
      if (event.key !== "Tab") return;
      const elements = [...sidebar.querySelectorAll("a[href],button:not([disabled]),[tabindex='0']")].filter((item) => item.offsetParent !== null);
      const first = elements[0], last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    });
    narrow.addEventListener("change", () => setMenu(false, false));
    root.classList.add("jev-enhanced");
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot, { once: true });
  else boot();
})();
