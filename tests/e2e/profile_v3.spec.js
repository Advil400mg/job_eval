import { randomUUID } from 'node:crypto';
import { test, expect } from '@playwright/test';
import { login } from './helpers.js';

// Real APIs and isolated synthetic accounts; no CV upload or model call.
const password = 'guided-v3-correct-password';
let profileUser;
let pendingUser;
let manualUser;
let baseline;

async function createAccount(request, origin) {
  const signedIn = await request.post('/login', {
    form: { identifier: 'admin', password: 'admin-correct-password', next: '/' },
    maxRedirects: 0,
  });
  expect(signedIn.status()).toBe(303);
  const invitation = await request.post('/api/admin/invitations', {
    headers: { Origin: origin }, data: { email: null, expires_hours: 1, send_email: false },
  });
  expect(invitation.ok()).toBe(true);
  const token = (await invitation.json()).token;
  const username = 'guided-' + randomUUID().slice(0, 12);
  const registered = await request.post('/register', {
    headers: { Origin: origin },
    form: { token, username, password, display_name: 'Guided example' },
    maxRedirects: 0,
  });
  expect(registered.status()).toBe(303);
  const me = await (await request.get('/api/auth/me')).json();
  expect(me.username).toBe(username);
  expect(me.role).toBe('user');
  expect((await (await request.get('/api/onboarding')).json()).needed).toBe(true);
  return username;
}

async function selectStep(page, step) {
  await page.locator(`[role="tab"][data-step="${step}"]`).click();
  await expect(page.locator(`[role="tabpanel"][data-step="${step}"]`)).toBeVisible();
}

test.beforeAll(async ({ browser, baseURL }) => {
  const context = await browser.newContext({ baseURL });
  const request = context.request;
  try {
    pendingUser = await createAccount(request, baseURL);
    manualUser = await createAccount(request, baseURL);
    profileUser = await createAccount(request, baseURL);
    const created = await request.post('/api/onboarding/manual', {
      headers: { Origin: baseURL },
      data: { name: 'Guided example', target_roles: 'Analyst', skills: 'Python',
        languages_line: 'English B2', locations: 'France', preferred_locations: '',
        seniority: 'junior', candidate_years: 1, reject_experience_years: null,
        contract_types: ['permanent'], max_age_days: 30 },
    });
    expect(created.ok()).toBe(true);
    baseline = (await (await request.get('/api/profile')).json()).profile;
    expect(baseline.search.policy_version).toBe(2);
  } finally { await context.close(); }
});

test.beforeEach(async ({ page, baseURL }) => {
  await login(page, profileUser, password);
  const current = await (await page.request.get('/api/profile')).json();
  const reset = await page.request.put('/api/profile', {
    headers: { Origin: baseURL },
    data: { profile: structuredClone(baseline), expected_revision: current.revision },
  });
  expect(reset.ok()).toBe(true);
  const loaded = await (await page.request.get('/api/profile')).json();
  expect(loaded.profile.search.confirmed).toBe(baseline.search.confirmed);
});

test('profil guidé : liens directs, clavier et relations ARIA', async ({ page }) => {
  await page.goto('/profile#preferences');
  const tabs = page.getByRole('tab');
  await expect(tabs).toHaveCount(3);
  await expect(page.locator('#step_preferences')).toBeVisible();
  await expect(page.locator('#step_facts')).toBeHidden();
  await expect(page.locator('#step_rules')).toBeHidden();
  await page.locator('#tab_preferences').focus();
  await page.keyboard.press('ArrowLeft');
  await expect(page.locator('#tab_facts')).toBeFocused();
  await expect(page.locator('#step_facts')).toBeVisible();
  await page.keyboard.press('End');
  await expect(page.locator('#tab_rules')).toBeFocused();
  await expect(page.locator('#step_rules')).toHaveAttribute('aria-labelledby', 'tab_rules');
  await expect(page.locator('#tab_facts')).toHaveAttribute('tabindex', '-1');
  await page.keyboard.press('Home');
  await expect(page.locator('#tab_facts')).toBeFocused();
  await expect(page.locator('#profile_history')).toBeVisible();
  await expect(page.locator('#restore_form')).toBeVisible();
});

test('profil : sauvegarder depuis chaque étape conserve les faits, préférences et confirmation', async ({ page }) => {
  await page.goto('/profile');
  await page.locator('#candidate_years').fill('1.5');
  await page.locator('#profile_save').click();
  await expect(page.getByText('Profil enregistré.', { exact: true })).toBeVisible();
  await selectStep(page, 'preferences');
  await page.locator('#locations').fill('France\nBerlin, DE');
  await page.locator('#contract_types').selectOption(['permanent', 'freelance']);
  await page.locator('#profile_save').click();
  await expect.poll(async () => (await (await page.request.get('/api/profile')).json()).profile.search.locations)
    .toEqual(['France', 'Berlin, DE']);
  await selectStep(page, 'rules');
  await page.locator('#profile_confirmed').check();
  await expect(page.locator('#profile_preview')).toContainText('Berlin, DE');
  await page.locator('#profile_save').click();
  await expect.poll(async () => (await (await page.request.get('/api/profile')).json()).profile.search.confirmed).toBe(true);
  const current = (await (await page.request.get('/api/profile')).json()).profile;
  expect(current.search.experience_filter.candidate_years).toBe(1.5);
  expect(current.search.contract_types).toEqual(['permanent', 'freelance']);
  expect(current.candidate).toEqual(baseline.candidate);
  expect((await (await page.request.get('/api/onboarding')).json()).cv_available).toBe(false);
  await page.reload();
  await expect(page.locator('#candidate_years')).toHaveValue('1.5');
});

test('validation native : ouvrir le premier champ invalide, même si plusieurs étapes sont invalides', async ({ page }) => {
  await page.goto('/profile');
  const errors = [];
  page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()); });
  let saves = 0;
  await page.route('**/api/profile', async (route) => {
    if (route.request().method() === 'PUT') saves += 1;
    await route.continue();
  });
  await page.locator('#candidate_name').fill('');
  await selectStep(page, 'preferences');
  await page.locator('#minimum_global_score').fill('');
  await selectStep(page, 'rules');
  const criterion = page.locator('[data-field="name"]').first();
  const criterionName = await criterion.inputValue();
  await criterion.fill('');
  await page.locator('#profile_save').click();
  await expect(page.locator('#candidate_name')).toBeVisible();
  await expect(page.locator('#candidate_name')).toBeFocused();
  await expect(page.locator('#profile_errors')).toBeVisible();
  expect(saves).toBe(0);
  await page.locator('#candidate_name').fill('Guided example');
  await page.locator('#profile_save').click();
  await expect(page.locator('#minimum_global_score')).toBeFocused();
  await page.locator('#minimum_global_score').fill('68');
  await page.locator('#profile_save').click();
  await expect(criterion).toBeFocused();
  await criterion.fill(criterionName);
  await page.locator('#profile_save').click();
  await expect(page.getByText(/Profil enregistré\.|Aucune modification\./).first()).toBeVisible();
  expect(saves).toBe(1);
  expect(errors.filter((message) => /not focusable/i.test(message))).toEqual([]);
});

test('révision concurrente : erreur toujours visible et aucune édition perdue', async ({ page, baseURL }) => {
  await page.goto('/profile');
  const original = await (await page.request.get('/api/profile')).json();
  await selectStep(page, 'preferences');
  await page.locator('#locations').fill('Berlin, DE');
  const otherTab = structuredClone(original.profile);
  otherTab.minimum_global_score = 70;
  const saved = await page.request.put('/api/profile', {
    headers: { Origin: baseURL }, data: { profile: otherTab, expected_revision: original.revision },
  });
  expect(saved.ok()).toBe(true);
  await selectStep(page, 'facts');
  const rejected = page.waitForResponse((response) => response.url().endsWith('/api/profile') && response.request().method() === 'PUT');
  await page.locator('#profile_save').click();
  expect((await rejected).status()).toBe(409);
  await expect(page.locator('#profile_errors')).toBeVisible();
  await expect(page.locator('#profile_save')).toBeEnabled();
  await selectStep(page, 'preferences');
  await expect(page.locator('#locations')).toHaveValue('Berlin, DE');
  const stored = (await (await page.request.get('/api/profile')).json()).profile;
  expect(stored.minimum_global_score).toBe(70);
  expect(stored.search.locations).toEqual(original.profile.search.locations);
});

test('initialisation : parcours séparés, valeurs conservées et validation sans requête', async ({ page }) => {
  await login(page, pendingUser, password);
  await selectStep(page, 'manual');
  await page.locator('#manual_setup_form [name="name"]').fill('Draft example');
  let submissions = 0;
  await page.route('**/api/onboarding/manual', async (route) => {
    if (route.request().method() === 'POST') submissions += 1;
    await route.continue();
  });
  await page.locator('#manual_setup_submit').click();
  await expect(page.locator('#manual_setup_form [name="target_roles"]')).toBeFocused();
  expect(submissions).toBe(0);
  await selectStep(page, 'cv');
  await expect(page.locator('#cv_pdf')).toBeVisible();
  await selectStep(page, 'manual');
  await expect(page.locator('#manual_setup_form [name="name"]')).toHaveValue('Draft example');
  expect(await page.evaluate(() => document.querySelector('#setup_form').reportValidity())).toBe(false);
  await expect(page.locator('#step_cv')).toBeVisible();
  await expect(page.locator('#cv_pdf')).toBeFocused();
});

test('sans JavaScript : les trois étapes et les deux parcours restent visibles', async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false, viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  try {
    await login(page, profileUser, password);
    await page.goto('/profile');
    for (const panel of ['#step_facts', '#step_preferences', '#step_rules']) await expect(page.locator(panel)).toBeVisible();
    await login(page, pendingUser, password);
    await expect(page.locator('#step_cv')).toBeVisible();
    await expect(page.locator('#step_manual')).toBeVisible();
    await expect(page.getByText('JavaScript est nécessaire pour créer le profil', { exact: false })).toBeVisible();
  } finally { await context.close(); }
});

test('initialisation responsive : deux thèmes, deux parcours et seuils CSS', async ({ page }) => {
  test.setTimeout(120_000);
  await login(page, pendingUser, password);
  let checks = 0;
  for (const theme of ['light', 'dark']) {
    if (await page.locator('html').getAttribute('data-theme') !== theme) await page.locator('[data-theme-toggle]').click();
    for (const width of [390, 679, 680, 681, 979, 980, 981, 1280]) {
      await page.setViewportSize({ width, height: 844 });
      for (const step of ['cv', 'manual']) {
        await selectStep(page, step);
        expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth), `${theme}/${width}/${step}`).toBeLessThanOrEqual(1);
        checks += 1;
      }
    }
  }
  console.log(`v3 onboarding layout checks: ${checks}`);
});

test('création manuelle réelle : profil non confirmé, critères conservés et génération CV indisponible', async ({ page }) => {
  await login(page, manualUser, password);
  await selectStep(page, 'manual');
  const form = page.locator('#manual_setup_form');
  await form.locator('[name="name"]').fill('Manual example');
  await form.locator('[name="target_roles"]').fill('Analyst');
  await form.locator('[name="skills"]').fill('Python\nSQL');
  await form.locator('[name="languages_line"]').fill('English B2');
  await form.locator('[name="locations"]').fill('France\nBerlin, DE');
  await form.locator('[name="candidate_years"]').fill('1');
  await form.locator('[name="contract_types"]').selectOption(['permanent', 'freelance']);
  await page.locator('#manual_setup_submit').click();
  await expect(page).toHaveURL(/\/profile$/);
  await expect(page.locator('#candidate_name')).toHaveValue('Manual example');
  const current = (await (await page.request.get('/api/profile')).json()).profile;
  expect(current.search.confirmed).toBe(false);
  expect(current.search.locations).toEqual(['France', 'Berlin, DE']);
  expect(current.search.contract_types).toEqual(['permanent', 'freelance']);
  expect(current.candidate_facts.skills).toEqual(['Python', 'SQL']);
  const status = await (await page.request.get('/api/onboarding')).json();
  expect(status.needed).toBe(false);
  expect(status.cv_available).toBe(false);
  await selectStep(page, 'rules');
  await expect(page.locator('#profile_confirmed')).not.toBeChecked();
});
