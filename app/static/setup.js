const form = document.querySelector("#setup_form");
const button = document.querySelector("#setup_submit");
const status = document.querySelector("#setup_status");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = document.querySelector("#cv_pdf").files[0];
  if (!file) {
    status.textContent = "Sélectionnez un CV PDF.";
    return;
  }
  button.disabled = true;
  status.textContent = "Extraction et analyse du CV en cours… cela peut prendre quelques minutes.";
  try {
    const response = await fetch("/api/onboarding", { method: "POST", body: new FormData(form) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Initialisation impossible");
    status.textContent = `Profil créé pour ${payload.candidate}. Chargement de l'application…`;
    window.location.reload();
  } catch (error) {
    status.textContent = "Erreur : " + error.message;
    button.disabled = false;
  }
});
