(function () {
  const tbody = document.getElementById("studies-tbody");
  if (!tbody) return; // empty-state, nothing to render/poll

  const POLL_IDLE_MS = 20000;
  const POLL_ACTIVE_MS = 5000;

  function fmtDate(iso) {
    if (!iso) return "\u2014";
    const d = new Date(iso);
    return d.toLocaleDateString() + " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function sampleCountsText(counts) {
    const failedPart = counts.failed
      ? `<span class="failed-count">${counts.failed} failed</span> \u00b7 `
      : "";
    return `${counts.total} total \u00b7 ${failedPart}${counts.success} success \u00b7 ${counts.running} running \u00b7 ${counts.pending} pending`;
  }

  function render(studies) {
    tbody.innerHTML = studies.map((s) => `
      <tr data-study-id="${s.study_id}">
        <td>${s.study_id}</td>
        <td>${s.dataset_profile || "\u2014"}</td>
        <td><span class="badge ${s.status.toLowerCase()}">${s.status}</span></td>
        <td class="sample-counts">${sampleCountsText(s.sample_counts)}</td>
        <td>${fmtDate(s.created_at)}</td>
        <td>${fmtDate(s.last_run_at)}</td>
      </tr>
    `).join("");

    tbody.querySelectorAll("tr").forEach((row) => {
      row.addEventListener("click", () => {
        window.location.href = `/studies/${row.dataset.studyId}`;
      });
    });

    return studies.some((s) => s.status === "RUNNING");
  }

  async function poll() {
    let anyRunning = false;
    try {
      const res = await fetch("/studies");
      const studies = await res.json();
      anyRunning = render(studies);
    } catch (err) {
      console.error("failed to refresh studies", err);
    }
    setTimeout(poll, anyRunning ? POLL_ACTIVE_MS : POLL_IDLE_MS);
  }

  const initial = JSON.parse(document.getElementById("initial-studies").textContent);
  render(initial);
  setTimeout(poll, POLL_IDLE_MS);
})();
