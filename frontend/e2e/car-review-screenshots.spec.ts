/* Screenshot of the shell's Review view (spec v2 §4.7) -- the CAR
   reaction-review bar cards. The standalone /car-review page was retired
   with the card-feed shell rebuild; Review now lives behind the shell's
   bottom nav. Run with the backend seeded via seed_car_review_demo.py. */
import { test } from '@playwright/test';

const THEMES = ['dark', 'light'] as const;

test.describe.configure({ mode: 'serial' });

async function login(page: import('@playwright/test').Page) {
  // Register a throwaway user via the UI's own /register form (this spec
  // verifies the real login flow too, consistent with the rest of the
  // suite). RegisterForm's onSuccess navigates to "/" -- now the shell.
  await page.goto('/register');
  const email = `car-review-${Date.now()}@example.com`;
  await page.getByLabel(/email/i).fill(email);
  await page.getByLabel(/password/i).fill('demo-password-123');
  await page.getByRole('button', { name: 'Create account' }).click();
  await page.waitForURL((url) => !url.pathname.includes('/register'), { timeout: 10_000 });
}

for (const theme of THEMES) {
  test(`shell review view (${theme})`, async ({ page }) => {
    await login(page);
    await page.goto('/');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    await page.getByRole('button', { name: 'Review' }).click();
    // The view renders its cards only once its own fetch resolves -- wait
    // for a seeded row's headline, not just any text.
    await page.waitForSelector('text=Crude oil supply shock hits refiners', { timeout: 10_000 });
    await page.screenshot({
      path: `.superpowers-screenshots/shell-review-${theme}-${test.info().project.name}.png`,
    });
  });
}
