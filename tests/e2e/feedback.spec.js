import { test, expect } from '@playwright/test';
import { login } from './helpers.js';

const legacyUrl = 'https://jobs.example.test/security-engineer';
const reviewUrl = 'https://jobs.example.test/review-required';

async function openOffer(page, title) {
  await page.goto('/offers');
  const row = page.locator('.offer-row').filter({ hasText: title });
  await expect(row).toHaveCount(1);
  await row.locator('[data-open-offer]').click();
  await expect(page.locator('#offer_drawer')).toHaveClass(/open/);
  return row;
}

test('une ancienne évaluation reste lisible et son feedback gère un conflit de révision', async ({ page }) => {
  await login(page);
  await openOffer(page, 'Security Engineer');
  await expect(page.locator('#offer_detail')).toContainText('Aucun critère enregistré');
  await expect(page.locator('.criterion-evidence')).toHaveCount(0);
  const form = page.locator('#feedback_form');
  await expect(form.locator('button[type="submit"]')).toBeEnabled();
  await form.locator('select[name="verdict"]').selectOption('bad_reason');
  await form.locator('textarea[name="note"]').fill('Motif corrigé dans ce navigateur');
  await form.locator('button[type="submit"]').click();
  await expect(page.locator('#feedback_state')).toContainText('Retour enregistré');

  await openOffer(page, 'Security Engineer');
  await expect(form.locator('select[name="verdict"]')).toHaveValue('bad_reason');
  await expect(form.locator('textarea[name="note"]')).toHaveValue('Motif corrigé dans ce navigateur');
  const competingWrite = await page.evaluate(async (url) => {
    const history = await (await fetch(`/api/offers/history?url=${encodeURIComponent(url)}`)).json();
    const response = await fetch(`/api/evaluations/${encodeURIComponent(history.offer.run_id)}/feedback`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, verdict: 'correct', note: 'Autre onglet', revision: 1 }),
    });
    return response.status;
  }, legacyUrl);
  expect(competingWrite).toBe(200);
  await form.locator('textarea[name="note"]').fill('Ne pas écraser');
  await form.locator('button[type="submit"]').click();
  await expect(page.locator('#feedback_state')).toContainText(/modifié dans un autre onglet/i);
  await expect(form.locator('button[type="submit"]')).toBeEnabled();
});

test('preuve hostile échappée, revue accessible au clavier et largeur mobile', async ({ page }) => {
  await login(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/offers');
  const row = page.locator('.offer-row').filter({ hasText: 'Junior IAM à examiner' });
  await expect(row).toHaveCount(1);
  await row.focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('#drawer_close')).toBeFocused();
  await expect(page.locator('#offer_detail')).toContainText('Revue requise');
  await expect(page.locator('#offer_detail')).toContainText('première mission non confirmée');
  await expect(page.locator('.criterion-evidence')).toContainText('<img src=x onerror=alert(1)>');
  await expect(page.locator('#offer_detail img')).toHaveCount(0);
  await expect(page.locator('.fact-list')).toContainText('Contrat');
  await expect(page.locator('#feedback_form button[type="submit"]')).toBeEnabled();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  await page.keyboard.press('Escape');
  await expect(row).toBeFocused();
});

test('un autre compte ne lit ni ne corrige le feedback du propriétaire', async ({ browser }) => {
  const admin = await browser.newPage();
  await login(admin);
  const runId = await admin.evaluate(async (url) => {
    const response = await fetch(`/api/offers/history?url=${encodeURIComponent(url)}`);
    return (await response.json()).offer.run_id;
  }, reviewUrl);
  await admin.close();

  const member = await browser.newPage();
  await login(member, 'member', 'member-correct-password');
  const statuses = await member.evaluate(async ({ url, runId }) => {
    const endpoint = `/api/evaluations/${encodeURIComponent(runId)}/feedback`;
    const get = await fetch(`${endpoint}?url=${encodeURIComponent(url)}`);
    const put = await fetch(endpoint, { method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, verdict: 'correct', note: '', revision: 0 }),
    });
    return [get.status, put.status];
  }, { url: reviewUrl, runId });
  expect(statuses).toEqual([404, 404]);
  await member.goto('/offers');
  await expect(member.locator('.offer-row')).toHaveCount(0);
  await member.close();
});
