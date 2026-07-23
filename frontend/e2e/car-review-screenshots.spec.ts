import { test } from '@playwright/test';

const THEMES = ['dark', 'light'] as const;

test.describe.configure({ mode: 'serial' });

async function login(page: import('@playwright/test').Page) {
  // Reuse whichever demo/test login flow the rest of this e2e suite (if
  // any) already relies on -- check frontend/e2e/ for an existing
  // register-or-login helper before writing a new one here. If none
  // exists, register a throwaway user via the UI's own /register form
  // (do not call the API directly -- this spec verifies the real login
  // flow works too, consistent with how every other screenshot in this
  // suite exercises real UI interaction, not shortcuts).
  //
  // Verified directly against frontend/src/components/RegisterForm.tsx
  // and frontend/src/lib/i18n.ts's English strings: the email/password
  // <label> elements wrap their <input> (implicit label association, so
  // getByLabel still works), and the submit button's English text is
  // "Create account" (auth.createAccount), NOT "Register" -- match that
  // exact text, not a /register/i guess. RegisterForm's onSuccess navigates
  // to "/" (the legacy feed) on success, per RegisterPage.tsx.
  await page.goto('/register');
  const email = `car-review-${Date.now()}@example.com`;
  await page.getByLabel(/email/i).fill(email);
  await page.getByLabel(/password/i).fill('demo-password-123');
  await page.getByRole('button', { name: 'Create account' }).click();
  await page.waitForURL((url) => !url.pathname.includes('/register'), { timeout: 10_000 });
}

for (const theme of THEMES) {
  test(`car review page (${theme})`, async ({ page }) => {
    await login(page);
    await page.goto('/car-review');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    // `waitForSelector('text=/./')` matches the nav bar's own text ("FEED",
    // "HOLDINGS", etc.) immediately on page load -- CarReviewPage renders
    // `null` (return null;) until its own async fetch resolves, so that
    // wait condition is satisfied long before real content exists,
    // producing a blank screenshot below the nav (the exact same race
    // class already found and fixed for the Level 1/deep-dive screenshots
    // in Phase 6/7 -- verified by reproducing this blank result first,
    // then confirming the fix below actually shows real content). Wait
    // for a specific demo row's company name instead (RELIANCE.NS sorts
    // first per the backend's `ORDER BY Alert.created_at DESC` and the
    // seed script's per-row offsets).
    await page.waitForSelector('text=Reliance Industries', { timeout: 10_000 });
    await page.screenshot({
      path: `.superpowers-screenshots/car-review-${theme}-${test.info().project.name}.png`,
      fullPage: true,
    });
  });
}
