(() => {
  const inviteForm = document.querySelector('#invite_form');
  const inviteResult = document.querySelector('#invite_result');

  function formatAdminDate(value, locale = 'fr-FR') {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value || '—';
    return new Intl.DateTimeFormat(locale, {
      dateStyle: 'medium', timeStyle: 'short',
    }).format(date);
  }

  function clearElement(element) {
    while (element?.firstChild) element.removeChild(element.firstChild);
  }

  function renderInviteResult(payload, ok) {
    if (!inviteResult) return;
    clearElement(inviteResult);
    inviteResult.classList.remove('hidden');
    inviteResult.classList.toggle('is-error', !ok);

    if (!ok) {
      const message = document.createElement('strong');
      message.textContent = payload.detail || 'Création impossible';
      inviteResult.append(message);
      return;
    }

    const copy = document.createElement('div');
    copy.className = 'admin-invite-result-copy';
    const title = document.createElement('strong');
    title.textContent = 'Invitation créée';
    const detail = document.createElement('span');
    detail.textContent = payload.email_sent
      ? 'Le lien a également été envoyé par email.'
      : (payload.email_error || 'Copie ce lien et transmets-le à la personne invitée.');
    const input = document.createElement('input');
    input.readOnly = true;
    input.value = payload.url;
    input.setAttribute('aria-label', 'Lien d’invitation');
    copy.append(title, detail, input);

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'secondary-btn admin-copy-btn';
    button.textContent = 'Copier le lien';
    button.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(payload.url);
        button.textContent = 'Lien copié';
        window.setTimeout(() => { button.textContent = 'Copier le lien'; }, 1800);
      } catch (_) {
        input.focus();
        input.select();
      }
    });
    inviteResult.append(copy, button);
  }

  function deleteConfirmationText(username) {
    return `Suppression définitive de @${username}.\n\nLe compte, ses analyses, CV, candidatures et fichiers actuels seront effacés. Les sauvegardes existantes resteront inchangées.\n\nSaisis exactement ${username} pour confirmer :`;
  }

  async function deleteUser(userId, confirmation) {
    const response = await fetch(`/api/admin/users/${encodeURIComponent(userId)}`, {
      method: 'DELETE',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({confirmation}),
    });
    let payload = {};
    try { payload = await response.json(); } catch (_) { /* réponse non JSON */ }
    if (!response.ok) throw new Error(payload.detail || 'Suppression du compte impossible.');
    return payload;
  }

  document.querySelectorAll('[data-local-time]').forEach((element) => {
    element.textContent = formatAdminDate(element.getAttribute('datetime'));
  });

  inviteForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = event.submitter;
    if (button) { button.disabled = true; button.textContent = 'Création…'; }
    try {
      const response = await fetch('/api/admin/invitations', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          email: document.querySelector('#invite_email').value || null,
          expires_hours: Number(document.querySelector('#invite_hours').value || 72),
          send_email: document.querySelector('#invite_send').checked,
        }),
      });
      const payload = await response.json();
      renderInviteResult(payload, response.ok);
    } catch (_) {
      renderInviteResult({detail: 'Le serveur est momentanément indisponible.'}, false);
    } finally {
      if (button) { button.disabled = false; button.textContent = 'Créer l’invitation'; }
    }
  });

  document.querySelectorAll('.user-toggle').forEach((button) => button.addEventListener('click', async () => {
    const row = button.closest('[data-user-id]');
    button.disabled = true;
    try {
      const response = await fetch(`/api/admin/users/${row.dataset.userId}?active=${button.dataset.active}`, {method: 'PATCH'});
      if (!response.ok) throw new Error();
      window.location.reload();
    } catch (_) {
      button.disabled = false;
      window.JEV?.showToast('Modification du compte impossible.', 'error');
    }
  }));

  document.querySelectorAll('.user-delete').forEach((button) => button.addEventListener('click', async () => {
    const row = button.closest('[data-user-id]');
    const username = button.dataset.username;
    const confirmation = window.prompt(deleteConfirmationText(username));
    if (confirmation === null) return;
    if (confirmation !== username) {
      window.JEV?.showToast('Le nom d’utilisateur saisi ne correspond pas.', 'error');
      return;
    }
    const actionButtons = row.querySelectorAll('button');
    actionButtons.forEach((item) => { item.disabled = true; });
    try {
      const result = await deleteUser(row.dataset.userId, confirmation);
      if (result.cleanup_pending) {
        window.JEV?.showToast(
          'Compte supprimé. Le nettoyage des fichiers sera retenté au prochain démarrage.',
          'error',
        );
        window.setTimeout(() => window.location.reload(), 2500);
      } else {
        window.location.reload();
      }
    } catch (error) {
      actionButtons.forEach((item) => { item.disabled = false; });
      window.JEV?.showToast(error.message, 'error');
    }
  }));

  document.querySelectorAll('.invite-revoke').forEach((button) => button.addEventListener('click', async () => {
    button.disabled = true;
    try {
      const response = await fetch(`/api/admin/invitations/${button.dataset.id}`, {method: 'DELETE'});
      if (!response.ok) throw new Error();
      window.location.reload();
    } catch (_) {
      button.disabled = false;
      window.JEV?.showToast('Révocation impossible.', 'error');
    }
  }));

  window.JEVAdmin = {formatAdminDate, renderInviteResult, deleteConfirmationText, deleteUser};
})();