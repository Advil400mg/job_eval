import { test, expect } from '@playwright/test';
import { login } from './helpers.js';

test('connexion refusée puis réussie et déconnexion', async ({ page }) => {
  await page.goto('/login');
  await page.getByLabel(/email ou nom d['’]utilisateur/i).fill('admin');
  await page.getByLabel(/mot de passe/i).fill('incorrect-password');
  await page.getByRole('button', { name: /se connecter/i }).click();
  await expect(page.getByText(/identifiant ou mot de passe incorrect/i)).toBeVisible();

  await login(page);
  await expect(page.getByRole('navigation', { name: /navigation principale/i })).toBeVisible();
  await page.getByRole('button', { name: /déconnexion/i }).click();
  await expect(page).toHaveURL(/\/login/);
});

test('les pages protégées redirigent et les droits admin sont appliqués', async ({ browser }) => {
  const anonymous = await browser.newPage();
  await anonymous.goto('/offers');
  await expect(anonymous).toHaveURL(/\/login\?next=/);
  await anonymous.close();

  const member = await browser.newPage();
  await login(member, 'member', 'member-correct-password');
  await expect(member.getByRole('link', { name: /administration/i })).toHaveCount(0);
  const response = await member.goto('/admin');
  expect(response.status()).toBe(403);
  await member.close();
});
