(function () {
  const state = { studyId: null, sampleIds: [], configDefaults: null };

  const errorSummary = document.getElementById("error-summary");
  function showErrors(messages) {
    errorSummary.innerHTML = "<strong>Couldn't create study:</strong><ul>" +
      messages.map((m) => `<li>${m}</li>`).join("") + "</ul>";
    errorSummary.style.display = "block";
    errorSummary.scrollIntoView({ behavior: "smooth" });
  }
  function clearErrors() {
    errorSummary.style.display = "none";
    errorSummary.innerHTML = "";
  }

  function showStep(n) {
    document.querySelectorAll(".wizard-step").forEach((el) => el.classList.remove("active"));
    document.getElementById(`step-${n}`).classList.add("active");
  }

  // -- Step 1: scan raw dir --------------------------------------------
  document.getElementById("scan-btn").addEventListener("click", async () => {
    clearErrors();
    const studyId = document.getElementById("study-id-input").value.trim();
    if (!studyId) {
      showErrors(["Study ID is required."]);
      return;
    }
    try {
      const res = await fetch(`/studies/${encodeURIComponent(studyId)}/raw-files`);
      const data = await res.json();
      state.studyId = studyId;
      state.sampleIds = data.sample_ids;

      const summary = document.getElementById("scan-summary");
      if (!data.dir_exists) {
        summary.textContent = `No directory found at ${data.raw_data_dir} yet -- drop the .mzML/.mzXML files there first.`;
      } else if (data.sample_ids.length === 0) {
        summary.textContent = `${data.raw_data_dir} exists but no .mzML/.mzXML files were found in it.`;
      } else {
        summary.textContent = `Found ${data.sample_ids.length} raw file(s) in ${data.raw_data_dir}.`;
      }
      renderSamplesTable();
      showStep(2);
    } catch (err) {
      showErrors(["Couldn't reach the server to scan for raw files."]);
    }
  });

  function renderSamplesTable() {
    const tbody = document.getElementById("samples-tbody");
    tbody.innerHTML = state.sampleIds.map((sid) => `
      <tr>
        <td>${sid}</td>
        <td><input type="text" class="sample-role-input" data-sample-id="${sid}" placeholder="e.g. QC / NSC / T691"></td>
      </tr>
    `).join("");
  }

  document.getElementById("back-to-1").addEventListener("click", () => showStep(1));

  // -- Step 2 -> 3: pre-fill config defaults -----------------------------
  document.getElementById("to-step-3").addEventListener("click", async () => {
    if (!state.configDefaults) {
      try {
        const res = await fetch("/studies/config-defaults");
        state.configDefaults = await res.json();
      } catch (err) {
        showErrors(["Couldn't load config defaults from the server."]);
        return;
      }
    }
    showStep(3);
  });
  document.getElementById("back-to-2").addEventListener("click", () => showStep(2));

  // -- Step 3: submit -----------------------------------------------------
  document.getElementById("submit-btn").addEventListener("click", async () => {
    clearErrors();
    const submitBtn = document.getElementById("submit-btn");
    submitBtn.disabled = true;

    const sampleRows = state.sampleIds.map((sid) => ({
      sample_id: sid,
      sample_role: document.querySelector(`.sample-role-input[data-sample-id="${sid}"]`).value.trim(),
    }));

    const config = JSON.parse(JSON.stringify(state.configDefaults));
    config.study = {
      id: state.studyId,
      polarity: document.getElementById("polarity-input").value,
      instrument: document.getElementById("instrument-input").value.trim(),
    };
    config.dataset_profile = document.getElementById("profile-input").value;
    config.files = { sample_metadata: `${state.studyId}_sample_metadata.csv` };

    try {
      const res = await fetch("/studies", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config, sample_rows: sampleRows }),
      });
      if (!res.ok) {
        const body = await res.json();
        const messages = Array.isArray(body.detail) ? body.detail : [body.detail || "Unknown error."];
        showErrors(messages);
        submitBtn.disabled = false;
        return;
      }
      const result = await res.json();
      window.location.href = `/studies/${result.study_id}`;
    } catch (err) {
      showErrors(["Couldn't reach the server to create the study."]);
      submitBtn.disabled = false;
    }
  });
})();
