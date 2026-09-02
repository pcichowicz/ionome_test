// Scrollspy: highlight the active sidebar link as the user scrolls.
(function () {
  const navLinks = document.querySelectorAll("nav.sidebar a[href^='#']");
  const targets = Array.from(navLinks)
    .map((a) => document.getElementById(a.getAttribute("href").slice(1)))
    .filter(Boolean);

  if (!targets.length) return;

  const linkFor = (id) =>
    document.querySelector(`nav.sidebar a[href="#${id}"]`);

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        const link = linkFor(entry.target.id);
        if (!link) return;
        if (entry.isIntersecting) {
          navLinks.forEach((a) => a.classList.remove("active"));
          link.classList.add("active");
        }
      });
    },
    { rootMargin: "-20% 0px -70% 0px", threshold: 0 }
  );

  targets.forEach((t) => observer.observe(t));
})();

// ---------------------------------------------------------------------
// Doc tabs: any group of [data-doc-tab] buttons sharing a
// [data-doc-tabgroup] value toggles the matching [data-doc-panel]
// elements. Used by the Documentation page's Getting Started section
// (Web App / CLI & Manual).
// ---------------------------------------------------------------------
(function () {
  const groupNames = new Set(
    Array.from(document.querySelectorAll("[data-doc-tabgroup]")).map((el) => el.dataset.docTabgroup)
  );

  groupNames.forEach((name) => {
    const buttons = document.querySelectorAll(`button[data-doc-tabgroup="${name}"]`);
    const panels = document.querySelectorAll(`[data-doc-panel][data-doc-tabgroup-target="${name}"]`);

    buttons.forEach((btn) => {
      btn.addEventListener("click", () => {
        buttons.forEach((b) => b.classList.remove("active"));
        panels.forEach((p) => p.classList.remove("active"));
        btn.classList.add("active");
        document
          .querySelector(`[data-doc-panel="${btn.dataset.docTab}"][data-doc-tabgroup-target="${name}"]`)
          .classList.add("active");
      });
    });
  });
})();
