const inviteForm = document.querySelector('#invite_form');
const inviteResult = document.querySelector('#invite_result');

inviteForm?.addEventListener('submit', async (event) => {
  event.preventDefault();
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
  inviteResult.classList.remove('hidden');
  if (!response.ok) {
    inviteResult.textContent = payload.detail || 'Création impossible';
    return;
  }
  inviteResult.innerHTML = `<p><strong>Lien à copier :</strong></p><input readonly value="${payload.url}"><p>${payload.email_sent ? 'Email envoyé.' : (payload.email_error || 'Lien créé.')}</p>`;
});

document.querySelectorAll('.user-toggle').forEach((button) => button.addEventListener('click', async () => {
  const row = button.closest('[data-user-id]');
  const response = await fetch(`/api/admin/users/${row.dataset.userId}?active=${button.dataset.active}`, {method: 'PATCH'});
  if (response.ok) window.location.reload();
}));

document.querySelectorAll('.invite-revoke').forEach((button) => button.addEventListener('click', async () => {
  const response = await fetch(`/api/admin/invitations/${button.dataset.id}`, {method: 'DELETE'});
  if (response.ok) window.location.reload();
}));
