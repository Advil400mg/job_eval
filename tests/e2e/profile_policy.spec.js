import { test, expect } from '@playwright/test';
import { login } from './helpers.js';

test('adoption explicite du profil personnalisable et confirmation avant évaluation', async ({ page }) => {
  await login(page);
  await page.goto('/profile');
  await page.getByRole('button', { name: 'Passer au profil personnalisable' }).click();
  await page.getByRole('button', { name: 'Créer la version à vérifier' }).click();
  await expect(page.locator('#profile_confirmed')).toBeVisible();
  await page.goto('/');
  await expect(page.getByText(/confirmez.*profil|profil.*confirmer/i).first()).toBeVisible();
  const blocked = await page.request.post('/api/evaluate/manual', {
    headers: { Origin: 'http://127.0.0.1:8769' },
    data: { url: 'https://example.test/job', text: 'Example offer '.repeat(80) },
  });
  expect(blocked.status()).toBe(428);
  await page.goto('/profile');
  await page.locator('#candidate_years').fill('3');
  await page.locator('#reject_experience_years').fill('');
  await page.locator('#locations').fill('France\nBerlin, DE');
  await page.locator('#contract_types').selectOption(['permanent', 'freelance']);
  await page.locator('#profile_confirmed').check();
  await expect(page.locator('#profile_preview')).toContainText('Berlin, DE');
  await page.locator('#profile_save').click();
  await expect(page.getByText('Profil enregistré.')).toBeVisible();
  const current = await page.request.get('/api/profile');
  const profile = (await current.json()).profile;
  expect(profile.search.confirmed).toBe(true);
  expect(profile.search.locations).toEqual(['France', 'Berlin, DE']);
  expect(profile.search.contract_types).toEqual(['permanent', 'freelance']);
});
