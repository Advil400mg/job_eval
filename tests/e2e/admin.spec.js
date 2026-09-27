import { test, expect } from '@playwright/test';
import { login } from './helpers.js';

test('invitation, inscription et suppression administrateur complète', async ({ browser }) => {
  const admin = await browser.newPage();
  await login(admin);
  await admin.goto('/admin');
  await admin.getByLabel(/email réservé/i).fill('new-user@example.test');
  await admin.getByRole('button', { name: /créer l’invitation/i }).click();
  await expect(admin.getByText('Invitation créée')).toBeVisible();
  const invitationUrl = await admin.getByLabel(/lien d’invitation/i).inputValue();

  const guest = await browser.newPage();
  await guest.goto(invitationUrl);
  await guest.getByLabel(/^Nom d’utilisateur/i).fill('newuser');
  await expect(guest.getByLabel(/^Email/i)).toHaveValue('new-user@example.test');
  await guest.getByLabel(/nom affiché/i).fill('New User');
  await guest.getByLabel(/^Mot de passe/i).fill('new-user-correct-password');
  await guest.getByRole('button', { name: /créer mon compte/i }).click();
  await expect(guest).toHaveURL(/\/$/);
  await guest.close();

  await admin.reload();
  const row = admin.locator('[data-user-id]').filter({ hasText: '@newuser' });
  await expect(row).toBeVisible();
  await row.getByRole('button', { name: 'Supprimer' }).click();
  const dialog = admin.locator('#action_dialog');
  await expect(dialog).toBeVisible();
  await dialog.locator('#action_dialog_input').fill('newuser');
  await dialog.getByRole('button', { name: /supprimer définitivement/i }).click();
  await expect(row).toHaveCount(0);
  await admin.close();
});

test('journal audit, diagnostic et sauvegarde sont opérationnels', async ({ page }) => {
  await login(page);
  await page.goto('/admin/audit');
  await expect(page.getByRole('heading', { name: /journal d’audit/i })).toBeVisible();
  await expect(page.locator('.audit-event').first()).toBeVisible();
  await expect(page.locator('#audit_summary')).toContainText(/événement/);

  await page.goto('/admin/diagnostics');
  await expect(page.getByRole('heading', { name: 'Diagnostic', exact: true })).toBeVisible();
  await expect(page.locator('#diagnostics_status')).toContainText(/État global/);
  await expect(page.locator('#diagnostics_checks .diagnostic-check').first()).toBeVisible();

  const created = await page.evaluate(async () => {
    const response = await fetch('/api/backups', { method: 'POST' });
    if (!response.ok) throw new Error(await response.text());
    return response.json();
  });
  expect(created.verified).toBe(true);
  const verified = await page.evaluate(async (name) => {
    const response = await fetch(`/api/backups/${encodeURIComponent(name)}/verify`, { method: 'POST' });
    if (!response.ok) throw new Error(await response.text());
    return response.json();
  }, created.name);
  expect(verified.verified).toBe(true);
});
