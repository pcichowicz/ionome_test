# docs/ — GitHub Pages site

This folder is a self-contained static site (no build step, no Jekyll
needed) documenting Ionome, the LC-MS pipeline project.

## Enable GitHub Pages

1. Push this `docs/` folder to your repo's default branch (e.g. `main`).
2. On GitHub: **Settings → Pages**.
3. Under **Build and deployment → Source**, choose **Deploy from a
   branch**.
4. Branch: `main` (or whichever), folder: **/docs**. Save.
5. GitHub will publish at `https://<username>.github.io/<repo>/` within a
   minute or two.

## Preview locally

No build tools required — just serve the folder (opening a page directly
via `file://` still works fine now, but a local server is the closer match
to how GitHub Pages actually serves it):

```bash
cd docs
python3 -m http.server 8000
# then open http://localhost:8000
```

## Structure

```
docs/
├── index.html          — Home
├── pipeline.html        — Pipeline Overview: workflow, architecture, design decisions
├── background.html      — Scientific Background
├── documentation.html   — Install, Getting Started (web app / CLI), using the web app, config, REST API reference, Stage contract
├── stages.html          — All 16 cohort-mode stages, in run order
├── gallery.html         — Real results (volcano/heatmap/PLS-DA/XIC) from MTBLS1301
├── development.html     — Roadmap: done / open / deferred
├── about.html           — Project motivation, links
├── css/style.css        — shared across every page
├── js/main.js            — scrollspy nav (per-page anchors) + Documentation page's Getting Started tab toggle
├── assets/diagrams/      — static SVG architecture diagrams
└── assets/results/       — real result PNGs (volcano/heatmap/PLS-DA/XIC), used directly by gallery.html
```

Every page shares the same `nav.site-nav` top bar (`css/style.css`'s
`site-nav` rules) with the current page marked via a `class="current"` link
— set directly in each page's HTML at build time, not detected by JS, since
that's simpler and doesn't depend on JS running correctly for basic nav to
work. Each page also keeps its own `nav.sidebar` for in-page anchor links
to that page's own sections (unchanged pattern from the original
single-page site).

## Filling in the content

- **Stage descriptions**: `stages.html` has real content for all 16 stages.
  If a stage's implementation changes, keep using the established pattern —
  one-sentence purpose, an `input → output` line, a `.finding` callout for
  any real bug found & fixed, a `.decision` callout for any deliberate
  design choice, and a small comparison table for anything that differs
  between the two profiles.
- **`documentation.html`**: Installation, Getting Started, Using the Web
  App, Configuration, and API Reference are all filled in with real
  content. One TODO remains: a real standalone CLI entrypoint doesn't
  exist yet (see the CLI/Manual tab in Getting Started) — today that path
  means writing files by hand and either calling the API or
  `run_pipeline_for_study` directly. The Stage Contract section's full
  class/method reference is also still a TODO.
- **`about.html`** is now a fill-in-the-blanks template (Motivation /
  Background / This project / Get in touch) rather than a single generic
  TODO — still needs your actual content.
- **Result images**: `gallery.html` currently uses whatever real result
  PNGs were on hand when this was built. Re-run the relevant stat-plot
  stages and swap the files in `assets/results/` to update it — filenames
  are referenced directly in `gallery.html`.
- **Repo link**: every `https://github.com/YOUR_USERNAME/YOUR_REPO` href
  (site-nav on every page, hero/footer, About page) is a clearly-marked
  placeholder — swap in your actual repo URL.
