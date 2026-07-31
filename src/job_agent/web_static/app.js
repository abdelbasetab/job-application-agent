"use strict";

const state = {
  demo: true,
  jobs: [],
  applications: [],
  selectedJobId: null,
  dbPath: null,
  profileReady: false,
  profileSource: "none",
  cvDirty: false,
  config: {},
  pipelineRunning: false,
  emailSyncReady: false,
  authenticated: false,
  registrationEnabled: false,
  authMode: "login",
  user: null,
  csrfToken: null,
  followUps: [],
  emailIdentity: null,
  inboxItems: [],
  jdInboxId: "",
  autopilotSchedule: null,
};
let lastProfileName = "";
let appBooted = false;

const $ = (sel) => document.querySelector(sel);
const el = (id) => document.getElementById(id);

function jsonHeaders() {
  const h = { "Content-Type": "application/json" };
  if (state.csrfToken) h["X-CSRF-Token"] = state.csrfToken;
  return h;
}

const els = {
  authView: el("authView"),
  appShell: el("appShell"),
  authForm: el("authForm"),
  loginTabBtn: el("loginTabBtn"),
  registerTabBtn: el("registerTabBtn"),
  authEmailInput: el("authEmailInput"),
  authPasswordInput: el("authPasswordInput"),
  authConfirmField: el("authConfirmField"),
  authConfirmInput: el("authConfirmInput"),
  authSubmitBtn: el("authSubmitBtn"),
  authMessage: el("authMessage"),
  themeToggle: el("themeToggle"),
  viewTitle: el("viewTitle"),
  statusText: el("statusText"),
  globalProgress: el("globalProgress"),
  progressLabel: el("progressLabel"),
  progressPct: el("progressPct"),
  progressFill: el("progressFill"),
  agentProgress: el("agentProgress"),
  providerBadge: el("providerBadge"),
  currentUserLabel: el("currentUserLabel"),
  logoutBtn: el("logoutBtn"),
  // profil
  dropzone: el("dropzone"),
  cvFile: el("cvFile"),
  cvFileStatus: el("cvFileStatus"),
  cvInput: el("cvInput"),
  buildProfileBtn: el("buildProfileBtn"),
  demoProfileBtn: el("demoProfileBtn"),
  goPipelineBtn: el("goPipelineBtn"),
  profilePanel: el("profilePanel"),
  profileStatus: el("profileStatus"),
  emailConnectionBadge: el("emailConnectionBadge"),
  emailIdentityPanel: el("emailIdentityPanel"),
  emailAddressInput: el("emailAddressInput"),
  emailFromInput: el("emailFromInput"),
  reviewEmailInput: el("reviewEmailInput"),
  smtpHostInput: el("smtpHostInput"),
  smtpPortInput: el("smtpPortInput"),
  smtpUserInput: el("smtpUserInput"),
  smtpPasswordInput: el("smtpPasswordInput"),
  imapHostInput: el("imapHostInput"),
  imapPortInput: el("imapPortInput"),
  imapUserInput: el("imapUserInput"),
  imapPasswordInput: el("imapPasswordInput"),
  imapFolderInput: el("imapFolderInput"),
  emailUseTlsInput: el("emailUseTlsInput"),
  emailDryRunInput: el("emailDryRunInput"),
  emailSyncDryRunInput: el("emailSyncDryRunInput"),
  emailAutoFollowUpInput: el("emailAutoFollowUpInput"),
  fillEmailFromProfileBtn: el("fillEmailFromProfileBtn"),
  saveEmailCredentialsBtn: el("saveEmailCredentialsBtn"),
  testEmailConnectionBtn: el("testEmailConnectionBtn"),
  emailConnectionTestPanel: el("emailConnectionTestPanel"),
  clearEmailCredentialsBtn: el("clearEmailCredentialsBtn"),
  connectGoogleBtn: el("connectGoogleBtn"),
  connectMicrosoftBtn: el("connectMicrosoftBtn"),
  // suche
  queryInput: el("queryInput"),
  querySuggestions: el("querySuggestions"),
  limitInput: el("limitInput"),
  thresholdInput: el("thresholdInput"),
  thresholdOut: el("thresholdOut"),
  demoModeBtn: el("demoModeBtn"),
  liveModeBtn: el("liveModeBtn"),
  llmInput: el("llmInput"),
  chromaInput: el("chromaInput"),
  draftAllInput: el("draftAllInput"),
  resetInput: el("resetInput"),
  dbPathInput: el("dbPathInput"),
  runBtn: el("runBtn"),
  activeProfile: el("activeProfile"),
  searchProfileFact: el("searchProfileFact"),
  sourceFact: el("sourceFact"),
  searchStateFact: el("searchStateFact"),
  jobsMetric: el("jobsMetric"),
  matchesMetric: el("matchesMetric"),
  draftsMetric: el("draftsMetric"),
  trackedMetric: el("trackedMetric"),
  dbPathLabel: el("dbPathLabel"),
  jobsBody: el("jobsBody"),
  detailTitle: el("detailTitle"),
  jobLink: el("jobLink"),
  livenessBadge: el("livenessBadge"),
  checkLivenessBtn: el("checkLivenessBtn"),
  jobDetail: el("jobDetail"),
  letterBody: el("letterBody"),
  generateDraftBtn: el("generateDraftBtn"),
  copyBtn: el("copyBtn"),
  statusSelect: el("statusSelect"),
  notesInput: el("notesInput"),
  recipientHint: el("recipientHint"),
  attachCvInput: el("attachCvInput"),
  sendEmailBtn: el("sendEmailBtn"),
  exportBtn: el("exportBtn"),
  downloadLink: el("downloadLink"),
  syncInboxBtn: el("syncInboxBtn"),
  saveStatusBtn: el("saveStatusBtn"),
  trackerBody: el("trackerBody"),
  // cv-check
  reviewCvBtn: el("reviewCvBtn"),
  cvCheckLlmInput: el("cvCheckLlmInput"),
  cvCheckPanel: el("cvCheckPanel"),
  // follow-ups
  followupsBadge: el("followupsBadge"),
  followupDaysInput: el("followupDaysInput"),
  refreshFollowupsBtn: el("refreshFollowupsBtn"),
  syncInboxFollowupsBtn: el("syncInboxFollowupsBtn"),
  runEmailAutopilotBtn: el("runEmailAutopilotBtn"),
  autopilotIntervalInput: el("autopilotIntervalInput"),
  startAutopilotScheduleBtn: el("startAutopilotScheduleBtn"),
  stopAutopilotScheduleBtn: el("stopAutopilotScheduleBtn"),
  emailAuditPanel: el("emailAuditPanel"),
  autopilotSchedulePanel: el("autopilotSchedulePanel"),
  followupsBody: el("followupsBody"),
  autopilotStatusChip: el("autopilotStatusChip"),
  // inbox
  inboxBadge: el("inboxBadge"),
  inboxUrlInput: el("inboxUrlInput"),
  inboxNoteInput: el("inboxNoteInput"),
  addInboxBtn: el("addInboxBtn"),
  inboxBody: el("inboxBody"),
  jdLlmInput: el("jdLlmInput"),
  jdTitleInput: el("jdTitleInput"),
  jdCompanyInput: el("jdCompanyInput"),
  jdLocationInput: el("jdLocationInput"),
  jdUrlInput: el("jdUrlInput"),
  jdTextInput: el("jdTextInput"),
  evaluateJdBtn: el("evaluateJdBtn"),
  jdEvalResult: el("jdEvalResult"),
  // patterns / detail extras
  patternsPanel: el("patternsPanel"),
  refreshPatternsBtn: el("refreshPatternsBtn"),
  reportBtn: el("reportBtn"),
  interviewPrepBtn: el("interviewPrepBtn"),
  interviewPrepPanel: el("interviewPrepPanel"),
  currentPasswordInput: el("currentPasswordInput"),
  newPasswordInput: el("newPasswordInput"),
  changePasswordBtn: el("changePasswordBtn"),
  deletePasswordInput: el("deletePasswordInput"),
  deleteConfirmInput: el("deleteConfirmInput"),
  deleteAccountBtn: el("deleteAccountBtn"),
};

/* ----------------------------- toasts ------------------------------ */
function showToast(message, type = "error") {
  let host = document.getElementById("toastHost");
  if (!host) {
    host = document.createElement("div");
    host.id = "toastHost";
    host.className = "toast-host";
    document.body.appendChild(host);
  }
  const node = document.createElement("div");
  node.className = `toast-item ${type}`;
  node.textContent = message;
  host.appendChild(node);
  setTimeout(() => {
    node.classList.add("hide");
    setTimeout(() => node.remove(), 350);
  }, 4500);
  if (type === "error" && els.statusText) els.statusText.textContent = "Fehler";
  if (type === "ok" && els.statusText) els.statusText.textContent = message;
}

const AGENT_STEPS = [
  { key: "scout", idle: "Wartet", active: "Jobs suchen", done: "Jobs gefunden" },
  { key: "matcher", idle: "Wartet", active: "Bewerten", done: "Bewertet" },
  { key: "writer", idle: "Wartet", active: "Anschreiben", done: "Entwürfe erstellt" },
  { key: "tracker", idle: "Wartet", active: "Speichern", done: "Gespeichert" },
];
const VIEW_TITLES = {
  profil: "Profil",
  suche: "Jobs finden",
  inbox: "Portal- & URL-Inbox",
  bewerbungen: "Bewerbungen",
  followups: "Follow-up-Radar",
  einstellungen: "Einstellungen",
};

/* ----------------------------- theme ------------------------------- */
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  try { localStorage.setItem("ja-theme", theme); } catch {}
}
function initTheme() {
  let theme = null;
  try { theme = localStorage.getItem("ja-theme"); } catch {}
  if (!theme) {
    theme = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  applyTheme(theme);
}
if (els.themeToggle) {
  els.themeToggle.addEventListener("click", () => {
    const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    applyTheme(next);
  });
}

/* ----------------------------- auth -------------------------------- */
function setAuthMode(mode) {
  if (mode === "register" && !state.registrationEnabled) mode = "login";
  state.authMode = mode;
  const register = mode === "register";
  els.loginTabBtn.classList.toggle("is-active", !register);
  els.registerTabBtn.classList.toggle("is-active", register);
  els.authConfirmField.classList.toggle("is-hidden", !register);
  els.authPasswordInput.autocomplete = register ? "new-password" : "current-password";
  els.authSubmitBtn.textContent = register ? "Account erstellen" : "Einloggen";
  els.authMessage.textContent = "";
}

async function loadAuthConfig() {
  try {
    const res = await fetch("/api/auth/config");
    const data = await res.json();
    state.registrationEnabled = Boolean(res.ok && data.registration_enabled);
  } catch {
    state.registrationEnabled = false;
  }
  if (els.registerTabBtn) {
    els.registerTabBtn.classList.toggle("is-hidden", !state.registrationEnabled);
  }
  if (!state.registrationEnabled && state.authMode === "register") setAuthMode("login");
}

function showAuthenticated(user) {
  state.authenticated = true;
  state.user = user;
  els.authView.classList.add("is-hidden");
  els.appShell.classList.remove("is-hidden");
  els.currentUserLabel.textContent = user?.email || "";
}

function showAuth() {
  state.authenticated = false;
  state.user = null;
  els.appShell.classList.add("is-hidden");
  els.authView.classList.remove("is-hidden");
  els.currentUserLabel.textContent = "";
}

async function checkAuth() {
  await loadAuthConfig();
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
    // stay on auth view
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
      headers: { "Content-Type": "application/json" },
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
  updateActiveProfile("none");
  syncStatusControls(null);
  await loadConfig();
  await loadState({ silent: true });
  route();
  refreshFollowUpBadge();
  loadInboxItems();
  appBooted = true;
}

/* ----------------------------- routing ----------------------------- */
const ROUTES = ["profil", "suche", "inbox", "bewerbungen", "followups", "einstellungen"];
function route() {
  const pathRoute = location.pathname.replace(/^\/+/, "");
  let r = location.hash.replace(/^#\/?/, "") || (ROUTES.includes(pathRoute) ? pathRoute : "profil");
  if (!ROUTES.includes(r)) r = "profil";
  document.querySelectorAll(".view").forEach((v) => v.classList.add("is-hidden"));
  const view = el("view-" + r);
  if (view) view.classList.remove("is-hidden");
  document.querySelectorAll(".side-link").forEach((b) => b.classList.toggle("is-active", b.dataset.route === r));
  if (els.viewTitle) els.viewTitle.textContent = VIEW_TITLES[r] || "Job Agent";
  if (!state.pipelineRunning && ["suche", "bewerbungen", "followups"].includes(r)) {
    loadState({ silent: true });
  }
  if (r === "inbox") loadInboxItems();
  if (r === "bewerbungen") { renderTracker(); loadPatterns(); }
  if (r === "followups") { loadFollowUps(); refreshAutopilotSchedule(); }
  if (r === "einstellungen") { loadEmailAudit(); refreshAutopilotSchedule(); }
}
window.addEventListener("hashchange", route);
document.querySelectorAll(".side-link").forEach((b) =>
  b.addEventListener("click", () => { location.hash = "#/" + b.dataset.route; })
);

/* ----------------------------- progress ---------------------------- */
const progress = {
  show(label, pct) {
    els.globalProgress.classList.remove("is-hidden", "complete", "failed");
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
    els.globalProgress.classList.remove("is-hidden", "indeterminate", "complete", "failed");
    els.progressFill.style.width = Math.max(0, Math.min(100, pct)) + "%";
    els.progressPct.textContent = Math.round(pct) + "%";
    if (label) els.progressLabel.textContent = label;
    if (state.pipelineRunning) {
      toggleAgentProgress(true);
      renderAgentProgress(label, pct);
    }
  },
  finish(label = "Pipeline abgeschlossen") {
    els.globalProgress.classList.remove("is-hidden", "indeterminate", "failed");
    this.set(100, label);
    els.globalProgress.classList.add("complete");
    renderAgentProgress("Fertig", 100);
  },
  fail(label) {
    els.globalProgress.classList.remove("is-hidden", "indeterminate", "complete");
    toggleAgentProgress(true);
    els.globalProgress.classList.add("failed");
    els.progressLabel.textContent = label;
    els.progressPct.textContent = "";
    markAgentProgressFailed();
  },
  hide() {
    els.globalProgress.classList.add("is-hidden");
    els.globalProgress.classList.remove("indeterminate", "complete", "failed");
    els.progressFill.style.width = "0%";
    toggleAgentProgress(false);
    renderAgentProgress(null, 0);
  },
};

function toggleAgentProgress(visible) {
  if (els.agentProgress) els.agentProgress.classList.toggle("is-hidden", !visible);
}
function renderAgentProgress(stage, pct) {
  if (!els.agentProgress) return;
  const activeIndex = agentIndexFromStage(stage, pct);
  els.agentProgress.querySelectorAll(".agent-node").forEach((node, index) => {
    const meta = AGENT_STEPS[index];
    const label = node.querySelector("small");
    node.classList.remove("active", "done", "failed");
    if (activeIndex === -1) {
      if (label) label.textContent = meta.idle;
      return;
    }
    if (pct >= 100 || index < activeIndex) {
      node.classList.add("done");
      if (label) label.textContent = meta.done;
    } else if (index === activeIndex) {
      node.classList.add("active");
      if (label) label.textContent = meta.active;
    } else if (label) {
      label.textContent = meta.idle;
    }
  });
}
function markAgentProgressFailed() {
  if (!els.agentProgress) return;
  const current = els.agentProgress.querySelector(".agent-node.active");
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
  [
    els.runBtn,
    els.buildProfileBtn,
    els.demoProfileBtn,
    els.generateDraftBtn,
    els.saveStatusBtn,
    els.sendEmailBtn,
    els.saveEmailCredentialsBtn,
    els.testEmailConnectionBtn,
    els.clearEmailCredentialsBtn,
    els.runEmailAutopilotBtn,
    els.connectGoogleBtn,
    els.connectMicrosoftBtn,
    els.startAutopilotScheduleBtn,
    els.stopAutopilotScheduleBtn,
    els.changePasswordBtn,
    els.deleteAccountBtn,
  ].forEach((b) => {
    if (b) b.disabled = busy;
  });
  if (els.syncInboxBtn) els.syncInboxBtn.disabled = busy || !state.emailSyncReady;
  if (els.syncInboxFollowupsBtn) els.syncInboxFollowupsBtn.disabled = busy || !state.emailSyncReady;
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
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); els.cvFile.click(); }
  });
  ["dragover", "dragenter"].forEach((ev) =>
    els.dropzone.addEventListener(ev, (e) => { e.preventDefault(); els.dropzone.classList.add("dragover"); })
  );
  ["dragleave", "drop"].forEach((ev) =>
    els.dropzone.addEventListener(ev, (e) => { e.preventDefault(); els.dropzone.classList.remove("dragover"); })
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
      await loadConfig();
    }
    els.cvFileStatus.textContent = data.source === "cv" ? "✓ Profil aus CV erstellt." : "Demo-Profil angezeigt.";
  } catch (err) {
    els.cvFileStatus.textContent = `Fehler: ${err.message}`;
  } finally {
    progress.hide();
    setBusy(false);
  }
}
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
    await loadConfig();
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
  if (els.activeProfile) els.activeProfile.textContent = label;
  if (els.searchProfileFact) els.searchProfileFact.textContent = compactProfileLabel(source);
  if (els.profileStatus) {
    els.profileStatus.className = `banner ${source === "cv" ? "banner-cv" : "banner-demo"}`;
    els.profileStatus.textContent = label;
  }
  loadSearchSuggestions();
}

/* ------------------- search suggestions from the CV ------------------ */
async function loadSearchSuggestions() {
  if (!els.querySuggestions) return;
  try {
    const res = await fetch("/api/search-suggestions");
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "");
    renderSearchSuggestions(data.suggestions || []);
  } catch {
    renderSearchSuggestions([]);
  }
}

function renderSearchSuggestions(suggestions) {
  const box = els.querySuggestions;
  if (!box) return;
  box.classList.toggle("is-hidden", suggestions.length === 0);
  if (!suggestions.length) {
    box.innerHTML = "";
    return;
  }
  box.innerHTML =
    '<span class="query-suggestions-label">Aus deinem Lebenslauf:</span>' +
    suggestions
      .map(
        (item) =>
          `<button class="query-chip" type="button" title="${escapeAttr(item.reason || "")}" data-query="${escapeAttr(item.query)}">${escapeHtml(item.query)}</button>`
      )
      .join("");
  box.querySelectorAll("[data-query]").forEach((chip) =>
    chip.addEventListener("click", () => {
      if (!els.queryInput) return;
      els.queryInput.value = chip.dataset.query || "";
      markActiveSuggestion();
      els.queryInput.focus();
    })
  );
  markActiveSuggestion();
}

function markActiveSuggestion() {
  const current = (els.queryInput ? els.queryInput.value : "").trim().toLowerCase();
  els.querySuggestions?.querySelectorAll("[data-query]").forEach((chip) =>
    chip.classList.toggle("is-active", (chip.dataset.query || "").toLowerCase() === current)
  );
}
if (els.queryInput) els.queryInput.addEventListener("input", markActiveSuggestion);
function profileLabel(source) {
  if (source === "pending") return "CV importiert, Profil noch nicht erstellt";
  if (source === "none" || !lastProfileName) return "Kein Profil geladen — bitte Lebenslauf importieren (oder Demo laden).";
  const suffix = source === "cv" ? "aus CV" : "Demo";
  return `Aktives Profil: ${lastProfileName} (${suffix})`;
}
function compactProfileLabel(source) {
  if (source === "pending") return "In Arbeit";
  if (source === "none" || !lastProfileName) return "Kein Profil";
  return source === "cv" ? lastProfileName : "Demo";
}

function cleanEmail(value, preferred = "") {
  const text = String(value || "").trim().toLowerCase().replace(/^mailto:/, "").replace(/^[<\s]+|[>\s,;:]+$/g, "");
  const pref = cleanEmailExact(preferred);
  if (pref && text.includes(pref)) return pref;
  const exact = cleanEmailExact(text);
  if (exact) return exact;
  const match = text.match(/[a-z0-9][a-z0-9._%+\-]{0,63}@[a-z0-9][a-z0-9.\-]{0,253}\.[a-z]{2,24}/i);
  return match ? cleanEmailExact(match[0]) : "";
}

function cleanEmailExact(value) {
  const text = String(value || "").trim().toLowerCase().replace(/^mailto:/, "").replace(/^[<\s]+|[>\s,;:]+$/g, "");
  if (!/^[a-z0-9][a-z0-9._%+\-]{0,63}@[a-z0-9][a-z0-9.\-]{0,253}\.[a-z]{2,24}$/i.test(text)) return "";
  const [local, domain] = text.split("@");
  if (!local || !domain || local.startsWith(".") || local.endsWith(".") || local.includes("..")) return "";
  if (domain.startsWith(".") || domain.endsWith(".") || domain.includes("..")) return "";
  if (domain.split(".").some((part) => !part || part.startsWith("-") || part.endsWith("-"))) return "";
  return text;
}

function bestIdentityEmail(identity = state.emailIdentity) {
  if (!identity) return "";
  const account = identity.account || {};
  const login = cleanEmail(identity.login_email || "");
  const candidate = cleanEmail(identity.candidate_email, login);
  if (identity.account_source !== "local") return candidate || login || cleanEmail(identity.profile_email || "");
  return (
    cleanEmail(account.email_address, login) ||
    candidate ||
    login ||
    cleanEmail(identity.profile_email || "")
  );
}

function renderEmailIdentity(identity) {
  state.emailIdentity = identity || null;
  if (!els.emailIdentityPanel || !identity) return;
  const smtpReady = Boolean(identity.smtp_ready);
  const imapReady = Boolean(identity.imap_ready);
  const source = identity.account_source === "local"
    ? "Lokal gespeichert"
    : identity.account_source === "env" ? ".env (CLI)" : "Nicht konfiguriert";
  const badgeClass = smtpReady && imapReady ? "ok" : smtpReady || imapReady ? "warn" : "muted";
  if (els.emailConnectionBadge) {
    els.emailConnectionBadge.className = `email-badge ${badgeClass}`;
    els.emailConnectionBadge.textContent = smtpReady && imapReady ? "Verbunden" : smtpReady ? "Versand bereit" : imapReady ? "Inbox bereit" : "Nicht verbunden";
  }
  const warnings = (identity.warnings || []).map((w) => `<li>${escapeHtml(w)}</li>`).join("");
  els.emailIdentityPanel.innerHTML = `
    <div class="email-status-grid">
      <div><span>Profil-Mail</span><strong>${escapeHtml(identity.profile_email || "-")}</strong></div>
      <div><span>Absender</span><strong>${escapeHtml(identity.sender || "-")}</strong></div>
      <div><span>SMTP</span><strong class="${smtpReady ? "ok" : "muted"}">${smtpReady ? "bereit" : "fehlt"}</strong></div>
      <div><span>IMAP</span><strong class="${imapReady ? "ok" : "muted"}">${imapReady ? "bereit" : "fehlt"}</strong></div>
    </div>
    <div class="email-flags">
      <span>${escapeHtml(source)}</span>
      <span>${identity.email_dry_run ? "Versand: Dry-run" : "Versand: echt"}</span>
      <span>${identity.email_sync_dry_run ? "Inbox: Vorschlaege" : "Inbox: schreibt Status"}</span>
      <span>${identity.auto_follow_up_send ? "Auto-Follow-up: senden erlaubt" : "Auto-Follow-up: vorbereitet nur"}</span>
    </div>
    ${warnings ? `<ul class="email-warnings">${warnings}</ul>` : ""}`;
  fillEmailCredentialForm(identity);
}

function fillEmailCredentialForm(identity = state.emailIdentity) {
  if (!identity) return;
  const account = identity.account || {};
  const email = bestIdentityEmail(identity);
  const useAccountEmails = identity.account_source === "local";
  if (els.emailAddressInput) els.emailAddressInput.value = email;
  if (els.emailFromInput) els.emailFromInput.value = cleanEmail(useAccountEmails ? account.email_from : "", email) || email;
  if (els.reviewEmailInput) els.reviewEmailInput.value = account.review_email || "";
  if (els.smtpHostInput) els.smtpHostInput.value = account.smtp_host || "";
  if (els.smtpPortInput) els.smtpPortInput.value = account.smtp_port || 587;
  if (els.smtpUserInput) els.smtpUserInput.value = cleanEmail(useAccountEmails ? account.smtp_user : "", email) || email;
  if (els.smtpPasswordInput) els.smtpPasswordInput.value = "";
  if (els.imapHostInput) els.imapHostInput.value = account.imap_host || "";
  if (els.imapPortInput) els.imapPortInput.value = account.imap_port || 993;
  if (els.imapUserInput) els.imapUserInput.value = cleanEmail(useAccountEmails ? account.imap_user : "", email) || email;
  if (els.imapPasswordInput) els.imapPasswordInput.value = "";
  if (els.imapFolderInput) els.imapFolderInput.value = account.imap_folder || "INBOX";
  if (els.emailUseTlsInput) els.emailUseTlsInput.checked = account.use_tls !== false;
  if (els.emailDryRunInput) els.emailDryRunInput.checked = account.dry_run !== false;
  if (els.emailSyncDryRunInput) els.emailSyncDryRunInput.checked = account.sync_dry_run !== false;
  if (els.emailAutoFollowUpInput) els.emailAutoFollowUpInput.checked = account.auto_follow_up_send === true;
}

function fillEmailFromProfile() {
  const identity = state.emailIdentity || {};
  const email = bestIdentityEmail(identity) || cleanEmail(identity.profile_email || "");
  if (!email) return;
  [els.emailAddressInput, els.emailFromInput, els.smtpUserInput, els.imapUserInput].forEach((input) => {
    if (input) input.value = email;
  });
}

async function saveEmailCredentials() {
  const realSend = els.emailDryRunInput && !els.emailDryRunInput.checked;
  const realSync = els.emailSyncDryRunInput && !els.emailSyncDryRunInput.checked;
  if ((realSend || realSync) && !window.confirm(
    "Du deaktivierst mindestens einen Dry-run. Dadurch können echte E-Mails gesendet oder Tracker-Status automatisch geändert werden. Fortfahren?"
  )) return;
  setBusy(true);
  try {
    const fallbackEmail = bestIdentityEmail();
    const body = {
      email_address: els.emailAddressInput ? cleanEmail(els.emailAddressInput.value, fallbackEmail) : "",
      email_from: els.emailFromInput ? cleanEmail(els.emailFromInput.value, fallbackEmail) : "",
      review_email: els.reviewEmailInput ? cleanEmail(els.reviewEmailInput.value) : "",
      smtp_host: els.smtpHostInput ? els.smtpHostInput.value : "",
      smtp_port: els.smtpPortInput ? Number(els.smtpPortInput.value || 587) : 587,
      smtp_user: els.smtpUserInput ? cleanEmail(els.smtpUserInput.value, fallbackEmail) : "",
      smtp_password: els.smtpPasswordInput ? els.smtpPasswordInput.value : "",
      imap_host: els.imapHostInput ? els.imapHostInput.value : "",
      imap_port: els.imapPortInput ? Number(els.imapPortInput.value || 993) : 993,
      imap_user: els.imapUserInput ? cleanEmail(els.imapUserInput.value, fallbackEmail) : "",
      imap_password: els.imapPasswordInput ? els.imapPasswordInput.value : "",
      imap_folder: els.imapFolderInput ? els.imapFolderInput.value : "INBOX",
      use_tls: els.emailUseTlsInput ? els.emailUseTlsInput.checked : true,
      dry_run: els.emailDryRunInput ? els.emailDryRunInput.checked : true,
      sync_dry_run: els.emailSyncDryRunInput ? els.emailSyncDryRunInput.checked : true,
      auto_follow_up_send: els.emailAutoFollowUpInput ? els.emailAutoFollowUpInput.checked : false,
    };
    const res = await fetch("/api/email-credentials", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "E-Mail-Verbindung konnte nicht gespeichert werden");
    renderEmailIdentity(data.email_identity);
    await loadConfig();
    els.statusText.textContent = "E-Mail-Verbindung gespeichert";
  } catch (err) {
    showToast(err.message);
  } finally {
    setBusy(false);
  }
}

function renderEmailConnectionTest(data) {
  if (!els.emailConnectionTestPanel) return;
  const rows = ["smtp", "imap"]
    .filter((key) => data && data[key])
    .map((key) => {
      const item = data[key] || {};
      const cls = item.ok ? "ok" : item.configured ? "fail" : "warn";
      const label = key.toUpperCase();
      const target = item.host ? `${item.host}:${item.port || ""}` : "nicht konfiguriert";
      return `<div class="email-test-row ${cls}">
        <span>${label}</span>
        <strong>${item.ok ? "Verbunden" : item.configured ? "Fehler" : "Fehlt"}</strong>
        <small>${escapeHtml(target)}${item.user ? ` - ${escapeHtml(item.user)}` : ""}</small>
        <p>${escapeHtml(item.message || "")}</p>
      </div>`;
    })
    .join("");
  els.emailConnectionTestPanel.classList.remove("is-hidden");
  els.emailConnectionTestPanel.innerHTML = `
    <div class="email-test-head">
      <strong>Verbindungstest</strong>
      <span>${escapeHtml(data.account_source || "")}</span>
    </div>
    <div class="email-test-list">${rows || '<div class="empty">Kein Test ausgefuehrt.</div>'}</div>`;
}

async function testEmailConnection() {
  setBusy(true);
  if (els.emailConnectionTestPanel) {
    els.emailConnectionTestPanel.classList.remove("is-hidden");
    els.emailConnectionTestPanel.innerHTML = '<div class="empty">Teste SMTP und IMAP ...</div>';
  }
  try {
    const res = await fetch("/api/test-email-connection", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ kind: "both" }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Verbindungstest fehlgeschlagen");
    renderEmailConnectionTest(data);
    if (data.email_identity) renderEmailIdentity(data.email_identity);
    const smtpOk = Boolean(data.smtp && data.smtp.ok);
    const imapOk = Boolean(data.imap && data.imap.ok);
    els.statusText.textContent = smtpOk && imapOk
      ? "SMTP und IMAP verbunden"
      : smtpOk
        ? "SMTP verbunden, IMAP pruefen"
        : imapOk
          ? "IMAP verbunden, SMTP pruefen"
          : "E-Mail-Verbindung nicht erfolgreich";
  } catch (err) {
    if (els.emailConnectionTestPanel) {
      els.emailConnectionTestPanel.classList.remove("is-hidden");
      els.emailConnectionTestPanel.innerHTML = `<div class="email-test-row fail"><strong>Fehler</strong><p>${escapeHtml(err.message)}</p></div>`;
    }
    showToast(err.message);
  } finally {
    setBusy(false);
  }
}

async function clearEmailCredentials() {
  setBusy(true);
  try {
    const res = await fetch("/api/email-credentials", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ action: "clear" }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Lokale E-Mail-Daten konnten nicht entfernt werden");
    renderEmailIdentity(data.email_identity);
    await loadConfig();
    els.statusText.textContent = "Lokale E-Mail-Daten entfernt";
  } catch (err) {
    showToast(err.message);
  } finally {
    setBusy(false);
  }
}

function renderOAuthProviders(providers) {
  const byKey = new Map((providers || []).map((p) => [p.key, p]));
  [
    [els.connectGoogleBtn, byKey.get("google")],
    [els.connectMicrosoftBtn, byKey.get("microsoft")],
  ].forEach(([btn, provider]) => {
    if (!btn) return;
    const configured = Boolean(provider && provider.configured);
    btn.disabled = !configured;
    btn.title = configured
      ? `${provider.label} OAuth starten`
      : "OAuth Client-ID/Secret fehlen in .env";
  });
}

async function connectOAuthProvider(provider) {
  setBusy(true);
  try {
    const identity = state.emailIdentity || {};
    const res = await fetch("/api/oauth/email/start", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({
        provider,
        email: identity.profile_email || identity.login_email || "",
      }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "OAuth konnte nicht gestartet werden");
    window.location.href = data.authorization_url;
  } catch (err) {
    showToast(err.message);
    setBusy(false);
  }
}

function renderAutopilotSchedule(schedule) {
  state.autopilotSchedule = schedule || null;
  renderAutopilotChip(schedule);
  if (!els.autopilotSchedulePanel) return;
  if (!schedule || !schedule.enabled) {
    els.autopilotSchedulePanel.classList.add("is-hidden");
    return;
  }
  els.autopilotSchedulePanel.classList.remove("is-hidden");
  const status = schedule.running ? "läuft gerade" : "wartet";
  els.autopilotSchedulePanel.innerHTML = `
    <div class="email-audit-head"><strong>Autopilot-Plan</strong><span>${escapeHtml(status)}</span></div>
    <div class="email-audit-list">
      <div class="email-audit-row"><span>Intervall</span><strong>${Number(schedule.interval_minutes || 0)} Minuten</strong><small>${escapeHtml(schedule.last_error || "OK")}</small></div>
      <div class="email-audit-row"><span>Letzter Lauf</span><strong>${fmtDateTime(schedule.last_run)}</strong><small>Nächster: ${fmtDateTime(schedule.next_run)}</small></div>
    </div>`;
}

function renderAutopilotChip(schedule) {
  if (!els.autopilotStatusChip) return;
  const identity = state.config.email_identity || {};
  const autoSend = Boolean(identity.auto_follow_up_send) && identity.email_dry_run === false;
  if (schedule && schedule.enabled) {
    els.autopilotStatusChip.textContent =
      `Autopilot: alle ${Number(schedule.interval_minutes || 0)} min · ` +
      (autoSend ? "Versand aktiv" : "nur vorbereiten");
    els.autopilotStatusChip.className = autoSend ? "chip risk medium" : "chip score mid";
  } else {
    els.autopilotStatusChip.textContent = "Autopilot: aus";
    els.autopilotStatusChip.className = "chip status";
  }
}

async function refreshAutopilotSchedule() {
  if (!els.autopilotSchedulePanel) return;
  try {
    const res = await fetch("/api/email-autopilot-schedule");
    const data = await res.json();
    if (res.ok && data.ok) renderAutopilotSchedule(data);
  } catch {
    /* schedule status is best-effort */
  }
}

async function configureAutopilotSchedule(action) {
  setBusy(true);
  try {
    const res = await fetch("/api/email-autopilot-schedule", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({
        action,
        db_path: state.dbPath || els.dbPathInput.value,
        days: followUpDays(),
        interval_minutes: els.autopilotIntervalInput ? Number(els.autopilotIntervalInput.value || 15) : 15,
        run_now: action === "start",
      }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Autopilot-Plan konnte nicht geändert werden");
    renderAutopilotSchedule(data);
    showToast(data.enabled ? "Autopilot-Plan gestartet" : "Autopilot-Plan gestoppt", "ok");
  } catch (err) {
    showToast(err.message);
  } finally {
    setBusy(false);
  }
}
const PFX_ICON = {
  loc: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2a7 7 0 00-7 7c0 5 7 13 7 13s7-8 7-13a7 7 0 00-7-7zm0 9.5A2.5 2.5 0 1112 6.5a2.5 2.5 0 010 5z"/></svg>',
  mail: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4h16a2 2 0 012 2v12a2 2 0 01-2 2H4a2 2 0 01-2-2V6a2 2 0 012-2zm0 2v.4l8 5 8-5V6H4zm16 12V8.9l-8 5-8-5V18h16z"/></svg>',
  phone: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6.6 10.8a15 15 0 006.6 6.6l2.2-2.2a1 1 0 011-.25c1.1.37 2.3.57 3.6.57a1 1 0 011 1V20a1 1 0 01-1 1A17 17 0 013 4a1 1 0 011-1h3.3a1 1 0 011 1c0 1.3.2 2.5.57 3.6a1 1 0 01-.25 1l-2.2 2.2z"/></svg>',
};

function profileInitials(name) {
  const parts = String(name || "").trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  const first = parts[0][0] || "";
  const last = parts.length > 1 ? parts[parts.length - 1][0] : "";
  return (first + last).toUpperCase();
}

function cefrPercent(level) {
  const key = String(level || "").trim().toLowerCase().replace(/\s+/g, "");
  const map = { a1: 17, a2: 33, b1: 50, b2: 67, c1: 83, c2: 100 };
  if (map[key] != null) return map[key];
  if (/(mutter|native|fließend|fluent|verhandlung)/.test(key)) return 100;
  return 60;
}

function renderProfile(data) {
  const p = data && data.profile;
  if (!els.profilePanel || !p) return;
  els.profilePanel.classList.remove("profile-empty");

  const contact = [
    p.location ? `<span class="pfx-cc">${PFX_ICON.loc}${escapeHtml(p.location)}</span>` : "",
    p.email ? `<span class="pfx-cc">${PFX_ICON.mail}${escapeHtml(p.email)}</span>` : "",
    p.phone ? `<span class="pfx-cc">${PFX_ICON.phone}${escapeHtml(p.phone)}</span>` : "",
  ].join("") || '<span class="pfx-cc muted">Keine Kontaktdaten erkannt</span>';

  const exp = (p.experience || []).map((e) => `
    <div class="pfx-card">
      <div class="pfx-card-head">
        <strong>${escapeHtml(e.role || "—")}</strong>
        <span class="pfx-period">${escapeHtml(e.start || "?")} – ${escapeHtml(e.end || "heute")}</span>
      </div>
      <div class="pfx-org">${escapeHtml(e.company || "")}</div>
      ${e.summary ? `<p class="pfx-summary">${escapeHtml(e.summary)}</p>` : ""}
      ${(e.skills_used || []).length ? `<div class="skill-list">${pillList(e.skills_used)}</div>` : ""}
    </div>`).join("") || '<div class="pfx-emptyrow">Keine Angaben erkannt.</div>';

  const edu = (p.education || []).map((e) => `
    <div class="pfx-card">
      <div class="pfx-card-head">
        <strong>${escapeHtml([e.degree, e.field].filter(Boolean).join(" · ") || "—")}</strong>
        <span class="pfx-period">${escapeHtml(e.start || "?")} – ${escapeHtml(e.end || "heute")}</span>
      </div>
      <div class="pfx-org">${escapeHtml(e.institution || "")}${e.grade ? " · Note " + escapeHtml(e.grade) : ""}</div>
    </div>`).join("") || '<div class="pfx-emptyrow">Keine Angaben erkannt.</div>';

  const langs = Object.entries(p.languages || {}).map(([c, l]) => `
    <div class="pfx-lang">
      <span class="pfx-lang-name">${escapeHtml(c)}</span>
      <span class="pfx-lang-badge">${escapeHtml(l)}</span>
      <div class="pfx-lang-bar"><span style="width:${cefrPercent(l)}%"></span></div>
    </div>`).join("") || '<div class="pfx-emptyrow">Keine Angaben erkannt.</div>';

  const pr = p.preferences || {};
  const prefRows = [
    ["Orte", (pr.locations || []).join(", ") || "—"],
    ["Remote", pr.remote_ok ? "ja" : "nein"],
    ["Art", (pr.employment_types || []).join(", ") || "—"],
  ];
  if (pr.min_salary) prefRows.push(["Min. Gehalt", `${pr.min_salary} €`]);
  const prefs = prefRows.map(([k, v]) => `<div class="pfx-pref"><span>${escapeHtml(k)}</span><strong>${escapeHtml(v)}</strong></div>`).join("");

  const sourceTag = data.source === "cv"
    ? '<span class="pfx-source cv">aus CV</span>'
    : '<span class="pfx-source demo">Demo</span>';
  const banner = data.warning
    ? `<div class="pf-warning">⚠ ${escapeHtml(data.warning)}</div>`
    : data.source === "demo"
      ? `<div class="pf-note">Demo-Profil (Vorschau). Importiere einen Lebenslauf für dein echtes Profil.</div>`
      : "";

  els.profilePanel.innerHTML = `${banner}
    <div class="pfx">
      <div class="pfx-hero">
        <div class="pfx-avatar">${escapeHtml(profileInitials(p.name))}</div>
        <div class="pfx-hero-main">
          <h2 class="pfx-name">${escapeHtml(p.name || "—")}</h2>
          ${p.headline ? `<p class="pfx-headline">${escapeHtml(p.headline)}</p>` : ""}
          <div class="pfx-contact">${contact}</div>
        </div>
        ${sourceTag}
      </div>
      <div class="pfx-stats">
        <div><strong>${(p.skills || []).length}</strong><span>Skills</span></div>
        <div><strong>${(p.experience || []).length}</strong><span>Stationen</span></div>
        <div><strong>${(p.education || []).length}</strong><span>Ausbildung</span></div>
        <div><strong>${Object.keys(p.languages || {}).length}</strong><span>Sprachen</span></div>
      </div>
      <div class="pfx-body">
        <div class="pfx-main">
          <section class="pfx-sec"><h3>Berufserfahrung</h3><div class="pfx-cards">${exp}</div></section>
          <section class="pfx-sec"><h3>Ausbildung</h3><div class="pfx-cards">${edu}</div></section>
        </div>
        <aside class="pfx-aside">
          <section class="pfx-sec"><h3>Skills</h3><div class="skill-list">${pillList(p.skills)}</div></section>
          <section class="pfx-sec"><h3>Sprachen</h3><div class="pfx-langs">${langs}</div></section>
          <section class="pfx-sec"><h3>Präferenzen</h3><div class="pfx-prefs">${prefs}</div></section>
        </aside>
      </div>
    </div>`;
}

/* --------------------------- pipeline ------------------------------ */
function setMode(demo) {
  state.demo = demo;
  els.demoModeBtn.classList.toggle("is-active", demo);
  els.liveModeBtn.classList.toggle("is-active", !demo);
  els.dbPathInput.value = demo ? "./data/demo_job_agent.db" : "./data/job_agent.db";
  if (els.sourceFact) els.sourceFact.textContent = demo ? "Beispiele" : "Live";
  if (els.dbPathLabel) els.dbPathLabel.textContent = demo ? "Beispieldaten" : "Live-Suche";
  if (demo && state.profileSource !== "cv") {
    state.cvDirty = false;
  }
}
function payload() {
  const data = {
    demo: state.demo,
    query: els.queryInput.value,
    limit: Number(els.limitInput.value || 5),
    threshold: (els.thresholdInput.value === "" ? 50 : Number(els.thresholdInput.value)) / 100,
    db_path: els.dbPathInput.value,
    reset_db: els.resetInput.checked,
    llm_agents: els.llmInput.checked,
    chroma: els.chromaInput.checked,
    draft_all: els.draftAllInput.checked,
    force_demo_profile: state.demo && state.profileSource === "demo",
  };
  const cvText = els.cvInput ? els.cvInput.value.trim() : "";
  if (state.cvDirty && cvText) data.cv_text = cvText;
  return data;
}
async function runPipeline() {
  if (!state.profileReady) {
    showToast("Bitte zuerst ein eigenes Profil erstellen oder das Demo-Profil bewusst laden.");
    location.hash = "#/profil";
    return;
  }
  if (els.resetInput?.checked && !window.confirm(
    "Vorherige Jobs, Bewertungen, Entwürfe und Statushistorien dieses Kontos wirklich löschen? Profil und Mail-Audit bleiben erhalten."
  )) return;
  setBusy(true);
  state.pipelineRunning = true;
  if (els.searchStateFact) els.searchStateFact.textContent = "Laeuft";
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
    if (els.resetInput) els.resetInput.checked = false;
    await loadConfig();
    els.statusText.textContent = "Pipeline abgeschlossen";
    if (els.searchStateFact) els.searchStateFact.textContent = "Abgeschlossen";
    progress.finish();
  } catch (err) {
    showToast(err.message);
    if (els.searchStateFact) els.searchStateFact.textContent = "Fehler";
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
async function loadState({ silent = false } = {}) {
  if (state.pipelineRunning) return;
  try {
    const res = await fetch("/api/state");
    const data = await res.json();
    if (!res.ok || data.ok === false) throw new Error(data.error || "State konnte nicht geladen werden");
    applyData(data);
  } catch (err) {
    if (!silent) showToast(err.message);
  }
}

function applyData(data) {
  if (!data) return;
  if (Array.isArray(data.jobs)) state.jobs = data.jobs;
  if (Array.isArray(data.applications)) state.applications = data.applications;
  if (!state.selectedJobId || !state.jobs.some((job) => job.id === state.selectedJobId)) {
    state.selectedJobId = state.jobs[0]?.id || null;
  }
  const s = data.summary || {};
  if (els.jobsMetric) els.jobsMetric.textContent = s.jobs ?? state.jobs.length ?? 0;
  if (els.matchesMetric) els.matchesMetric.textContent = s.matches ?? 0;
  if (els.draftsMetric) els.draftsMetric.textContent = s.drafts ?? state.applications.length ?? 0;
  if (els.trackedMetric) els.trackedMetric.textContent = s.tracked ?? state.applications.length ?? 0;
  if (data.db_path) {
    state.dbPath = data.db_path;
    if (els.dbPathInput) els.dbPathInput.value = data.db_path;
    const dbName = String(data.db_path).split(/[\\/]/).pop() || "";
    state.demo = dbName.includes("demo");
    if (els.demoModeBtn) els.demoModeBtn.classList.toggle("is-active", state.demo);
    if (els.liveModeBtn) els.liveModeBtn.classList.toggle("is-active", !state.demo);
    if (els.sourceFact) els.sourceFact.textContent = state.demo ? "Beispiele" : "Live";
  }
  if (els.dbPathLabel) {
    els.dbPathLabel.textContent = state.demo ? "Beispieldaten" : "Live-Suche";
  }
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
  renderTracker();
  refreshFollowUpBadge();
}

/* --------------------------- rendering ----------------------------- */
function scoreModifier(score, risk) {
  if (risk === "high") return "danger";
  if (score === null || score === undefined) return "neutral";
  if (score >= 0.75) return "";
  if (score >= 0.5) return "mid";
  return "low";
}
function riskShort(level) {
  if (level === "high") return "Risiko hoch";
  if (level === "medium") return "Risiko mittel";
  return "Risiko niedrig";
}
function livenessLabel(status) {
  if (status === "live") return { text: "Offen", cls: "live" };
  if (status === "expired") return { text: "Abgelaufen", cls: "expired" };
  return { text: "Unsicher", cls: "unknown" };
}
function remoteLabel(remote) {
  if (remote === true) return "Remote möglich";
  if (remote === false) return "Vor Ort";
  return "Remote: k. A.";
}
function recommendationLabel(value) {
  if (value === "strong") return "Sehr gute Priorität";
  if (value === "good") return "Gute Priorität";
  if (value === "skip") return "Nicht priorisieren";
  return "Manuell prüfen";
}

const COMPANY_SKIP = new Set(["gmbh", "ag", "se", "kg", "ug", "co", "ltd", "inc", "llc", "ev", "mbh", "und"]);
function companyInitials(name) {
  const words = String(name || "").trim().split(/\s+/).filter((w) => w && !COMPANY_SKIP.has(w.toLowerCase().replace(/[.,&]/g, "")));
  if (!words.length) return "?";
  return ((words[0][0] || "") + (words.length > 1 ? words[1][0] : "")).toUpperCase();
}

function renderJobs() {
  if (!els.jobsBody) return;
  if (!state.jobs.length) {
    els.jobsBody.innerHTML = '<div class="empty search-empty">Noch keine Jobs. Starte oben eine Suche.</div>';
    return;
  }
  els.jobsBody.innerHTML = state.jobs.map((job) => {
    const score = typeof job.score === "number" ? job.score : null;
    const mod = scoreModifier(score, job.risk_level);
    const scoreText = score === null ? "-" : Math.round(score * 100) + "%";
    const statusChip = job.status ? `<span class="chip status">${escapeHtml(job.status)}</span>` : "";
    const riskMeta = job.risk_level && job.risk_level !== "low"
      ? `<span>${escapeHtml(riskShort(job.risk_level))}</span>` : "";
    return `<div class="job-row ${job.id === state.selectedJobId ? "selected" : ""}" data-id="${escapeAttr(job.id)}">
      <div class="jr-ava">${escapeHtml(companyInitials(job.company))}</div>
      <div class="jr-main">
        <div class="jr-title">${escapeHtml(job.title)}</div>
        <div class="jr-sub">${escapeHtml(job.company)} - ${escapeHtml(job.location)}${job.remote ? " - Remote" : ""}</div>
        <div class="jr-meta">
          <span>${escapeHtml(job.source_label || job.source)}</span>
          <span>${escapeHtml(recommendationLabel(job.recommendation))}</span>
          ${riskMeta}
        </div>
      </div>
      <div class="jr-right">
        <span class="score-meter ${mod}">${scoreText}</span>
        ${statusChip}
      </div>
    </div>`;
  }).join("");
  els.jobsBody.querySelectorAll(".job-row").forEach((row) =>
    row.addEventListener("click", () => {
      state.selectedJobId = row.dataset.id;
      renderJobs();
      renderDetail();
      renderLetter();
    })
  );
}

function renderLivenessBadge(job) {
  if (!els.livenessBadge) return;
  const live = job && job.liveness;
  if (!live) {
    els.livenessBadge.className = "liveness-badge is-hidden";
    els.livenessBadge.textContent = "";
    els.livenessBadge.removeAttribute("title");
    return;
  }
  const label = livenessLabel(live.status);
  els.livenessBadge.className = `liveness-badge ${label.cls}`;
  els.livenessBadge.textContent = `${label.text} · ${Math.round((live.confidence || 0) * 100)}%`;
  els.livenessBadge.title = live.reason || "";
}

function detailSection(title, body, open = false, subtitle = "") {
  return `<details class="detail-section" ${open ? "open" : ""}>
    <summary><span>${escapeHtml(title)}</span>${subtitle ? `<small>${escapeHtml(subtitle)}</small>` : ""}</summary>
    <div class="detail-section-body">${body}</div>
  </details>`;
}

function salaryText(job) {
  if (!Array.isArray(job.salary_range) || job.salary_range.length < 2) return "k. A.";
  return `${Number(job.salary_range[0]).toLocaleString("de-DE")} - ${Number(job.salary_range[1]).toLocaleString("de-DE")} EUR`;
}

function jobOverviewBlock(job, score, mod) {
  const scoreText = score === null ? "-" : Math.round(score * 100) + "%";
  return `<div class="job-overview">
    <div class="job-overview-main">
      <p class="company-line">${escapeHtml(job.company)}</p>
      <h3>${escapeHtml(job.title)}</h3>
      <p>${escapeHtml(job.score_summary || job.rationale || "Noch keine Bewertung vorhanden.")}</p>
    </div>
    <div class="score-card ${mod}">
      <span>Fit</span>
      <strong>${scoreText}</strong>
      <small>${escapeHtml(recommendationLabel(job.recommendation))}</small>
    </div>
    <dl class="fact-grid">
      <div><dt>Ort</dt><dd>${escapeHtml(job.location || "k. A.")}</dd></div>
      <div><dt>Remote</dt><dd>${escapeHtml(remoteLabel(job.remote))}</dd></div>
      <div><dt>Quelle</dt><dd>${escapeHtml(job.source_label || job.source)}</dd></div>
      <div><dt>Gehalt</dt><dd>${escapeHtml(salaryText(job))}</dd></div>
    </dl>
  </div>`;
}

function requirementsBlock(job) {
  return `<div class="skill-columns">
    <div><h4>Passend</h4><div class="skill-list">${pillList(job.matched_skills)}</div></div>
    <div><h4>Fehlend</h4><div class="skill-list">${pillList(job.missing_skills, "missing")}</div></div>
    <div><h4>Anforderungen</h4><div class="skill-list">${pillList(job.requirements || [])}</div></div>
    <div><h4>Optional</h4><div class="skill-list">${pillList(job.nice_to_have || [])}</div></div>
  </div>`;
}

function applyRecipientSuggestions(job) {
  // Purely informational: the app never sends here itself, this only tells
  // the operator where they might forward the reviewed package themselves.
  if (!els.recipientHint) return;
  if (!job) {
    els.recipientHint.innerHTML = "";
    return;
  }
  const suggestions = job.recipient_suggestions || [];
  const best = job.contact_email || (suggestions[0] && suggestions[0].email) || "";
  if (!suggestions.length) {
    els.recipientHint.innerHTML = '<span class="muted-xs">Keine Bewerbungsadresse im Inserat erkannt.</span>';
    return;
  }
  const chips = suggestions.slice(0, 4).map((item) => `
    <span class="recipient-chip" title="${Math.round(Number(item.confidence || 0) * 100)}% - ${escapeAttr(item.reason || "")}">
      ${escapeHtml(item.email)}
    </span>`).join("");
  els.recipientHint.innerHTML = `<div class="recipient-hint-head"><span>Im Inserat erkannt</span><strong>${escapeHtml(best || "-")}</strong></div><div class="recipient-chips">${chips}</div><p class="muted-xs">Bitte nach Pruefung selbst dorthin weiterleiten.</p>`;
}

function renderDetail() {
  const job = selectedJob();
  if (els.checkLivenessBtn) els.checkLivenessBtn.disabled = !job;
  renderLivenessBadge(job);
  if (!job) {
    els.detailTitle.textContent = "Details";
    els.jobLink.style.visibility = "hidden";
    els.jobDetail.className = "detail-body empty-detail";
    els.jobDetail.innerHTML = '<div class="empty-detail-state">Waehle links einen Job aus.</div>';
    applyRecipientSuggestions(null);
    return;
  }

  els.detailTitle.textContent = job.title;
  els.jobLink.href = job.url;
  els.jobLink.style.visibility = "visible";
  applyRecipientSuggestions(job);
  els.jobDetail.className = "detail-body detail-accordion";
  const score = typeof job.score === "number" ? job.score : null;
  const mod = scoreModifier(score, job.risk_level);
  els.jobDetail.innerHTML = [
    detailSection("Uebersicht", jobOverviewBlock(job, score, mod), true, "Firma, Ort und Prioritaet"),
    detailSection(
      "Score",
      `<div class="score-main"><div><h3>Bewertung</h3><p class="score-explain">${escapeHtml(job.score_explanation || "-")}</p></div><span class="score-big ${mod}">${score === null ? "-" : Math.round(score * 100) + "%"}</span></div>${scoreBreakdown(job.score_components || [])}`,
      true,
      "Gewichtung und Evidenz"
    ),
    detailSection("Beschreibung", `<p class="job-description">${escapeHtml(job.description || "-")}</p>`, false, "Originaltext der Anzeige"),
    detailSection("Anforderungen", requirementsBlock(job), false, "Skills und Luecken"),
    detailSection("Risiko", riskBlock(job), false, "Qualitaets- und Scam-Signale"),
    detailSection("Begruendung", `<p class="reasoning-text">${escapeHtml(job.rationale || "-")}</p>`, false, "Warum diese Bewertung")
  ].join("");
}

function scoreBreakdown(components) {
  if (!components.length) return '<span class="empty">Noch keine Rubrikdaten.</span>';
  return `<div class="score-breakdown">${components.map((item) => {
    const pct = Math.max(0, Math.min(100, (Number(item.score || 0) / 5) * 100));
    return `<div class="score-row">
      <div class="score-row-head"><strong>${escapeHtml(item.label || item.key)}</strong><span>${Number(item.score || 0)}/5 · ${Number(item.weight || 0)}%</span></div>
      <div class="score-bar"><span style="width:${pct}%"></span></div>
      <p>${escapeHtml(item.evidence || "")}</p>
    </div>`;
  }).join("")}</div>`;
}
function riskBlock(job) {
  const flags = job.risk_flags || [];
  const level = job.risk_level || "low";
  const summary = flags.length
    ? flags.map((f) => `<li>${escapeHtml(f)}</li>`).join("")
    : "<li>Keine starken Ghost-Job- oder Scam-Signale erkannt.</li>";
  return `<div class="risk-box ${escapeAttr(level)}">
    <div class="risk-head"><span class="risk-pill ${escapeAttr(level)}">${riskShort(level)}</span><strong>${escapeHtml(recommendationLabel(job.recommendation))}</strong></div>
    <ul>${summary}</ul></div>`;
}

function renderLetter() {
  const job = selectedJob();
  const app = job ? state.applications.find((a) => a.job_id === job.id) : null;
  syncStatusControls(job, app);
  if (els.interviewPrepPanel) {
    els.interviewPrepPanel.classList.add("is-hidden");
    els.interviewPrepPanel.innerHTML = "";
  }
  if (!app) {
    els.letterBody.textContent = job
      ? 'Noch kein Anschreiben fuer diesen Job. Klicke auf "Entwurf erstellen", um jetzt einen passenden Bewerbungsentwurf zu erzeugen.'
      : "Noch kein Entwurf.";
    return;
  }
  const checks = Object.entries(app.quality_checks || {}).map(([k, ok]) => `${ok ? "OK" : "WARN"} ${k}`).join("\n");
  els.letterBody.textContent = checks ? `${app.cover_letter_md}\n\n---\nQualitätschecks\n${checks}` : app.cover_letter_md;
}
function syncStatusControls(job, app) {
  const hasJob = Boolean(job);
  const hasApp = Boolean(app);
  if (els.statusSelect) { els.statusSelect.disabled = !hasApp; els.statusSelect.value = app?.status || "draft"; }
  if (els.notesInput) { els.notesInput.disabled = !hasApp; els.notesInput.value = app?.notes || ""; }
  if (els.generateDraftBtn) els.generateDraftBtn.disabled = !hasJob || hasApp;
  [els.saveStatusBtn, els.sendEmailBtn, els.exportBtn, els.copyBtn].forEach((b) => { if (b) b.disabled = !hasApp; });
  [els.reportBtn, els.interviewPrepBtn].forEach((b) => { if (b) b.disabled = !hasJob; });
  if (els.downloadLink) els.downloadLink.classList.add("is-hidden");
}
function selectedJob() {
  return state.jobs.find((j) => j.id === state.selectedJobId) || null;
}

function renderTracker() {
  if (!els.trackerBody) return;
  const apps = state.applications || [];
  if (!apps.length) {
    els.trackerBody.innerHTML = '<tr><td colspan="6" class="empty">Noch keine Bewerbungen — starte die Pipeline in „Suche".</td></tr>';
    return;
  }
  els.trackerBody.innerHTML = apps.map((app) => {
    const job = state.jobs.find((j) => j.id === app.job_id);
    return `<tr>
      <td><strong>${escapeHtml(job ? job.title : app.job_id)}</strong><div class="jr-sub">${escapeHtml(job ? job.company : "")}</div></td>
      <td><span class="status-pill ${escapeAttr(app.status || "draft")}">${escapeHtml(app.status || "draft")}</span></td>
      <td>${fmtDate(app.submitted_at)}</td>
      <td>${fmtDate(app.updated_at)}</td>
      <td>${escapeHtml((app.notes || "").split("\n").pop().slice(0, 80))}</td>
      <td><button class="btn btn-ghost btn-sm" data-open="${escapeAttr(app.job_id)}">Öffnen</button></td>
    </tr>`;
  }).join("");
  els.trackerBody.querySelectorAll("[data-open]").forEach((b) =>
    b.addEventListener("click", async () => {
      state.selectedJobId = b.dataset.open;
      if (!state.jobs.some((job) => job.id === state.selectedJobId)) {
        await loadState({ silent: true });
      }
      renderJobs(); renderDetail(); renderLetter();
      location.hash = "#/suche";
    })
  );
}
function fmtDate(iso) {
  if (!iso) return "–";
  const d = new Date(iso);
  return isNaN(d) ? "–" : d.toLocaleDateString("de-DE");
}

function fmtDateTime(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  return isNaN(d) ? "-" : d.toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" });
}

/* --------------------------- CV-Check ------------------------------ */
async function reviewCv() {
  const cv_text = els.cvInput ? els.cvInput.value.trim() : "";
  if (!cv_text) {
    els.cvFileStatus.textContent = "Bitte zuerst einen Lebenslauf importieren oder Text einfügen.";
    return;
  }
  const useLlm = Boolean(els.cvCheckLlmInput && els.cvCheckLlmInput.checked);
  progress.show(useLlm ? "CV-Check läuft (Rubrik + LLM) …" : "CV-Check läuft …", null);
  setBusy(true);
  try {
    const res = await fetch("/api/review-cv", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ cv_text, llm: useLlm }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "CV-Check fehlgeschlagen");
    renderCvCheck(data.assessment || {});
    els.statusText.textContent = "CV-Check abgeschlossen";
  } catch (err) {
    showToast(err.message);
  } finally {
    progress.hide();
    setBusy(false);
  }
}

function renderCvCheck(a) {
  if (!els.cvCheckPanel) return;
  const score = Number(a.overall_score || 0);
  const pct = Math.round((score / 5) * 100);
  const band = score >= 4 ? "good" : score >= 3 ? "mid" : score >= 2 ? "low" : "bad";
  const rows = (a.components || []).map((item) => {
    const width = Math.max(0, Math.min(100, (Number(item.score || 0) / 5) * 100));
    return `<div class="score-row">
      <div class="score-row-head"><strong>${escapeHtml(item.label || item.key)}</strong><span>${Number(item.score || 0)}/5 · ${Number(item.weight || 0)}%</span></div>
      <div class="score-bar"><span style="width:${width}%"></span></div>
      <p>${escapeHtml(item.evidence || "")}</p>
    </div>`;
  }).join("");
  const tips = (a.tips || []).length
    ? `<div class="cv-tips"><h3>Konkrete Tipps</h3><ol>${a.tips.map((t) => `<li>${escapeHtml(t)}</li>`).join("")}</ol></div>`
    : "";
  const llm = a.llm_feedback
    ? `<div class="cv-llm"><h3>LLM-Feedback</h3><p>${escapeHtml(a.llm_feedback)}</p></div>`
    : "";
  els.cvCheckPanel.classList.remove("is-hidden");
  els.cvCheckPanel.innerHTML = `
    <div class="cv-check-grid">
      <div class="gauge-wrap">
        <div class="gauge ${band}" style="--val:${pct}">
          <div class="gauge-inner"><strong>${score.toFixed(1)}</strong><span>/ 5</span></div>
        </div>
        <p class="gauge-summary">${escapeHtml(a.summary || "")}</p>
        <p class="muted-xs">${Number(a.word_count || 0)} Wörter analysiert</p>
      </div>
      <div class="score-breakdown">${rows}</div>
    </div>
    ${tips}${llm}`;
}

/* --------------------------- Follow-ups ---------------------------- */
function followUpDays() {
  const n = Number(els.followupDaysInput && els.followupDaysInput.value);
  return Number.isFinite(n) && n >= 1 ? Math.min(60, Math.round(n)) : 7;
}
async function fetchFollowUps() {
  const params = new URLSearchParams({ days: String(followUpDays()) });
  if (state.dbPath) params.set("db_path", state.dbPath);
  const res = await fetch(`/api/follow-ups?${params}`);
  const data = await res.json();
  if (!res.ok || !data.ok) throw new Error(data.error || "Follow-ups konnten nicht geladen werden");
  return data.follow_ups || [];
}
async function loadFollowUps() {
  if (!els.followupsBody) return;
  try {
    state.followUps = await fetchFollowUps();
    renderFollowUps();
    updateFollowUpBadge(state.followUps.length);
  } catch (err) {
    els.followupsBody.innerHTML = `<div class="empty">${escapeHtml(err.message)}</div>`;
  }
}
async function refreshFollowUpBadge() {
  try {
    updateFollowUpBadge((await fetchFollowUps()).length);
  } catch {
    /* badge is best-effort */
  }
}
function updateFollowUpBadge(count) {
  if (!els.followupsBadge) return;
  els.followupsBadge.textContent = String(count);
  els.followupsBadge.classList.toggle("is-hidden", !count);
}
function renderFollowUps() {
  const items = state.followUps || [];
  if (!items.length) {
    els.followupsBody.innerHTML =
      '<div class="empty">Keine fälligen Follow-ups — alles im grünen Bereich.</div>';
    return;
  }
  const dryRun = state.config.email_dry_run !== false;
  els.followupsBody.innerHTML = items.map((item) => {
    const recipient = item.contact_email || "";
    const recipientText = recipient ? `An: ${escapeHtml(recipient)}` : "Keine Empfaengeradresse erkannt";
    return `
    <div class="fu-item" data-id="${escapeAttr(item.job_id)}">
      <div class="fu-head">
        <div>
          <strong>${escapeHtml(item.title)}</strong>
          <div class="jr-sub">${escapeHtml(item.company || "")}</div>
          <div class="fu-recipient">${recipientText}</div>
        </div>
        <div class="fu-meta">
          <span class="chip overdue">${item.days_overdue} Tage überfällig</span>
          <span class="jr-sub">beworben: ${fmtDate(item.submitted_at)} · inaktiv seit ${item.days_since_activity} Tagen</span>
        </div>
      </div>
      <details class="fu-draft">
        <summary>Nachfass-E-Mail anzeigen</summary>
        <pre class="letter">${escapeHtml(item.suggested_email_md || "")}</pre>
      </details>
      <div class="btn-row">
        <button class="btn btn-primary btn-sm" data-fu-send="${escapeAttr(item.job_id)}" ${recipient ? "" : "disabled"}>
          ${dryRun ? "E-Mail senden (Dry-Run)" : "E-Mail senden"}
        </button>
        <button class="btn btn-ghost btn-sm" data-fu-copy="${escapeAttr(item.job_id)}">Entwurf kopieren</button>
        <button class="btn btn-ghost btn-sm" data-fu-done="${escapeAttr(item.job_id)}">Als erledigt vermerken</button>
      </div>
    </div>`;
  }).join("");
  els.followupsBody.querySelectorAll("[data-fu-send]").forEach((b) =>
    b.addEventListener("click", () => sendFollowUpEmail(b.dataset.fuSend))
  );
  els.followupsBody.querySelectorAll("[data-fu-done]").forEach((b) =>
    b.addEventListener("click", () => recordFollowUp(b.dataset.fuDone))
  );
  els.followupsBody.querySelectorAll("[data-fu-copy]").forEach((b) =>
    b.addEventListener("click", async () => {
      const item = (state.followUps || []).find((f) => f.job_id === b.dataset.fuCopy);
      try {
        await navigator.clipboard.writeText(item ? item.suggested_email_md : "");
        els.statusText.textContent = "Entwurf kopiert";
      } catch {
        els.statusText.textContent = "Kopieren nicht möglich";
      }
    })
  );
}
async function recordFollowUp(jobId) {
  setBusy(true);
  try {
    const res = await fetch("/api/record-follow-up", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ job_id: jobId, db_path: state.dbPath || els.dbPathInput.value }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Follow-up konnte nicht vermerkt werden");
    state.applications = data.applications || state.applications;
    els.statusText.textContent = "Follow-up vermerkt";
    await loadFollowUps();
    renderTracker();
  } catch (err) {
    showToast(err.message);
  } finally {
    setBusy(false);
  }
}
async function sendFollowUpEmail(jobId) {
  const item = (state.followUps || []).find((f) => f.job_id === jobId);
  const dryRun = state.config.email_dry_run !== false;
  const reviewTarget = state.config.email_review_recipient || "deine Kontroll-E-Mail";
  if (!dryRun && !window.confirm(
    `Follow-up-Kontrollpaket jetzt wirklich an ${reviewTarget} senden (zur eigenen Pruefung)?`
  )) return;
  setBusy(true);
  try {
    const res = await fetch("/api/send-follow-up-email", {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify({
          job_id: jobId,
          db_path: state.dbPath || els.dbPathInput.value,
          body_md: item ? item.suggested_email_md : "",
          confirm_real_send: !dryRun,
          idempotency_key: `web:follow-up:${jobId}`,
        }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Follow-up-E-Mail fehlgeschlagen");
    state.applications = data.applications || state.applications;
    const email = data.email || {};
    els.statusText.textContent = email.dry_run
      ? `Follow-up-Kontrollpaket Dry-run vorbereitet: ${email.recipient}`
      : `Follow-up-Kontrollpaket gesendet an: ${email.recipient}`;
    await loadFollowUps();
    renderTracker();
  } catch (err) {
    showToast(err.message);
  } finally {
    setBusy(false);
  }
}

/* --------------------------- URL-Inbox ----------------------------- */
async function loadInboxItems() {
  if (!els.inboxBody) return;
  try {
    const res = await fetch("/api/inbox");
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Inbox konnte nicht geladen werden");
    state.inboxItems = data.items || [];
    renderInbox();
    updateInboxBadge();
  } catch (err) {
    els.inboxBody.innerHTML = `<div class="empty">${escapeHtml(err.message)}</div>`;
  }
}
function updateInboxBadge() {
  if (!els.inboxBadge) return;
  const fresh = (state.inboxItems || []).filter((item) => item.status === "neu").length;
  els.inboxBadge.textContent = String(fresh);
  els.inboxBadge.classList.toggle("is-hidden", !fresh);
}
function renderInbox() {
  const items = state.inboxItems || [];
  if (!items.length) {
    els.inboxBody.innerHTML =
      '<div class="empty">Die Inbox ist leer — Portal-Link oben einfügen oder eine Anzeige unten direkt bewerten.</div>';
    return;
  }
  const statusChip = (status) => {
    const cls = status === "bewertet" ? "score" : status === "verworfen" ? "risk medium" : "status";
    return `<span class="chip ${cls}">${escapeHtml(status)}</span>`;
  };
  els.inboxBody.innerHTML = items.map((item) => `
    <div class="inbox-item" data-id="${escapeAttr(item.id)}">
      <div class="inbox-main">
        <a href="${escapeAttr(item.url)}" target="_blank" rel="noreferrer">${escapeHtml(item.url)}</a>
        <div class="jr-sub">${escapeHtml(item.note || "")}${item.note ? " · " : ""}gemerkt: ${fmtDate(item.added_at)}</div>
      </div>
      <div class="inbox-actions">
        ${statusChip(item.status)}
        <button class="btn btn-ghost btn-sm" data-ib-eval="${escapeAttr(item.id)}">Bewerten</button>
        <button class="btn btn-ghost btn-sm" data-ib-discard="${escapeAttr(item.id)}">Verwerfen</button>
        <button class="btn btn-ghost btn-sm" data-ib-remove="${escapeAttr(item.id)}">Löschen</button>
      </div>
    </div>`).join("");
  els.inboxBody.querySelectorAll("[data-ib-eval]").forEach((b) =>
    b.addEventListener("click", () => prefillJdForm(b.dataset.ibEval))
  );
  els.inboxBody.querySelectorAll("[data-ib-discard]").forEach((b) =>
    b.addEventListener("click", () => updateInboxItem(b.dataset.ibDiscard, "status", "verworfen"))
  );
  els.inboxBody.querySelectorAll("[data-ib-remove]").forEach((b) =>
    b.addEventListener("click", () => updateInboxItem(b.dataset.ibRemove, "remove"))
  );
}
function prefillJdForm(itemId) {
  const item = (state.inboxItems || []).find((entry) => entry.id === itemId);
  if (!item) return;
  state.jdInboxId = item.id;
  if (els.jdUrlInput) els.jdUrlInput.value = item.url;
  if (els.jdTextInput) els.jdTextInput.focus();
  showToast("URL übernommen — Anzeigentext einfügen und „Bewerten“ klicken.", "ok");
}
async function addInboxUrl() {
  const url = els.inboxUrlInput ? els.inboxUrlInput.value.trim() : "";
  if (!url) {
    showToast("Bitte zuerst eine URL einfügen.");
    return;
  }
  setBusy(true);
  try {
    const res = await fetch("/api/inbox", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ url, note: els.inboxNoteInput ? els.inboxNoteInput.value : "" }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Konnte nicht gemerkt werden");
    state.inboxItems = data.items || [];
    if (els.inboxUrlInput) els.inboxUrlInput.value = "";
    if (els.inboxNoteInput) els.inboxNoteInput.value = "";
    renderInbox();
    updateInboxBadge();
    showToast("In der Inbox gemerkt.", "ok");
  } catch (err) {
    showToast(err.message);
  } finally {
    setBusy(false);
  }
}
async function updateInboxItem(itemId, action, status) {
  setBusy(true);
  try {
    const res = await fetch("/api/inbox/update", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ id: itemId, action, status }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Inbox-Update fehlgeschlagen");
    state.inboxItems = data.items || [];
    renderInbox();
    updateInboxBadge();
  } catch (err) {
    showToast(err.message);
  } finally {
    setBusy(false);
  }
}
async function evaluateJd() {
  const title = els.jdTitleInput ? els.jdTitleInput.value.trim() : "";
  const description = els.jdTextInput ? els.jdTextInput.value.trim() : "";
  if (!title || description.length < 40) {
    showToast("Bitte mindestens Jobtitel und den kompletten Anzeigentext einfügen.");
    return;
  }
  setBusy(true);
  progress.show("Anzeige wird bewertet …", null);
  try {
    const res = await fetch("/api/inbox/evaluate", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({
        title,
        company: els.jdCompanyInput ? els.jdCompanyInput.value : "",
        location: els.jdLocationInput ? els.jdLocationInput.value : "",
        url: els.jdUrlInput ? els.jdUrlInput.value : "",
        description,
        llm: Boolean(els.jdLlmInput && els.jdLlmInput.checked),
        threshold: Number(els.thresholdInput ? els.thresholdInput.value : 50) / 100,
        db_path: state.dbPath || (els.dbPathInput ? els.dbPathInput.value : ""),
        inbox_id: state.jdInboxId || "",
      }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Bewertung fehlgeschlagen");
    state.jdInboxId = "";
    renderJdEvalResult(data);
    mergeEvaluatedJob(data);
    loadInboxItems();
    refreshFollowUpBadge();
    showToast("Anzeige bewertet.", "ok");
  } catch (err) {
    showToast(err.message);
  } finally {
    progress.hide();
    setBusy(false);
  }
}
function renderJdEvalResult(data) {
  if (!els.jdEvalResult) return;
  const job = data.job || {};
  const score = typeof job.score === "number" ? Math.round(job.score * 100) + " %" : "–";
  const mod = scoreModifier(job.score, job.risk_level);
  els.jdEvalResult.classList.remove("is-hidden");
  els.jdEvalResult.innerHTML = `
    <div class="jd-eval-head">
      <div>
        <strong>${escapeHtml(job.title || "")}</strong>
        <div class="jr-sub">${escapeHtml(job.company || "")} · ${escapeHtml(job.location || "")}</div>
      </div>
      <span class="score-meter ${mod}">${score}</span>
    </div>
    <p class="jd-eval-summary">${escapeHtml(job.score_summary || job.score_explanation || "")}</p>
    <div class="skill-columns">
      <div><h4>Passt</h4><div class="skill-list">${pillList(job.matched_skills)}</div></div>
      <div><h4>Fehlt</h4><div class="skill-list">${pillList(job.missing_skills, "missing")}</div></div>
    </div>
    <div class="btn-row">
      ${data.application ? '<span class="chip green">Anschreiben-Entwurf erstellt</span>' : '<span class="chip status">Kein Entwurf (Score unter Schwelle)</span>'}
      <button class="btn btn-ghost btn-sm" data-open-search="${escapeAttr(job.id || "")}">In „Suche“ öffnen</button>
    </div>`;
  const openBtn = els.jdEvalResult.querySelector("[data-open-search]");
  if (openBtn) {
    openBtn.addEventListener("click", () => {
      state.selectedJobId = openBtn.dataset.openSearch;
      location.hash = "#/suche";
      renderJobs();
      renderDetail();
      renderLetter();
    });
  }
}
function mergeEvaluatedJob(data) {
  if (!data.job) return;
  state.jobs = [data.job, ...state.jobs.filter((job) => job.id !== data.job.id)];
  if (Array.isArray(data.applications)) state.applications = data.applications;
  state.selectedJobId = data.job.id;
  renderJobs();
  renderDetail();
  renderLetter();
  renderTracker();
}

/* --------------------------- Muster & Statistik --------------------- */
async function loadPatterns() {
  if (!els.patternsPanel) return;
  try {
    const params = new URLSearchParams();
    if (state.dbPath) params.set("db_path", state.dbPath);
    const res = await fetch(`/api/patterns?${params}`);
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Auswertung fehlgeschlagen");
    renderPatterns(data);
  } catch (err) {
    els.patternsPanel.innerHTML = `<div class="empty">${escapeHtml(err.message)}</div>`;
  }
}
function renderPatterns(report) {
  if (!report.total) {
    els.patternsPanel.innerHTML =
      '<div class="empty">Noch keine Auswertung — erscheint, sobald Bewerbungen getrackt sind.</div>';
    return;
  }
  const pct = (value) => (value === null || value === undefined ? "–" : Math.round(value * 100) + " %");
  const funnelLabels = {
    draft: "Entwurf", submitted: "Eingereicht", interview: "Interview",
    offer: "Angebot", rejected: "Absage", withdrawn: "Zurückgezogen",
  };
  const funnel = Object.entries(report.funnel || {})
    .map(([stage, count]) => `<div class="pat-stage"><strong>${count}</strong><span>${funnelLabels[stage] || stage}</span></div>`)
    .join("");
  const stale = (report.stale_submitted || []).slice(0, 3)
    .map((item) => `<li>${escapeHtml(item.title)} (${escapeHtml(item.company)}) — ${item.days_waiting} Tage</li>`)
    .join("");
  const insights = (report.insights || []).map((text) => `<li>${escapeHtml(text)}</li>`).join("");
  els.patternsPanel.innerHTML = `
    <div class="pat-funnel">${funnel}</div>
    <div class="pat-stats">
      <div><span>Antwortquote</span><strong>${pct(report.response_rate)}</strong></div>
      <div><span>Interviewquote</span><strong>${pct(report.interview_rate)}</strong></div>
      <div><span>Ø Tage bis Antwort</span><strong>${report.avg_days_to_response ?? "–"}</strong></div>
      <div><span>Überfällig (≥ ${report.stale_after_days} T.)</span><strong>${(report.stale_submitted || []).length}</strong></div>
    </div>
    ${stale ? `<div class="pat-block"><h4>Am längsten ohne Antwort</h4><ul>${stale}</ul></div>` : ""}
    <div class="pat-block"><h4>Erkenntnisse</h4><ul>${insights}</ul></div>`;
}

/* --------------------------- Report & Interview-Prep ---------------- */
async function exportReport() {
  const job = selectedJob();
  if (!job) return;
  setBusy(true);
  try {
    const res = await fetch("/api/export-report", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ job_id: job.id, db_path: state.dbPath || els.dbPathInput.value }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Report fehlgeschlagen");
    if (els.downloadLink && data.download) {
      els.downloadLink.href = data.download;
      els.downloadLink.textContent = "Report laden";
      els.downloadLink.classList.remove("is-hidden");
    }
    showToast("Bewertungsreport erstellt.", "ok");
  } catch (err) {
    showToast(err.message);
  } finally {
    setBusy(false);
  }
}
async function showInterviewPrep() {
  const job = selectedJob();
  if (!job || !els.interviewPrepPanel) return;
  setBusy(true);
  try {
    const params = new URLSearchParams({ job_id: job.id });
    if (state.dbPath) params.set("db_path", state.dbPath);
    if (els.llmInput && els.llmInput.checked) params.set("llm", "1");
    const res = await fetch(`/api/interview-prep?${params}`);
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Interview-Vorbereitung fehlgeschlagen");
    renderInterviewPrep(data.prep || {});
  } catch (err) {
    showToast(err.message);
  } finally {
    setBusy(false);
  }
}
function renderInterviewPrep(prep) {
  const block = (title, entries) => entries && entries.length
    ? `<div class="pat-block"><h4>${escapeHtml(title)}</h4><ul>${entries.map((e) => `<li>${e}</li>`).join("")}</ul></div>`
    : "";
  const skillItems = (prep.fachfragen || []).map(
    (item) => `<strong>${escapeHtml(item.skill)}:</strong> ${escapeHtml(item.frage)}<br><small class="muted-xs">Tipp: ${escapeHtml(item.tipp)}</small>`
  );
  const gapItems = (prep.lueckenfragen || []).map(
    (item) => `<strong>${escapeHtml(item.skill)}:</strong> ${escapeHtml(item.frage)}<br><small class="muted-xs">Tipp: ${escapeHtml(item.tipp)}</small>`
  );
  const plain = (values) => (values || []).map((value) => escapeHtml(value));
  els.interviewPrepPanel.classList.remove("is-hidden");
  els.interviewPrepPanel.innerHTML = `
    <div class="email-audit-head"><strong>Interview-Vorbereitung</strong><span>${escapeHtml(prep.star_hinweis || "")}</span></div>
    ${block("Fachfragen (deine Stärken)", skillItems)}
    ${block("Lücken souverän beantworten", gapItems)}
    ${block("Unternehmen & Motivation", plain(prep.unternehmensfragen))}
    ${block("Verhaltensfragen", plain(prep.verhaltensfragen))}
    ${block("Anzeigenspezifisch (LLM)", plain(prep.llm_fragen))}
    ${block("Deine Rückfragen", plain(prep.rueckfragen))}`;
}

function pillList(values, modifier = "") {
  if (!values || !values.length) return '<span class="empty">-</span>';
  return values.map((v) => `<span class="skill-pill ${modifier}">${escapeHtml(v)}</span>`).join("");
}

/* --------------------------- actions ------------------------------- */
async function generateDraft() {
  const job = selectedJob();
  if (!job) {
    showToast("Bitte zuerst einen Job auswaehlen.");
    return;
  }
  setBusy(true);
  if (els.statusText) els.statusText.textContent = "Anschreiben wird erstellt ...";
  try {
    const res = await fetch("/api/generate-draft", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({
        db_path: state.dbPath || els.dbPathInput.value,
        job_id: job.id,
        llm: Boolean(els.llmInput && els.llmInput.checked),
      }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Entwurf konnte nicht erstellt werden");
    state.applications = data.applications || state.applications;
    state.selectedJobId = job.id;
    if (data.job) {
      const existing = state.jobs.some((item) => item.id === job.id);
      state.jobs = existing
        ? state.jobs.map((item) => (item.id === job.id ? { ...item, ...data.job } : item))
        : [data.job, ...state.jobs];
    }
    els.statusText.textContent = "Anschreiben erstellt";
    showToast("Anschreiben erstellt.", "ok");
    renderJobs();
    renderDetail();
    renderLetter();
    renderTracker();
    if (els.letterBody) els.letterBody.scrollIntoView({ block: "nearest", behavior: "smooth" });
  } catch (err) {
    showToast(err.message);
  } finally {
    setBusy(false);
  }
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
      body: JSON.stringify({ db_path: state.dbPath || els.dbPathInput.value, job_id: job.id, status: els.statusSelect.value, notes: els.notesInput.value }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Status konnte nicht gespeichert werden");
    state.applications = data.applications || state.applications;
    const updated = data.status || {};
    state.jobs = state.jobs.map((item) => (item.id === job.id ? { ...item, status: updated.status || item.status } : item));
    els.statusText.textContent = "Status gespeichert";
    renderJobs(); renderDetail(); renderLetter(); renderTracker();
    refreshFollowUpBadge();
  } catch (err) {
    showToast(err.message);
  } finally {
    setBusy(false);
  }
}
async function sendApplicationEmail() {
  const job = selectedJob();
  if (!job) {
    showToast("Bitte zuerst eine Bewerbung oeffnen.");
    return;
  }
  const app = state.applications.find((item) => item.job_id === job.id);
  if (!app) {
    showToast('Noch kein Anschreiben vorhanden. Bitte zuerst "Entwurf erstellen" klicken.');
    return;
  }
  await loadConfig();
  let dryRun = state.config.email_dry_run !== false;
  const reviewTarget = state.config.email_review_recipient || "deine Kontroll-E-Mail";
  if (dryRun) {
    const enabled = await enableRealEmailSendForCurrentAccount(reviewTarget);
    if (!enabled) return;
    dryRun = false;
  }
  if (!dryRun && !window.confirm(
    `Kontrollpaket jetzt wirklich an ${reviewTarget} senden${els.attachCvInput?.checked ? " (mit CV-Anhang)" : ""}? Der Arbeitgeber wird dabei nicht kontaktiert.`
  )) return;
  setBusy(true);
  if (els.statusText) els.statusText.textContent = "Kontrollpaket wird gesendet ...";
  try {
    const res = await fetch("/api/send-application-email", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({
        db_path: state.dbPath || els.dbPathInput.value,
        job_id: job.id,
        attach_cv: els.attachCvInput ? els.attachCvInput.checked : false,
        confirm_real_send: !dryRun,
        idempotency_key: `web:application:${job.id}:real`,
      }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Kontrollpaket konnte nicht gesendet werden");
    state.applications = data.applications || state.applications;
    const updated = data.status || {};
    state.jobs = state.jobs.map((item) => (item.id === job.id ? { ...item, status: updated.status || item.status } : item));
    const email = data.email || {};
    const att = email.attachments && email.attachments.length ? ` (+ ${email.attachments.join(", ")})` : "";
    els.statusText.textContent = (email.dry_run ? `Dry-run vorbereitet: ${email.recipient}` : `Kontrollpaket gesendet an: ${email.recipient}`) + att;
    showToast((email.dry_run ? "Kontrollpaket Dry-run vorbereitet" : "Kontrollpaket gesendet") + `: ${email.recipient}${att}`, "ok");
    renderJobs(); renderDetail(); renderLetter(); renderTracker();
    refreshFollowUpBadge();
    await loadState({ silent: true });
  } catch (err) {
    showToast(err.message);
  } finally {
    setBusy(false);
  }
}

async function enableRealEmailSendForCurrentAccount(reviewTarget) {
  const identity = state.config.email_identity || {};
  const account = identity.account || {};
  if (!account.smtp_ready) {
    showToast("SMTP ist noch nicht vollstaendig konfiguriert. Bitte zuerst in Einstellungen speichern und SMTP testen.");
    return false;
  }
  if (!state.config.email_review_recipient) {
    showToast("Kontroll-E-Mail fehlt. Bitte in Einstellungen deine eigene Zieladresse eintragen.");
    return false;
  }
  if (!window.confirm(
    `Dry-run ist aktiv. Jetzt fuer dieses Konto deaktivieren und das Kontrollpaket wirklich an ${reviewTarget} senden?`
  )) return false;

  const body = {
    email_address: account.email_address || identity.candidate_email || "",
    email_from: account.email_from || identity.sender || "",
    review_email: account.review_email || state.config.email_review_recipient || "",
    smtp_host: account.smtp_host || "",
    smtp_port: account.smtp_port || 587,
    smtp_user: account.smtp_user || identity.smtp_user || "",
    smtp_password: "",
    imap_host: account.imap_host || "",
    imap_port: account.imap_port || 993,
    imap_user: account.imap_user || identity.imap_user || "",
    imap_password: "",
    imap_folder: account.imap_folder || "INBOX",
    use_tls: account.use_tls !== false,
    dry_run: false,
    sync_dry_run: account.sync_dry_run !== false,
    auto_follow_up_send: account.auto_follow_up_send === true,
  };
  const res = await fetch("/api/email-credentials", {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok || !data.ok) {
    showToast(data.error || "Dry-run konnte nicht deaktiviert werden.");
    return false;
  }
  renderEmailIdentity(data.email_identity);
  await loadConfig();
  if (state.config.email_dry_run !== false) {
    showToast("Dry-run ist weiterhin aktiv. Bitte Einstellungen pruefen.");
    return false;
  }
  return true;
}
async function syncInboxStatus() {
  await loadConfig();
  if (state.config.email_sync_dry_run !== false) {
    const enabled = await enableRealInboxSyncForCurrentAccount();
    if (!enabled) return;
  }
  setBusy(true);
  try {
    const res = await fetch("/api/sync-email-status", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ db_path: state.dbPath || els.dbPathInput.value }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Inbox-Sync fehlgeschlagen");
    state.applications = data.applications || state.applications;
    const updates = data.sync?.updates || [];
    const byJob = new Map(updates.map((item) => [item.job_id, item.stage]));
    state.jobs = state.jobs.map((item) => (byJob.has(item.id) ? { ...item, status: byJob.get(item.id) } : item));
    const message = inboxSyncMessage(data.sync || {});
    els.statusText.textContent = message;
    showToast(message, updates.length ? "ok" : "info");
    renderJobs(); renderDetail(); renderLetter(); renderTracker();
    await loadEmailAudit();
    await loadState({ silent: true });
  } catch (err) {
    showToast(err.message);
  } finally {
    setBusy(false);
  }
}

async function enableRealInboxSyncForCurrentAccount() {
  const identity = state.config.email_identity || {};
  const account = identity.account || {};
  if (!account.imap_ready) {
    showToast("IMAP ist noch nicht vollstaendig konfiguriert. Bitte zuerst in Einstellungen speichern und IMAP testen.");
    return false;
  }
  if (!window.confirm(
    "Inbox-Sync ist im Vorschlagsmodus. Jetzt fuer dieses Konto echte Statusupdates aktivieren?"
  )) return false;

  const body = {
    email_address: account.email_address || identity.candidate_email || "",
    email_from: account.email_from || identity.sender || "",
    review_email: account.review_email || state.config.email_review_recipient || "",
    smtp_host: account.smtp_host || "",
    smtp_port: account.smtp_port || 587,
    smtp_user: account.smtp_user || identity.smtp_user || "",
    smtp_password: "",
    imap_host: account.imap_host || "",
    imap_port: account.imap_port || 993,
    imap_user: account.imap_user || identity.imap_user || "",
    imap_password: "",
    imap_folder: account.imap_folder || "INBOX",
    use_tls: account.use_tls !== false,
    dry_run: account.dry_run !== false,
    sync_dry_run: false,
    auto_follow_up_send: account.auto_follow_up_send === true,
  };
  const res = await fetch("/api/email-credentials", {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok || !data.ok) {
    showToast(data.error || "Inbox-Statusupdates konnten nicht aktiviert werden.");
    return false;
  }
  renderEmailIdentity(data.email_identity);
  await loadConfig();
  if (state.config.email_sync_dry_run !== false) {
    showToast("Inbox-Sync ist weiterhin im Vorschlagsmodus. Bitte Einstellungen pruefen.");
    return false;
  }
  return true;
}

function inboxSyncMessage(sync) {
  const seen = Number(sync.seen || 0);
  const classified = Number(sync.classified || 0);
  const matched = Number(sync.matched || 0);
  const updates = sync.updates || [];
  const mode = sync.dry_run ? "Dry-run" : "Aktualisiert";
  if (!seen) return `${mode}: Keine E-Mails im verbundenen Postfach gelesen`;
  if (!classified) return `${mode}: ${seen} E-Mails gelesen, keine Bewerbungsantwort erkannt`;
  if (!matched) return `${mode}: ${seen} gelesen, ${classified} erkannt, aber keiner Bewerbung zugeordnet`;
  return `${mode}: ${seen} gelesen, ${classified} erkannt, ${matched} zugeordnet, ${updates.length} Status aktualisiert`;
}

async function runEmailAutopilot() {
  setBusy(true);
  try {
    const res = await fetch("/api/run-email-autopilot", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({
        db_path: state.dbPath || els.dbPathInput.value,
        days: followUpDays(),
      }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Autopilot fehlgeschlagen");
    state.applications = data.applications || state.applications;
    const updates = data.sync?.updates || [];
    const byJob = new Map(updates.map((item) => [item.job_id, item.stage]));
    state.jobs = state.jobs.map((item) => (byJob.has(item.id) ? { ...item, status: byJob.get(item.id) } : item));
    const actions = data.actions || [];
    const sent = actions.filter((a) => a.mode === "sent").length;
    const prepared = actions.filter((a) => a.mode === "prepared" || a.mode === "dry_run").length;
    const skipped = actions.filter((a) => a.mode === "skipped" || a.mode === "error").length;
    els.statusText.textContent = `Autopilot: ${updates.length} Inbox-Updates, ${prepared} vorbereitet, ${sent} gesendet, ${skipped} uebersprungen`;
    renderJobs(); renderDetail(); renderLetter(); renderTracker();
    await loadFollowUps();
    await loadEmailAudit();
    await refreshAutopilotSchedule();
  } catch (err) {
    showToast(err.message);
  } finally {
    setBusy(false);
  }
}

async function loadEmailAudit() {
  if (!els.emailAuditPanel) return;
  try {
    const params = new URLSearchParams({ limit: "8" });
    if (state.dbPath || (els.dbPathInput && els.dbPathInput.value)) {
      params.set("db_path", state.dbPath || els.dbPathInput.value);
    }
    const res = await fetch(`/api/email-audit?${params}`);
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Audit nicht verfuegbar");
    renderEmailAudit(data.events || []);
  } catch {
    els.emailAuditPanel.classList.add("is-hidden");
  }
}

function renderEmailAudit(events) {
  if (!els.emailAuditPanel) return;
  if (!events.length) {
    els.emailAuditPanel.classList.add("is-hidden");
    return;
  }
  els.emailAuditPanel.classList.remove("is-hidden");
  els.emailAuditPanel.innerHTML = `
    <div class="email-audit-head"><strong>Mail-Audit</strong><span>${events.length} letzte Ereignisse</span></div>
    <div class="email-audit-list">
      ${events.map((event) => {
        const payload = event.payload || {};
        const label = event.event_type || "event";
        const detail = payload.recipient || `${payload.updates || payload.sync_updates || 0} Updates`;
        return `<div class="email-audit-row"><span>${escapeHtml(label)}</span><strong>${escapeHtml(detail)}</strong><small>${fmtDate(event.created_at)}</small></div>`;
      }).join("")}
    </div>`;
}
async function checkLiveness() {
  const job = selectedJob();
  if (!job) return;
  const btn = els.checkLivenessBtn;
  const previous = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.textContent = "Prüfe …"; }
  try {
    const res = await fetch("/api/check-liveness", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ db_path: state.dbPath || els.dbPathInput.value, job_id: job.id }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Verfügbarkeitsprüfung fehlgeschlagen");
    state.jobs = state.jobs.map((j) => (j.id === job.id ? { ...j, liveness: data.liveness } : j));
    renderJobs(); renderDetail();
    els.statusText.textContent = `Verfügbarkeit: ${livenessLabel(data.liveness.status).text}`;
  } catch (err) {
    showToast(err.message);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = previous; }
  }
}
async function exportApplication() {
  const job = selectedJob();
  if (!job) return;
  const btn = els.exportBtn;
  const previous = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.textContent = "Erstelle …"; }
  if (els.downloadLink) els.downloadLink.classList.add("is-hidden");
  try {
    const res = await fetch("/api/export-application", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ db_path: state.dbPath || els.dbPathInput.value, job_id: job.id }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Export fehlgeschlagen");
    if (els.downloadLink && data.download) {
      els.downloadLink.href = data.download;
      els.downloadLink.textContent = "Paket laden";
      els.downloadLink.classList.remove("is-hidden");
    }
    els.statusText.textContent = `Export erstellt: ${(data.files || []).join(", ")}`;
  } catch (err) {
    showToast(err.message);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = previous; }
  }
}

function escapeHtml(value) {
  return String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}
function escapeAttr(value) { return escapeHtml(value); }

async function changePassword() {
  const current = els.currentPasswordInput?.value || "";
  const next = els.newPasswordInput?.value || "";
  if (next.length < 12) {
    showToast("Das neue Passwort muss mindestens 12 Zeichen haben.");
    return;
  }
  setBusy(true);
  try {
    const res = await fetch("/api/auth/change-password", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ current_password: current, new_password: next }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Passwort konnte nicht geändert werden");
    appBooted = false;
    state.csrfToken = null;
    showAuth();
    setAuthMode("login");
    if (els.authMessage) els.authMessage.textContent = "Passwort geändert. Bitte erneut anmelden.";
  } catch (err) {
    showToast(err.message);
  } finally {
    setBusy(false);
  }
}

async function deleteAccount() {
  const password = els.deletePasswordInput?.value || "";
  const confirmText = els.deleteConfirmInput?.value || "";
  if (confirmText !== "DELETE") {
    showToast("Bitte DELETE exakt eingeben.");
    return;
  }
  if (!window.confirm("Account und alle zugehörigen Daten dauerhaft löschen?")) return;
  setBusy(true);
  try {
    const res = await fetch("/api/auth/delete-account", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ password, confirm: confirmText }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Account konnte nicht gelöscht werden");
    appBooted = false;
    state.csrfToken = null;
    showAuth();
    setAuthMode("login");
    if (els.authMessage) els.authMessage.textContent = "Account und lokale Daten wurden gelöscht.";
  } catch (err) {
    showToast(err.message);
  } finally {
    setBusy(false);
  }
}

/* --------------------------- config + wiring ----------------------- */
async function loadConfig() {
  try {
    const res = await fetch("/api/config");
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "config");
    state.config = data;
    if (els.providerBadge) {
      els.providerBadge.textContent = `${data.llm_provider} / ${data.llm_model}`;
      els.providerBadge.title = data.embedding_model ? `Embedding: ${data.embedding_model}` : "Embedding: lokaler Hash-Fallback";
      els.providerBadge.classList.add("ok");
    }
    if (els.llmInput) els.llmInput.checked = Boolean(data.llm_agents_default);
    if (els.chromaInput) els.chromaInput.checked = Boolean(data.chroma_default);
    renderEmailIdentity(data.email_identity);
    renderOAuthProviders(data.email_oauth_providers || []);
    renderAutopilotSchedule(data.email_autopilot_schedule || {});
    if (els.autopilotIntervalInput) {
      els.autopilotIntervalInput.value = data.email_autopilot_schedule?.interval_minutes || data.email_autopilot_interval_minutes || 15;
    }
    // Recipient is derived from the selected job's posting (see renderDetail), not a fixed address.
    if (els.sendEmailBtn) {
      els.sendEmailBtn.title = data.email_dry_run ? "Dry-run: keine echte E-Mail." : "Sendet die Bewerbung per SMTP.";
    }
    if (els.syncInboxBtn) {
      state.emailSyncReady = Boolean(data.email_sync_ready);
      els.syncInboxBtn.title = data.email_sync_dry_run ? "Dry-run: Statusupdates werden nur vorgeschlagen." : "Liest die Inbox und aktualisiert Status.";
      els.syncInboxBtn.disabled = !state.emailSyncReady;
    }
    if (els.syncInboxFollowupsBtn) {
      els.syncInboxFollowupsBtn.title = data.email_sync_dry_run ? "Dry-run: Statusupdates werden nur vorgeschlagen." : "Liest die Inbox und aktualisiert Status.";
      els.syncInboxFollowupsBtn.disabled = !state.emailSyncReady;
    }
  } catch {
    if (els.providerBadge) { els.providerBadge.textContent = "lokal"; els.providerBadge.classList.add("off"); }
  }
}

if (els.runBtn) els.runBtn.addEventListener("click", runPipeline);
if (els.buildProfileBtn) els.buildProfileBtn.addEventListener("click", buildProfile);
if (els.demoProfileBtn) els.demoProfileBtn.addEventListener("click", loadDemoProfile);
if (els.goPipelineBtn) els.goPipelineBtn.addEventListener("click", () => { location.hash = "#/suche"; });
if (els.copyBtn) els.copyBtn.addEventListener("click", copyLetter);
if (els.generateDraftBtn) els.generateDraftBtn.addEventListener("click", generateDraft);
if (els.checkLivenessBtn) els.checkLivenessBtn.addEventListener("click", checkLiveness);
if (els.exportBtn) els.exportBtn.addEventListener("click", exportApplication);
if (els.saveStatusBtn) els.saveStatusBtn.addEventListener("click", saveStatus);
if (els.sendEmailBtn) els.sendEmailBtn.addEventListener("click", sendApplicationEmail);
if (els.syncInboxBtn) els.syncInboxBtn.addEventListener("click", syncInboxStatus);
if (els.syncInboxFollowupsBtn) els.syncInboxFollowupsBtn.addEventListener("click", syncInboxStatus);
if (els.runEmailAutopilotBtn) els.runEmailAutopilotBtn.addEventListener("click", runEmailAutopilot);
if (els.fillEmailFromProfileBtn) els.fillEmailFromProfileBtn.addEventListener("click", fillEmailFromProfile);
if (els.saveEmailCredentialsBtn) els.saveEmailCredentialsBtn.addEventListener("click", saveEmailCredentials);
if (els.testEmailConnectionBtn) els.testEmailConnectionBtn.addEventListener("click", testEmailConnection);
if (els.clearEmailCredentialsBtn) els.clearEmailCredentialsBtn.addEventListener("click", clearEmailCredentials);
if (els.connectGoogleBtn) els.connectGoogleBtn.addEventListener("click", () => connectOAuthProvider("google"));
if (els.connectMicrosoftBtn) els.connectMicrosoftBtn.addEventListener("click", () => connectOAuthProvider("microsoft"));
if (els.startAutopilotScheduleBtn) els.startAutopilotScheduleBtn.addEventListener("click", () => configureAutopilotSchedule("start"));
if (els.stopAutopilotScheduleBtn) els.stopAutopilotScheduleBtn.addEventListener("click", () => configureAutopilotSchedule("stop"));
if (els.authForm) els.authForm.addEventListener("submit", submitAuth);
if (els.loginTabBtn) els.loginTabBtn.addEventListener("click", () => setAuthMode("login"));
if (els.registerTabBtn) els.registerTabBtn.addEventListener("click", () => setAuthMode("register"));
if (els.logoutBtn) els.logoutBtn.addEventListener("click", logout);
if (els.changePasswordBtn) els.changePasswordBtn.addEventListener("click", changePassword);
if (els.deleteAccountBtn) els.deleteAccountBtn.addEventListener("click", deleteAccount);
function syncThresholdControl() {
  if (!els.thresholdInput || !els.thresholdOut) return;
  const min = Number(els.thresholdInput.min || 0);
  const max = Number(els.thresholdInput.max || 100);
  const value = Number(els.thresholdInput.value || 0);
  const pct = max > min ? ((value - min) / (max - min)) * 100 : value;
  els.thresholdOut.textContent = `${value} %`;
  els.thresholdInput.style.setProperty("--range-pct", `${Math.max(0, Math.min(100, pct))}%`);
  els.thresholdInput.closest(".field-range")?.classList.toggle("is-disabled", els.thresholdInput.disabled);
}
if (els.draftAllInput) {
  els.draftAllInput.addEventListener("change", () => {
    els.thresholdInput.disabled = els.draftAllInput.checked;
    syncThresholdControl();
  });
}
if (els.thresholdInput && els.thresholdOut) {
  els.thresholdInput.addEventListener("input", syncThresholdControl);
  syncThresholdControl();
}
if (els.demoModeBtn) els.demoModeBtn.addEventListener("click", () => setMode(true));
if (els.liveModeBtn) els.liveModeBtn.addEventListener("click", () => setMode(false));
if (els.reviewCvBtn) els.reviewCvBtn.addEventListener("click", reviewCv);
if (els.refreshFollowupsBtn) els.refreshFollowupsBtn.addEventListener("click", loadFollowUps);
if (els.followupDaysInput) els.followupDaysInput.addEventListener("change", loadFollowUps);
if (els.addInboxBtn) els.addInboxBtn.addEventListener("click", addInboxUrl);
if (els.inboxUrlInput) {
  els.inboxUrlInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); addInboxUrl(); }
  });
}
if (els.evaluateJdBtn) els.evaluateJdBtn.addEventListener("click", evaluateJd);
if (els.refreshPatternsBtn) els.refreshPatternsBtn.addEventListener("click", loadPatterns);
if (els.reportBtn) els.reportBtn.addEventListener("click", exportReport);
if (els.interviewPrepBtn) els.interviewPrepBtn.addEventListener("click", showInterviewPrep);

/* --------------------------- init ---------------------------------- */
initTheme();
setAuthMode("login");
showAuth();
checkAuth();
