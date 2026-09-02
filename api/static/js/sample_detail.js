(function () {
  const studyId = window.STUDY_ID;
  const sampleId = window.SAMPLE_ID;

  async function loadPlots() {
    const container = document.getElementById("sample-plots-container");
    const res = await fetch(`/studies/${studyId}/results/plots`);
    const plots = await res.json();
    const mine = plots.filter((p) => p.category === "chromatograms" && p.filename.startsWith(`${sampleId}_`));
    if (mine.length === 0) {
      container.textContent = "No chromatogram plots for this sample yet -- run the study first.";
      return;
    }
    container.innerHTML = `<div class="plot-grid">${
      mine.map((p) => `<a href="${p.url}" target="_blank"><img src="${p.url}" alt="${p.filename}" title="${p.filename}"></a>`).join("")
    }</div>`;
  }

  loadPlots();
})();
