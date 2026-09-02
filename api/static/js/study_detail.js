(function () {
  const studyId = window.STUDY_ID;

  // -- tabs, lazy-load each panel's data the first time it's shown --
  const loaders = { plots: loadPlots, table: loadTablePreview, qc: loadQcReport, runs: loadRuns };
  const loaded = new Set();

  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      const tab = btn.dataset.tab;
      document.getElementById(`tab-${tab}`).classList.add("active");
      if (!loaded.has(tab) && loaders[tab]) {
        loaded.add(tab);
        loaders[tab]();
      }
    });
  });

  async function loadReadiness() {
    const res = await fetch(`/studies/${studyId}/sample-readiness`);
    const data = await res.json();
    const line = document.getElementById("readiness-line");
    line.textContent = data.missing.length === 0
      ? `${data.present.length} of ${data.expected.length} expected samples present.`
      : `${data.present.length} of ${data.expected.length} expected samples present -- missing: ${data.missing.join(", ")}`;
  }

  async function loadSamples() {
    const res = await fetch(`/studies/${studyId}/samples`);
    const samples = await res.json();
    document.getElementById("samples-tbody").innerHTML = samples.map((s) => `
      <tr data-sample-id="${s.sample_id}">
        <td>${s.sample_id}</td>
        <td>${s.description || "\u2014"}</td>
        <td><span class="badge ${s.status.toLowerCase()}">${s.status}</span></td>
      </tr>
    `).join("");
    document.querySelectorAll("#samples-tbody tr").forEach((row) => {
      row.style.cursor = "pointer";
      row.addEventListener("click", () => {
        window.location.href = `/studies/${studyId}/samples/${row.dataset.sampleId}`;
      });
    });
  }

  async function loadPlots() {
    const container = document.getElementById("plots-container");
    const res = await fetch(`/studies/${studyId}/results/plots`);
    const plots = await res.json();
    if (plots.length === 0) {
      container.textContent = "No plots yet -- run the study first.";
      return;
    }
    const byCategory = {};
    plots.forEach((p) => { (byCategory[p.category] ||= []).push(p); });
    const categories = Object.keys(byCategory);

    const subtabsHtml = `<nav class="subtabs">${
      categories.map((c, i) => `<button class="subtab-btn${i === 0 ? " active" : ""}" data-category="${c}">${c.replace(/_/g, " ")}</button>`).join("")
    }</nav>`;
    const panelsHtml = categories.map((c, i) => `
      <div class="plot-grid subtab-panel${i === 0 ? " active" : ""}" data-category="${c}">
        ${byCategory[c].map((p) => `<a href="${p.url}" target="_blank"><img src="${p.url}" alt="${p.filename}" title="${p.filename}"></a>`).join("")}
      </div>
    `).join("");
    container.innerHTML = subtabsHtml + panelsHtml;

    container.querySelectorAll(".subtab-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        container.querySelectorAll(".subtab-btn").forEach((b) => b.classList.remove("active"));
        container.querySelectorAll(".subtab-panel").forEach((p) => p.classList.remove("active"));
        btn.classList.add("active");
        container.querySelector(`.subtab-panel[data-category="${btn.dataset.category}"]`).classList.add("active");
      });
    });
  }

  async function loadTablePreview() {
    const container = document.getElementById("table-container");
    const res = await fetch(`/studies/${studyId}/results/table/preview`);
    if (!res.ok) {
      container.textContent = "No feature table / library yet -- run the study first.";
      return;
    }
    const data = await res.json();
    const headerRow = data.columns.map((c) => `<th>${c}</th>`).join("");
    const bodyRows = data.rows.map((row) =>
      `<tr>${data.columns.map((c) => `<td>${row[c] ?? ""}</td>`).join("")}</tr>`
    ).join("");
    container.innerHTML = `
      <p class="hint">Showing ${data.rows.length} of ${data.total_rows} rows.
        <a href="${data.download_url}">Download full CSV</a></p>
      <div class="table-scroll"><table><thead><tr>${headerRow}</tr></thead><tbody>${bodyRows}</tbody></table></div>
    `;
  }

  async function loadQcReport() {
    const container = document.getElementById("qc-report-container");
    const res = await fetch(`/studies/${studyId}/results/qc-report`);
    if (!res.ok) {
      container.textContent = "No QC report yet -- run the study first.";
      return;
    }
    container.textContent = JSON.stringify(await res.json(), null, 2);
  }

  async function loadRuns() {
    const res = await fetch(`/studies/${studyId}/results/runs`);
    const runs = await res.json();
    document.getElementById("runs-tbody").innerHTML = runs.map((r) => `
      <tr>
        <td>${r.run_id}</td>
        <td><span class="badge ${r.status.toLowerCase()}">${r.status}</span></td>
        <td>${r.started_at || "\u2014"}</td>
        <td>${r.finished_at || "\u2014"}</td>
        <td>${r.n_steps}</td>
      </tr>
    `).join("");
  }

  document.getElementById("run-btn").addEventListener("click", async () => {
    const btn = document.getElementById("run-btn");
    btn.disabled = true;
    const res = await fetch(`/studies/${studyId}/run`, { method: "POST" });
    const data = await res.json();
    document.getElementById("run-status-line").textContent = `Run started (run_id: ${data.run_id}).`;
    setTimeout(() => { loadSamples(); btn.disabled = false; }, 3000);
  });

  loadReadiness();
  loadSamples();
})();
