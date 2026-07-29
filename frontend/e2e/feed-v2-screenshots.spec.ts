/* Screenshot tour of the card-feed shell (spec v2 §7) -- the swipeable
   news-card UI at "/". Superseded the old /feed-v2 list/detail
   screenshots when that page was retired in favor of the shell. Run with
   the backend seeded via seed_feed_v2_demo.py. */
import { test } from '@playwright/test';

const THEMES = ['dark', 'light'] as const;

for (const theme of THEMES) {
  test(`shell card front (${theme})`, async ({ page }) => {
    await page.goto('/');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    await page.waitForSelector('.card', { timeout: 10_000 });
    await page.screenshot({
      path: `.superpowers-screenshots/shell-card-front-${theme}-${test.info().project.name}.png`,
    });
  });

  test(`shell card back - ripple layers (${theme})`, async ({ page }) => {
    await page.goto('/');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    const front = page.locator('.face.front').first();
    await front.waitFor({ timeout: 10_000 });
    await front.click();
    // Card-back layers arrive via the detail fetch after the flip.
    await page.waitForSelector('.layer', { timeout: 10_000 });
    await page.waitForTimeout(600); // let the flip animation settle
    await page.screenshot({
      path: `.superpowers-screenshots/shell-card-back-${theme}-${test.info().project.name}.png`,
    });
  });

  test(`shell card back - timeline tab (${theme})`, async ({ page }) => {
    await page.goto('/');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    const front = page.locator('.face.front').first();
    await front.waitFor({ timeout: 10_000 });
    await front.click();
    await page.waitForSelector('.layer', { timeout: 10_000 });
    await page.getByRole('button', { name: 'Timeline' }).first().click();
    await page.waitForTimeout(600);
    await page.screenshot({
      path: `.superpowers-screenshots/shell-card-timeline-${theme}-${test.info().project.name}.png`,
    });
  });

  test(`shell deep-dive sheet (${theme})`, async ({ page }) => {
    await page.goto('/');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    const front = page.locator('.face.front').first();
    await front.waitFor({ timeout: 10_000 });
    await front.click();
    const row = page.locator('.srow').first();
    await row.waitFor({ timeout: 10_000 });
    await row.click();
    await page.waitForSelector('text=What they do', { timeout: 10_000 });
    await page.waitForTimeout(400); // sheet slide-up
    await page.screenshot({
      path: `.superpowers-screenshots/shell-deep-dive-${theme}-${test.info().project.name}.png`,
    });
  });

  test(`shell discover (${theme})`, async ({ page }) => {
    await page.goto('/');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    await page.getByRole('button', { name: 'Discover' }).click();
    await page.waitForTimeout(800);
    await page.screenshot({
      path: `.superpowers-screenshots/shell-discover-${theme}-${test.info().project.name}.png`,
    });
  });

  test(`shell directory (${theme})`, async ({ page }) => {
    await page.goto('/');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    await page.getByRole('button', { name: 'Directory' }).click();
    await page.waitForTimeout(800);
    await page.screenshot({
      path: `.superpowers-screenshots/shell-directory-${theme}-${test.info().project.name}.png`,
    });
  });
}
