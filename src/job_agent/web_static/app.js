const state = {
  demo: true,
  jobs: [],
  applications: [],
  selectedJobId: null,
  dbPath: null,
  profileReady: false,
  profileSource: "demo",
  cvDirty: false,
  config: {},
  pipelineRunning: false,
  emailSyncReady: false,
  authenticated: false,
  authMode: "login",
  user: null,
  csrfToken: null,
};
let lastProfileName = "";
let appBooted = false;

const $ = (sel) => document.querySelector(sel);

// Headers for state-changing POSTs: JSON + the double-submit CSRF token.
function jsonHeaders() {
  const headers = { "Content-Type": "application/json" };
  if (state.csrfToken) headers["X-CSRF-Token"] = state.csrfToken;
  return headers;
}
const els = {
  authView: $("#authView"),
  appShell: $("#appShell"),
  authForm: $("#authForm"),
  loginTabBtn: $("#loginTabBtn"),
  registerTabBtn: $("#registerTabBtn"),
  authEmailInput: $("#authEmailInput"),
  authPasswordInput: $("#authPasswordInput"),
  authConfirmField: $("#authConfirmField"),
  authConfirmInput: $("#authConfirmInput"),
  authSubmitBtn: $("#authSubmitBtn"),
  authMessage: $("#authMessage"),
  statusText: $("#statusText"),
  globalProgress: $("#globalProgress"),
  progressLabel: $("#progressLabel"),
  progressPct: $("#progressPct"),
  progressFill: $("#progressFill"),
  agentProgress: $("#agentProgress"),
  providerBadge: $("#providerBadge"),
  currentUserLabel: $("#currentUserLabel"),
  logoutBtn: $("#logoutBtn"),
  // profil
  dropzone: $("#dropzone"),
  cvFile: $("#cvFile"),
  cvFileStatus: $("#cvFileStatus"),
  cvInput: $("#cvInput"),
  buildProfileBtn: $("#buildProfileBtn"),
  demoProfileBtn: $("#demoProfileBtn"),
  goPipelineBtn: $("#goPipelineBtn"),
  profilePanel: $("#profilePanel"),
  profileStatus: $("#profileStatus"),
  // pipeline
  queryInput: $("#queryInput"),
  limitInput: $("#limitInput"),
  thresholdInput: $("#thresholdInput"),
  demoModeBtn: $("#demoModeBtn"),
  liveModeBtn: $("#liveModeBtn"),
  llmInput: $("#llmInput"),
  chromaInput: $("#chromaInput"),
  draftAllInput: $("#draftAllInput"),
  resetInput: $("#resetInput"),
  dbPathInput: $("#dbPathInput"),
  runBtn: $("#runBtn"),
  activeProfile: $("#activeProfile"),
  jobsMetric: $("#jobsMetric"),
  matchesMetric: $("#matchesMetric"),
  draftsMetric: $("#draftsMetric"),
  trackedMetric: $("#trackedMetric"),
  dbPathLabel: $("#dbPathLabel"),
  jobsBody: $("#jobsBody"),
  detailTitle: $("#detailTitle"),
  jobLink: $("#jobLink"),
  jobDetail: $("#jobDetail"),
  letterBody: $("#letterBody"),
  copyBtn: $("#copyBtn"),
  statusSelect: $("#statusSelect"),
  notesInput: $("#notesInput"),
  emailRecipientInput: $("#emailRecipientInput"),
  sendEmailBtn: $("#sendEmailBtn"),
  syncInboxBtn: $("#syncInboxBtn"),
  saveStatusBtn: $("#saveStatusBtn"),
};

const AGENT_STEPS = [
  { key: "scout", idle: "Wartet", active: "Jobs suchen", done: "Jobs gefunden" },
  { key: "matcher", idle: "Wartet", active: "Bewerten", done: "Bewertet" },
  { key: "writer", idle: "Wartet", active: "Anschreiben", done: "Entwürfe erstellt" },
  { key: "tracker", idle: "Wartet", active: "Speichern", done: "Gespeichert" },
];

/* ----------------------------- auth -------------------------------- */
function setAuthMode(mode) {
  state.authMode = mode;
  const register = mode === "register";
  els.loginTabBtn.classList.toggle("active", !register);
  els.registerTabBtn.classList.toggle("active", register);
  els.authConfirmField.classList.toggle("hidden", !register);
  els.authPasswordInput.autocomplete = register ? "new-password" : "current-password";
  els.authSubmitBtn.textContent = register ? "Account erstellen" : "Einloggen";
  els.authMessage.textContent = "";
}

function showAuthenticated(user) {
  state.authenticated = true;
  state.user = user;
  els.authView.classList.add("hidden");
  els.appShell.classList.remove("hidden");
  els.currentUserLabel.textContent = user?.email || "";
}

function showAuth() {
  state.authenticated = false;
  state.user = null;
  els.appShell.classList.add("hidden");
  els.authView.classList.remove("hidden");
  els.currentUserLabel.textContent = "";
}

async function checkAuth() {
  try {
    const res = await fetch("/api/auth/me");
    const data = await res.json();
    if (res.ok && data.authenticated) {
      state.csrfToken = data.csrf_token || null;
      showAuthenticated(data.user);
      await bootApp();
      return;
    }
  } catch {
    // Stay on auth view.
  }
  showAuth();
}

async function submitAuth(event) {
  event.preventDefault();
  const email = els.authEmailInput.value.trim();
  const password = els.authPasswordInput.value;
  const confirm = els.authConfirmInput.value;
  if (state.authMode === "register" && password !== confirm) {
    els.authMessage.textContent = "Passwörter stimmen nicht überein.";
    return;
  }
  els.authSubmitBtn.disabled = true;
  els.authMessage.textContent = "";
  try {
    const res = await fetch(`/api/auth/${state.authMode === "register" ? "register" : "login"}`, {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Anmeldung fehlgeschlagen");
    state.csrfToken = data.csrf_token || null;
    showAuthenticated(data.user);
    await bootApp();
  } catch (err) {
    els.authMessage.textContent = err.message;
  } finally {
    els.authSubmitBtn.disabled = false;
  }
}

async function logout() {
  await fetch("/api/auth/logout", { method: "POST" });
  appBooted = false;
  showAuth();
}

async function bootApp() {
  if (appBooted) return;
  setMode(true);
  updateActiveProfile("demo");
  syncStatusControls(null);
  await loadConfig().finally(() => loadDemoProfile());
  route();
  appBooted = true;
}

/* ----------------------------- routing ----------------------------- */
const ROUTES = ["profil", "pipeline"];
function route() {
  let r = location.hash.replace(/^#\/?/, "") || "profil";
  if (!ROUTES.includes(r)) r = "profil";
  document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
  const view = document.getElementById("view-" + r);
  if (view) view.classList.remove("hidden");
  document.querySelectorAll(".nav-link").forEach((b) =>
    b.classList.toggle("active", b.dataset.route === r)
  );
}
window.addEventListener("hashchange", route);
document.querySelectorAll(".nav-link").forEach((b) =>
  b.addEventListener("click", () => {
    location.hash = "#/" + b.dataset.route;
  })
);

/* ----------------------------- progress ---------------------------- */
const progress = {
  show(label, pct) {
    els.globalProgress.classList.remove("hidden");
    els.globalProgress.classList.remove("complete", "failed");
    toggleAgentProgress(state.pipelineRunning);
    els.progressLabel.textContent = label;
    if (pct == null) {
      els.globalProgress.classList.add("indeterminate");
      els.progressPct.textContent = "";
      if (!state.pipelineRunning) renderAgentProgress(null, 0);
    } else {
      this.set(pct, label);
    }
  },
  set(pct, label) {
    els.globalProgress.classList.remove("hidden", "indeterminate", "complete", "failed");
    els.progressFill.style.width = Math.max(0, Math.min(100, pct)) + "%";
    els.progressPct.textContent = Math.round(pct) + "%";
    if (label) els.progressLabel.textContent = label;
    if (state.pipelineRunning) {
      toggleAgentProgress(true);
      renderAgentProgress(label, pct);
    }
  },
  finish(label = "Pipeline abgeschlossen") {
    els.globalProgress.classList.remove("hidden", "indeterminate", "failed");
    this.set(100, label);
    els.globalProgress.classList.add("complete");
    renderAgentProgress("Fertig", 100);
  },
  fail(label) {
    els.globalProgress.classList.remove("hidden", "indeterminate", "complete");
    toggleAgentProgress(true);
    els.globalProgress.classList.add("failed");
    els.progressLabel.textContent = label;
    els.progressPct.textContent = "";
    markAgentProgressFailed();
  },
  hide() {
    els.globalProgress.classList.add("hidden");
    els.globalProgress.classList.remove("indeterminate", "complete", "failed");
    els.progressFill.style.width = "0%";
    toggleAgentProgress(false);
    renderAgentProgress(null, 0);
  },
};

function toggleAgentProgress(visible) {
  if (!els.agentProgress) return;
  els.agentProgress.classList.toggle("is-hidden", !visible);
}

function renderAgentProgress(stage, pct) {
  if (!els.agentProgress) return;
  const activeIndex = agentIndexFromStage(stage, pct);
  els.agentProgress
    .querySelectorAll(".agent-step")
    .forEach((step, index) => {
      const meta = AGENT_STEPS[index];
      const label = step.querySelector("small");
      step.classList.remove("active", "done", "failed");
      if (activeIndex === -1) {
        if (label) label.textContent = meta.idle;
        return;
      }
      if (pct >= 100 || index < activeIndex) {
        step.classList.add("done");
        if (label) label.textContent = meta.done;
      } else if (index === activeIndex) {
        step.classList.add("active");
        if (label) label.textContent = meta.active;
      } else if (label) {
        label.textContent = meta.idle;
      }
    });
}

function markAgentProgressFailed() {
  if (!els.agentProgress) return;
  const current = els.agentProgress.querySelector(".agent-step.active");
  if (current) {
    current.classList.remove("active");
    current.classList.add("failed");
    const label = current.querySelector("small");
    if (label) label.textContent = "Fehler";
  }
}

function agentIndexFromStage(stage, pct) {
  const text = String(stage || "").toLowerCase();
  if (pct >= 100 || text.includes("fertig")) return AGENT_STEPS.length;
  if (text.includes("tracker")) return 3;
  if (text.includes("writer")) return 2;
  if (text.includes("matcher")) return 1;
  if (text.includes("scout") || text.includes("pipeline startet")) return 0;
  return -1;
}

function setBusy(busy) {
  if (els.runBtn) els.runBtn.disabled = busy;
  if (els.buildProfileBtn) els.buildProfileBtn.disabled = busy;
  if (els.demoProfileBtn) els.demoProfileBtn.disabled = busy;
  if (els.saveStatusBtn) els.saveStatusBtn.disabled = busy;
  if (els.sendEmailBtn) els.sendEmailBtn.disabled = busy;
  if (els.syncInboxBtn) els.syncInboxBtn.disabled = busy || !state.emailSyncReady;
  document.body.toggleAttribute("aria-busy", busy);
  els.statusText.textContent = busy ? "Arbeite …" : "Bereit";
}

/* --------------------------- CV import ----------------------------- */
function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
    reader.onerror = () => reject(new Error("Datei konnte nicht gelesen werden"));
    reader.readAsDataURL(file);
  });
}

async function importCvFile(file) {
  const maxBytes = (state.config.max_cv_upload_mb || 8) * 1024 * 1024;
  if (file.size > maxBytes) {
    els.cvFileStatus.textContent = `Fehler: Datei ist größer als ${state.config.max_cv_upload_mb || 8} MB.`;
    return;
  }
  progress.show(`Lese „${file.name}" (OCR bei Scans) …`, null);
  els.cvFileStatus.textContent = `Verarbeite ${file.name} …`;
  setBusy(true);
  try {
    const content_base64 = await fileToBase64(file);
    const res = await fetch("/api/extract-cv", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ filename: file.name, content_base64 }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Import fehlgeschlagen");
    els.cvInput.value = data.cv_text || "";
    state.cvDirty = true;
    state.profileReady = false;
    state.profileSource = "pending";
    updateActiveProfile("pending");
    els.cvFileStatus.textContent = `✓ ${data.filename}: ${data.chars} Zeichen gelesen. Jetzt „Profil erstellen & prüfen".`;
  } catch (err) {
    els.cvFileStatus.textContent = `Fehler: ${err.message}`;
  } finally {
    progress.hide();
    setBusy(false);
  }
}

if (els.cvInput) {
  els.cvInput.addEventListener("input", () => {
    state.cvDirty = Boolean(els.cvInput.value.trim());
    if (state.cvDirty) {
      state.profileReady = false;
      state.profileSource = "pending";
      updateActiveProfile("pending");
    }
  });
}

if (els.dropzone) {
  els.dropzone.addEventListener("click", () => els.cvFile.click());
  els.dropzone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      els.cvFile.click();
    }
  });
  ["dragover", "dragenter"].forEach((ev) =>
    els.dropzone.addEventListener(ev, (e) => {
      e.preventDefault();
      els.dropzone.classList.add("dragover");
    })
  );
  ["dragleave", "drop"].forEach((ev) =>
    els.dropzone.addEventListener(ev, (e) => {
      e.preventDefault();
      els.dropzone.classList.remove("dragover");
    })
  );
  els.dropzone.addEventListener("drop", (e) => {
    const f = e.dataTransfer.files && e.dataTransfer.files[0];
    if (f) importCvFile(f);
  });
  els.cvFile.addEventListener("change", (e) => {
    const f = e.target.files && e.target.files[0];
    if (f) importCvFile(f);
  });
}

/* --------------------------- build profile ------------------------- */
async function buildProfile() {
  const cv_text = els.cvInput ? els.cvInput.value : "";
  progress.show("Profil wird erstellt (LLM) …", null);
  setBusy(true);
  try {
    const res = await fetch("/api/build-profile", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ cv_text }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Profil-Erstellung fehlgeschlagen");
    renderProfile(data);
    if (data.profile && data.profile.name) {
      lastProfileName = data.profile.name;
      state.profileReady = true;
      state.profileSource = data.source || "demo";
      state.cvDirty = data.source !== "cv" && Boolean(cv_text.trim());
      updateActiveProfile(data.source);
    }
    els.cvFileStatus.textContent =
      data.source === "cv" ? "✓ Profil aus CV erstellt." : "Demo-Profil angezeigt.";
  } catch (err) {
    els.cvFileStatus.textContent = `Fehler: ${err.message}`;
  } finally {
    progress.hide();
    setBusy(false);
  }
}
if (els.buildProfileBtn) els.buildProfileBtn.addEventListener("click", buildProfile);

async function loadDemoProfile() {
  progress.show("Demo-Profil wird geladen", null);
  setBusy(true);
  try {
    const res = await fetch("/api/use-demo-profile", { method: "POST", headers: jsonHeaders() });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Demo-Profil konnte nicht geladen werden");
    if (els.cvInput) els.cvInput.value = "";
    renderProfile(data);
    lastProfileName = data.profile?.name || "";
    state.profileReady = true;
    state.profileSource = "demo";
    state.cvDirty = false;
    updateActiveProfile("demo");
    els.cvFileStatus.textContent = "Demo-Profil geladen. Du kannst direkt die Pipeline starten.";
  } catch (err) {
    els.cvFileStatus.textContent = `Fehler: ${err.message}`;
  } finally {
    progress.hide();
    setBusy(false);
  }
}

function updateActiveProfile(source) {
  const label = profileLabel(source);
  if (els.activeProfile) {
    els.activeProfile.textContent = label;
  }
  if (els.profileStatus) {
    els.profileStatus.className = `profile-status ${source || "demo"}`;
    els.profileStatus.textContent = label || "Aktives Profil: Demo-Profil";
  }
}

function profileLabel(source) {
  if (source === "pending") return "CV importiert, Profil noch nicht erstellt";
  if (!lastProfileName) return "Aktives Profil: Demo-Profil";
  const suffix = source === "cv" ? "aus CV" : "Demo";
  return `Aktives Profil: ${lastProfileName} (${suffix})`;
}

function renderProfile(data) {
  const p = data && data.profile;
  if (!els.profilePanel || !p) return;
  els.profilePanel.classList.remove("profile-empty");
  const skillCount = (p.skills || []).length;
  const expCount = (p.experience || []).length;
  const langCount = Object.keys(p.languages || {}).length;
  const langs =
    Object.entries(p.languages || {})
      .map(([c, l]) => `${escapeHtml(c)}: ${escapeHtml(l)}`)
      .join(" · ") || "-";
  const exp =
    (p.experience || [])
      .map(
        (e) => `<div class="pf-item">
          <div class="pf-item-head"><strong>${escapeHtml(e.role || "-")}</strong>
          <span class="pf-dates">${escapeHtml(e.start || "?")} – ${escapeHtml(e.end || "heute")}</span></div>
          <span class="pf-sub">${escapeHtml(e.company || "")}</span>
          ${e.summary ? `<p>${escapeHtml(e.summary)}</p>` : ""}
          <div class="skill-list">${pillList(e.skills_used)}</div></div>`
      )
      .join("") || '<span class="empty">-</span>';
  const edu =
    (p.education || [])
      .map(
        (e) => `<div class="pf-item">
          <div class="pf-item-head"><strong>${escapeHtml(e.degree || "")} ${escapeHtml(e.field || "")}</strong>
          <span class="pf-dates">${escapeHtml(e.start || "?")} – ${escapeHtml(e.end || "heute")}</span></div>
          <span class="pf-sub">${escapeHtml(e.institution || "")}</span></div>`
      )
      .join("") || '<span class="empty">-</span>';
  const pr = p.preferences || {};
  const prefStr = `Orte: ${escapeHtml((pr.locations || []).join(", ") || "-")} · Remote: ${
    pr.remote_ok ? "ja" : "nein"
  } · Art: ${escapeHtml((pr.employment_types || []).join(", ") || "-")}`;
  const banner = data.warning
    ? `<div class="pf-warning">⚠ ${escapeHtml(data.warning)}</div>`
    : data.source === "demo"
      ? `<div class="pf-note">Demo-Profil (Vorschau). Importiere einen Lebenslauf für dein echtes Profil.</div>`
      : "";
  els.profilePanel.innerHTML = `${banner}
    <div class="profile-head">
      <h2>${escapeHtml(p.name || "-")}</h2>
      <p class="pf-headline">${escapeHtml(p.headline || "")}</p>
      <p class="pf-contact">${escapeHtml(p.location || "")}${p.email ? " · " + escapeHtml(p.email) : ""}${
        p.phone ? " · " + escapeHtml(p.phone) : ""
      }</p>
    </div>
    <div class="profile-kpis">
      <div><span>Skills</span><strong>${skillCount}</strong></div>
      <div><span>Stationen</span><strong>${expCount}</strong></div>
      <div><span>Sprachen</span><strong>${langCount}</strong></div>
    </div>
    <div class="pf-cols">
      <div class="pf-section"><h3>Skills</h3><div class="skill-list">${pillList(p.skills)}</div></div>
      <div class="pf-section"><h3>Sprachen</h3><p>${langs}</p></div>
    </div>
    <div class="pf-section"><h3>Erfahrung</h3>${exp}</div>
    <div class="pf-section"><h3>Ausbildung</h3>${edu}</div>
    <div class="pf-section"><h3>Präferenzen</h3><p>${prefStr}</p></div>`;
}

/* --------------------------- pipeline ------------------------------ */
function setMode(demo) {
  state.demo = demo;
  els.demoModeBtn.classList.toggle("active", demo);
  els.liveModeBtn.classList.toggle("active", !demo);
  els.dbPathInput.value = demo ? "./data/demo_job_agent.db" : "./data/job_agent.db";
  if (demo && state.profileSource !== "cv") {
    state.profileSource = "demo";
    state.cvDirty = false;
  }
}

function payload() {
  const data = {
    demo: state.demo,
    query: els.queryInput.value,
    limit: Number(els.limitInput.value || 5),
    threshold: Number(els.thresholdInput.value || 0.5),
    db_path: els.dbPathInput.value,
    reset_db: els.resetInput.checked,
    llm_agents: els.llmInput.checked,
    chroma: els.chromaInput.checked,
    draft_all: els.draftAllInput.checked,
    force_demo_profile: state.demo && state.profileSource === "demo",
  };
  const cvText = els.cvInput ? els.cvInput.value.trim() : "";
  if (state.cvDirty && cvText) {
    data.cv_text = cvText;
  }
  return data;
}

async function runPipeline() {
  setBusy(true);
  state.pipelineRunning = true;
  progress.set(3, "Pipeline startet …");
  try {
    const res = await fetch("/api/run-pipeline-async", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(payload()),
    });
    const start = await res.json();
    if (!res.ok || !start.ok) throw new Error(start.error || "Start fehlgeschlagen");
    const result = await pollPipeline(start.job_id);
    applyData(result);
    els.statusText.textContent = "Pipeline abgeschlossen";
    progress.finish();
  } catch (err) {
    els.statusText.innerHTML = `<span class="toast">${escapeHtml(err.message)}</span>`;
    progress.fail(`Fehler: ${err.message}`);
  } finally {
    state.pipelineRunning = false;
    setBusy(false);
  }
}

function pollPipeline(jobId) {
  return new Promise((resolve, reject) => {
    const tick = async () => {
      try {
        const r = await fetch(`/api/pipeline-progress?id=${encodeURIComponent(jobId)}`);
        const d = await r.json();
        if (!d.ok) return reject(new Error(d.error || "Fortschritt unbekannt"));
        progress.set(d.percent, d.stage);
        if (d.done) {
          if (d.error) return reject(new Error(d.error));
          return resolve(d.result);
        }
        setTimeout(tick, 350);
      } catch (e) {
        reject(e);
      }
    };
    tick();
  });
}

function applyData(data) {
  if (!data) return;
  state.jobs = data.jobs || [];
  state.applications = data.applications || [];
  state.selectedJobId = state.jobs[0]?.id || null;
  const s = data.summary || {};
  els.jobsMetric.textContent = s.jobs || 0;
  els.matchesMetric.textContent = s.matches || 0;
  els.draftsMetric.textContent = s.drafts || 0;
  els.trackedMetric.textContent = s.tracked || 0;
  els.dbPathLabel.textContent = data.db_path || "";
  state.dbPath = data.db_path || state.dbPath;
  if (data.profile && data.profile.name) {
    lastProfileName = data.profile.name;
    state.profileReady = true;
    state.profileSource = data.profile.source || (data.profile.from_cv ? "cv" : "demo");
    state.cvDirty = false;
    updateActiveProfile(state.profileSource);
  }
  renderJobs();
  renderDetail();
  renderLetter();
}

function renderJobs() {
  if (!state.jobs.length) {
    els.jobsBody.innerHTML = '<tr><td colspan="5" class="empty">Noch keine Jobs — starte die Pipeline.</td></tr>';
    return;
  }
  els.jobsBody.innerHTML = state.jobs
    .map((job) => {
      const score = typeof job.score === "number" ? job.score : null;
      const cls = scoreClass(score, job.risk_level);
      return `<tr data-id="${escapeAttr(job.id)}" class="${job.id === state.selectedJobId ? "selected" : ""}">
        <td class="role-cell"><strong>${escapeHtml(job.title)}</strong><span>${escapeHtml(job.location)}${job.remote ? " · Remote" : ""}</span></td>
        <td class="company-cell"><strong>${escapeHtml(job.company)}</strong><span>${job.remote ? "Remote" : escapeHtml(job.employment_type || "-")}</span></td>
        <td>${sourcePills(job)}</td>
        <td><span class="${cls}">${score === null ? "-" : Math.round(score * 100) + "%"}</span></td>
        <td>${job.status ? `<span class="status-pill">${escapeHtml(job.status)}</span>` : "-"}</td></tr>`;
    })
    .join("");
  els.jobsBody.querySelectorAll("tr[data-id]").forEach((row) =>
    row.addEventListener("click", () => {
      state.selectedJobId = row.dataset.id;
      renderJobs();
      renderDetail();
      renderLetter();
    })
  );
}

function renderDetail() {
  const job = selectedJob();
  if (!job) {
    els.detailTitle.textContent = "Details";
    els.jobLink.style.visibility = "hidden";
    els.jobDetail.className = "detail-body empty-detail";
    els.jobDetail.textContent = "Keine Auswahl";
    return;
  }
  els.detailTitle.textContent = job.title;
  els.jobLink.href = job.url;
  els.jobLink.style.visibility = "visible";
  els.jobDetail.className = "detail-body";
  els.jobDetail.innerHTML = `
    <div>
      <h3>${escapeHtml(job.company)}</h3>
      <div class="detail-meta">
        <span>${escapeHtml(job.location)}</span>
        <span>${escapeHtml(job.source_label || job.source)}</span>
        ${job.remote ? "<span>Remote</span>" : ""}
        ${job.employment_type ? `<span>${escapeHtml(job.employment_type)}</span>` : ""}
      </div>
    </div>
    <div class="score-main">
      <div>
        <h3>Score</h3>
        <p class="score-explain">${escapeHtml(job.score_explanation || "-")}</p>
      </div>
      <span class="${scoreClass(typeof job.score === "number" ? job.score : null, job.risk_level)}">${typeof job.score === "number" ? Math.round(job.score * 100) + "%" : "-"}</span>
    </div>
    <div><h3>Score-Aufschlüsselung</h3>${scoreBreakdown(job.score_components || [])}</div>
    <div><h3>Ghost-Job-Check</h3>${riskBlock(job)}</div>
    <div><h3>Matcher-Begründung</h3><p>${escapeHtml(job.rationale || "-")}</p></div>
    <div><h3>Anforderungen</h3><div class="skill-list">${pillList(job.requirements)}</div></div>
    <div><h3>Passende Skills</h3><div class="skill-list">${pillList(job.matched_skills)}</div></div>
    <div><h3>Fehlende Skills</h3><div class="skill-list">${pillList(job.missing_skills, "missing")}</div></div>
    <div><h3>Vollständige Beschreibung</h3><p class="job-description">${escapeHtml(job.description || "-")}</p></div>`;
}

function renderLetter() {
  const job = selectedJob();
  const app = job ? state.applications.find((a) => a.job_id === job.id) : null;
  syncStatusControls(app);
  if (!app) {
    els.letterBody.textContent = "Noch kein Entwurf.";
    return;
  }
  const checks = Object.entries(app.quality_checks || {})
    .map(([key, ok]) => `${ok ? "OK" : "WARN"} ${key}`)
    .join("\n");
  els.letterBody.textContent = checks
    ? `${app.cover_letter_md}\n\n---\nQualitätschecks\n${checks}`
    : app.cover_letter_md;
}

function syncStatusControls(app) {
  const hasApp = Boolean(app);
  if (els.statusSelect) {
    els.statusSelect.disabled = !hasApp;
    els.statusSelect.value = app?.status || "draft";
  }
  if (els.notesInput) {
    els.notesInput.disabled = !hasApp;
    els.notesInput.value = app?.notes || "";
  }
  if (els.saveStatusBtn) {
    els.saveStatusBtn.disabled = !hasApp;
  }
  if (els.sendEmailBtn) {
    els.sendEmailBtn.disabled = !hasApp;
  }
}

function selectedJob() {
  return state.jobs.find((j) => j.id === state.selectedJobId) || null;
}

function scoreClass(score, riskLevel) {
  if (riskLevel === "high") return "score-pill danger";
  if (score === null || score === undefined) return "score-pill neutral";
  if (score >= 0.75) return "score-pill";
  if (score >= 0.5) return "score-pill mid";
  return "score-pill low";
}

function sourcePills(job) {
  const source = escapeHtml(job.source_label || job.source || "-");
  const risk = riskLabel(job.risk_level);
  return `<div class="source-stack">
    <span class="source-pill">${source}</span>
    <span class="risk-pill ${escapeAttr(job.risk_level || "low")}">${risk}</span>
  </div>`;
}

function riskLabel(level) {
  if (level === "high") return "Risiko hoch";
  if (level === "medium") return "Risiko mittel";
  return "Risiko niedrig";
}

function scoreBreakdown(components) {
  if (!components.length) return '<span class="empty">Noch keine Rubrikdaten.</span>';
  return `<div class="score-breakdown">${components
    .map((item) => {
      const pct = Math.max(0, Math.min(100, (Number(item.score || 0) / 5) * 100));
      return `<div class="score-row">
        <div class="score-row-head">
          <strong>${escapeHtml(item.label || item.key)}</strong>
          <span>${Number(item.score || 0)}/5 · ${Number(item.weight || 0)}%</span>
        </div>
        <div class="score-bar"><span style="width: ${pct}%"></span></div>
        <p>${escapeHtml(item.evidence || "")}</p>
      </div>`;
    })
    .join("")}</div>`;
}

function riskBlock(job) {
  const flags = job.risk_flags || [];
  const level = job.risk_level || "low";
  const summary = flags.length
    ? flags.map((flag) => `<li>${escapeHtml(flag)}</li>`).join("")
    : "<li>Keine starken Ghost-Job- oder Scam-Signale erkannt.</li>";
  return `<div class="risk-box ${escapeAttr(level)}">
    <div class="risk-head">
      <span class="risk-pill ${escapeAttr(level)}">${riskLabel(level)}</span>
      <strong>${escapeHtml(recommendationLabel(job.recommendation))}</strong>
    </div>
    <ul>${summary}</ul>
  </div>`;
}

function recommendationLabel(value) {
  if (value === "strong") return "Sehr gute Priorität";
  if (value === "good") return "Gute Priorität";
  if (value === "skip") return "Nicht priorisieren";
  return "Manuell prüfen";
}

function pillList(values, modifier = "") {
  if (!values || !values.length) return '<span class="empty">-</span>';
  return values.map((v) => `<span class="skill-pill ${modifier}">${escapeHtml(v)}</span>`).join("");
}

async function copyLetter() {
  try {
    await navigator.clipboard.writeText(els.letterBody.textContent || "");
    els.statusText.textContent = "Kopiert";
  } catch {
    els.statusText.textContent = "Kopieren nicht möglich";
  }
}

async function saveStatus() {
  const job = selectedJob();
  if (!job) return;
  setBusy(true);
  try {
    const res = await fetch("/api/update-status", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({
        db_path: state.dbPath || els.dbPathInput.value,
        job_id: job.id,
        status: els.statusSelect.value,
        notes: els.notesInput.value,
      }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Status konnte nicht gespeichert werden");
    state.applications = data.applications || state.applications;
    const updated = data.status || {};
    state.jobs = state.jobs.map((item) =>
      item.id === job.id ? { ...item, status: updated.status || item.status } : item
    );
    els.statusText.textContent = "Status gespeichert";
    renderJobs();
    renderDetail();
    renderLetter();
  } catch (err) {
    els.statusText.innerHTML = `<span class="toast">${escapeHtml(err.message)}</span>`;
  } finally {
    setBusy(false);
  }
}

async function sendApplicationEmail() {
  const job = selectedJob();
  if (!job) return;
  setBusy(true);
  try {
    const res = await fetch("/api/send-application-email", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({
        db_path: state.dbPath || els.dbPathInput.value,
        job_id: job.id,
        recipient: els.emailRecipientInput ? els.emailRecipientInput.value : "",
      }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "E-Mail konnte nicht gesendet werden");
    state.applications = data.applications || state.applications;
    const updated = data.status || {};
    state.jobs = state.jobs.map((item) =>
      item.id === job.id ? { ...item, status: updated.status || item.status } : item
    );
    const email = data.email || {};
    els.statusText.textContent = email.dry_run
      ? `Dry-run vorbereitet: ${email.recipient}`
      : `E-Mail gesendet: ${email.recipient}`;
    renderJobs();
    renderDetail();
    renderLetter();
  } catch (err) {
    els.statusText.innerHTML = `<span class="toast">${escapeHtml(err.message)}</span>`;
  } finally {
    setBusy(false);
  }
}

async function syncInboxStatus() {
  setBusy(true);
  try {
    const res = await fetch("/api/sync-email-status", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({
        db_path: state.dbPath || els.dbPathInput.value,
      }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Inbox-Sync fehlgeschlagen");
    state.applications = data.applications || state.applications;
    const updates = data.sync?.updates || [];
    const byJob = new Map(updates.map((item) => [item.job_id, item.stage]));
    state.jobs = state.jobs.map((item) =>
      byJob.has(item.id) ? { ...item, status: byJob.get(item.id) } : item
    );
    const mode = data.sync?.dry_run ? "Dry-run" : "Aktualisiert";
    els.statusText.textContent = `${mode}: ${updates.length} E-Mail-Status erkannt`;
    renderJobs();
    renderDetail();
    renderLetter();
  } catch (err) {
    els.statusText.innerHTML = `<span class="toast">${escapeHtml(err.message)}</span>`;
  } finally {
    setBusy(false);
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
function escapeAttr(value) {
  return escapeHtml(value);
}

if (els.runBtn) els.runBtn.addEventListener("click", runPipeline);
if (els.demoProfileBtn) els.demoProfileBtn.addEventListener("click", loadDemoProfile);
if (els.goPipelineBtn) els.goPipelineBtn.addEventListener("click", () => { location.hash = "#/pipeline"; });
if (els.copyBtn) els.copyBtn.addEventListener("click", copyLetter);
if (els.saveStatusBtn) els.saveStatusBtn.addEventListener("click", saveStatus);
if (els.sendEmailBtn) els.sendEmailBtn.addEventListener("click", sendApplicationEmail);
if (els.syncInboxBtn) els.syncInboxBtn.addEventListener("click", syncInboxStatus);
if (els.authForm) els.authForm.addEventListener("submit", submitAuth);
if (els.loginTabBtn) els.loginTabBtn.addEventListener("click", () => setAuthMode("login"));
if (els.registerTabBtn) els.registerTabBtn.addEventListener("click", () => setAuthMode("register"));
if (els.logoutBtn) els.logoutBtn.addEventListener("click", logout);
if (els.draftAllInput) {
  els.draftAllInput.addEventListener("change", () => {
    els.thresholdInput.disabled = els.draftAllInput.checked;
  });
}
els.demoModeBtn.addEventListener("click", () => setMode(true));
els.demoModeBtn.addEventListener("click", () => loadDemoProfile());
els.liveModeBtn.addEventListener("click", () => setMode(false));

async function loadConfig() {
  try {
    const res = await fetch("/api/config");
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "config");
    state.config = data;
    if (els.providerBadge) {
      els.providerBadge.textContent = `${data.llm_provider} / ${data.llm_model}`;
      els.providerBadge.title = data.embedding_model
        ? `Embedding: ${data.embedding_model}`
        : "Embedding: lokaler Hash-Fallback";
      els.providerBadge.classList.add("ok");
    }
    if (els.llmInput) els.llmInput.checked = Boolean(data.llm_agents_default);
    if (els.chromaInput) els.chromaInput.checked = Boolean(data.chroma_default);
    if (els.emailRecipientInput && data.email_demo_recipient) {
      els.emailRecipientInput.value = data.email_demo_recipient;
    }
    if (els.sendEmailBtn) {
      els.sendEmailBtn.title = data.email_dry_run
        ? "Dry-run: Es wird keine echte E-Mail gesendet."
        : "Sendet die Bewerbung per SMTP und markiert sie als eingereicht.";
    }
    if (els.syncInboxBtn) {
      state.emailSyncReady = Boolean(data.email_sync_ready);
      els.syncInboxBtn.title = data.email_sync_dry_run
        ? "Dry-run: Inbox wird gelesen, Statusupdates werden nur vorgeschlagen."
        : "Liest die Inbox und aktualisiert erkannte Bewerbungsstatus.";
      els.syncInboxBtn.disabled = !state.emailSyncReady;
    }
  } catch {
    if (els.providerBadge) {
      els.providerBadge.textContent = "lokal";
      els.providerBadge.classList.add("off");
    }
  }
}

setAuthMode("login");
showAuth();
checkAuth();
