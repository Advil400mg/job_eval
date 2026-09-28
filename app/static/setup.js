const form = document.querySelector("#setup_form");
const button = document.querySelector("#setup_submit");
const status = document.querySelector("#setup_status");
const fileInput = document.querySelector("#cv_pdf");
const POLL_INTERVAL_MS = 2000;
const MAX_POLL_FAILURES = 10;
let pollTimer = null;
let pollFailures = 0;

function detailMessage(detail, fallback = "Initialisation impossible") {
  if (typeof detail === "string" && detail) return detail;
  if (detail && typeof detail.message === "string" && detail.message) return detail.message;
  return fallback;
}

function renderOnboarding(setup) {
  const job = setup && setup.job ? setup.job : {};
  const apiKeySet = setup && Object.hasOwn(setup, "api_key_set")
    ? Boolean(setup.api_key_set)
    : form.dataset.apiKeySet === "true";

  if (setup && !setup.needed) {
    button.disabled = true;
    status.textContent = "Profil créé. Chargement de l’application…";
    window.location.reload();
    return "done";
  }
  if (setup && setup.processing) {
    button.disabled = true;
    status.textContent = "Analyse du CV en cours… Vous pouvez quitter ou actualiser cette page.";
    return "running";
  }
  button.disabled = !apiKeySet;
  if ((job.status === "failed" || job.status === "interrupted") && job.last_error) {
    status.textContent = "Erreur : " + job.last_error;
    return job.status;
  }
  return "idle";
}

function schedulePoll(delay = POLL_INTERVAL_MS) {
  if (pollTimer !== null) clearTimeout(pollTimer);
  pollTimer = setTimeout(pollOnboarding, delay);
}

async function pollOnboarding() {
  try {
    const response = await fetch("/api/onboarding");
    const payload = await response.json();
    if (!response.ok) throw new Error(detailMessage(payload.detail, "Statut indisponible"));
    pollFailures = 0;
    const state = renderOnboarding(payload);
    if (state === "running") schedulePoll();
  } catch (error) {
    pollFailures += 1;
    button.disabled = true;
    if (pollFailures >= MAX_POLL_FAILURES) {
      pollTimer = null;
      status.textContent = "La vérification de l’analyse est indisponible. Actualisez la page pour réessayer.";
      return;
    }
    status.textContent = "Analyse en cours — vérification momentanément impossible. Nouvelle tentative…";
    schedulePoll(3000);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = fileInput.files[0];
  if (!file) {
    status.textContent = "Sélectionnez un CV PDF.";
    return;
  }
  button.disabled = true;
  status.textContent = "Extraction et analyse du CV en cours… cela peut prendre quelques minutes.";
  try {
    const data = new FormData(form);
    data.set("contract_types", data.getAll("contract_types").join(","));
    const response = await fetch("/api/onboarding", { method: "POST", body: data });
    const payload = await response.json();
    if (!response.ok) {
      if (payload.detail && payload.detail.onboarding) {
        const state = renderOnboarding(payload.detail.onboarding);
        if (state === "running") schedulePoll();
        return;
      }
      throw new Error(detailMessage(payload.detail));
    }
    status.textContent = `Profil créé pour ${payload.candidate}. Chargement de l’application…`;
    window.location.reload();
  } catch (error) {
    status.textContent = "Erreur : " + error.message;
    button.disabled = form.dataset.apiKeySet !== "true";
  }
});

const initialJobStatus = form.dataset.processing === "true" ? "running" :
  (form.dataset.error ? "failed" : null);
const initialState = renderOnboarding({
  needed: true,
  processing: form.dataset.processing === "true",
  api_key_set: form.dataset.apiKeySet === "true",
  job: { status: initialJobStatus, last_error: form.dataset.error || null },
});
if (initialState === "running") schedulePoll(0);

const manualForm = document.querySelector("#manual_setup_form");
if (manualForm) manualForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const submit = document.querySelector("#manual_setup_submit");
  const message = document.querySelector("#manual_setup_status");
  submit.disabled = true;
  message.textContent = "Création du profil…";
  const data = new FormData(manualForm);
  const payload = Object.fromEntries(data.entries());
  payload.candidate_years = payload.candidate_years ? Number(payload.candidate_years) : null;
  payload.reject_experience_years = payload.reject_experience_years ? Number(payload.reject_experience_years) : null;
  payload.max_age_days = Number(payload.max_age_days);
  payload.contract_types = data.getAll("contract_types");
  try {
    const response = await fetch("/api/onboarding/manual", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(detailMessage(result.detail));
    message.textContent = "Profil créé. Ouverture de votre profil…";
    window.location.assign("/profile");
  } catch (error) {
    message.textContent = "Erreur : " + error.message;
    submit.disabled = false;
  }
});

window.JEVSetup = { detailMessage, renderOnboarding, pollOnboarding };
