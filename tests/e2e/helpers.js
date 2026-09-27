import { expect } from '@playwright/test';

export async function login(page, username = 'admin', password = 'admin-correct-password') {
  await page.goto('/login');
  await page.getByLabel(/email ou nom d’utilisateur/i).fill(username);
  await page.getByLabel(/mot de passe/i).fill(password);
  await page.getByRole('button', { name: /se connecter/i }).click();
  await expect(page).toHaveURL(/\/$/);
}
