import { test } from '@playwright/test';

const THEMES = ['dark', 'light'] as const;

function hideBottomNav(page: import('@playwright/test').Page) {
  return page.evaluate(() => {
    const bottomNav = document.querySelector('nav.fixed') as HTMLElement | null;
    if (bottomNav) bottomNav.style.display = 'none';
  });
}

for (const theme of THEMES) {
  test(`feed-v2 Level 0 (${theme})`, async ({ page }) => {
    await page.goto('/feed-v2');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    await page.waitForSelector('text=/./', { timeout: 10_000 }).catch(() => {});
    await page.screenshot({
      path: `.superpowers-screenshots/feed-v2-level0-${theme}-${test.info().project.name}.png`,
      fullPage: true,
    });
  });

  test(`feed-v2 Level 1 (${theme})`, async ({ page }) => {
    await page.goto('/feed-v2');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    const firstRow = page.locator('[role="button"]').first();
    await firstRow.waitFor({ timeout: 10_000 });
    await firstRow.click();
    // AlertLevel1Page is now a real routed page (not a modal) that issues
    // its own async fetch after navigation -- wait for content that only
    // renders once that fetch resolves, same discipline as the deep-dive
    // page's "What they do" wait below.
    await page.waitForSelector('text=Raw move', { timeout: 10_000 });
    await hideBottomNav(page);
    await page.screenshot({
      path: `.superpowers-screenshots/feed-v2-level1-${theme}-${test.info().project.name}.png`,
      fullPage: true,
    });
  });

  test(`feed-v2 Level 2 ripple (${theme})`, async ({ page }) => {
    await page.goto('/feed-v2');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    const firstRow = page.locator('[role="button"]').first();
    await firstRow.waitFor({ timeout: 10_000 });
    await firstRow.click();
    await page.waitForSelector('text=Raw move', { timeout: 10_000 });
    const rippleDoor = page.getByRole('link', { name: /See ripple/ });
    await rippleDoor.click();
    // "See timeline" always renders once AlertRipplePage's own fetch
    // resolves, regardless of whether this alert has any ripple companies
    // -- a stable anchor independent of ripple content.
    await page.waitForSelector('text=See timeline', { timeout: 10_000 });
    await hideBottomNav(page);
    await page.screenshot({
      path: `.superpowers-screenshots/feed-v2-level2-ripple-${theme}-${test.info().project.name}.png`,
      fullPage: true,
    });
  });

  test(`feed-v2 Level 3 timeline (${theme})`, async ({ page }) => {
    await page.goto('/feed-v2');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    const firstRow = page.locator('[role="button"]').first();
    await firstRow.waitFor({ timeout: 10_000 });
    await firstRow.click();
    await page.waitForSelector('text=Raw move', { timeout: 10_000 });
    await page.getByRole('link', { name: /See ripple/ }).click();
    await page.waitForSelector('text=See timeline', { timeout: 10_000 });
    await page.getByRole('link', { name: /See timeline/ }).click();
    // "← Ripple" always renders once AlertTimelinePage's own fetch
    // resolves, regardless of whether this alert has any timeline entries.
    await page.waitForSelector('text=Ripple', { timeout: 10_000 });
    await hideBottomNav(page);
    await page.screenshot({
      path: `.superpowers-screenshots/feed-v2-level3-timeline-${theme}-${test.info().project.name}.png`,
      fullPage: true,
    });
  });

  test(`feed-v2 intensity breakdown (${theme})`, async ({ page }) => {
    await page.goto('/feed-v2');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    const intensityTarget = page.getByTestId('intensity-tap-target').first();
    await intensityTarget.waitFor({ timeout: 10_000 });
    await intensityTarget.click();
    await page.waitForTimeout(300);
    await page.screenshot({
      path: `.superpowers-screenshots/feed-v2-intensity-breakdown-${theme}-${test.info().project.name}.png`,
      fullPage: true,
    });
  });

  test(`feed-v2 stock deep-dive with alert context (${theme})`, async ({ page }) => {
    await page.goto('/feed-v2');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    const firstRow = page.locator('[role="button"]').first();
    await firstRow.waitFor({ timeout: 10_000 });
    await firstRow.click();
    await page.waitForSelector('text=Raw move', { timeout: 10_000 });
    await page.getByRole('link', { name: /See ripple/ }).click();
    await page.waitForSelector('text=See timeline', { timeout: 10_000 });
    // Ripple's peer rows are now on a plain page (no longer scoped inside
    // a `[role="dialog"]`) -- same selector shape PeerRow has always used.
    const peerRow = page.locator('[role="button"][aria-label]').first();
    await peerRow.waitFor({ timeout: 10_000 });
    await peerRow.click();
    await page.waitForSelector('text=What they do', { timeout: 10_000 });
    await hideBottomNav(page);
    await page.screenshot({
      path: `.superpowers-screenshots/feed-v2-stock-deep-dive-with-alert-${theme}-${test.info().project.name}.png`,
      fullPage: true,
    });
  });

  test(`feed-v2 directory (${theme})`, async ({ page }) => {
    await page.goto('/feed-v2/directory');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    await page.waitForSelector('text=/./', { timeout: 10_000 }).catch(() => {});
    await page.screenshot({
      path: `.superpowers-screenshots/feed-v2-directory-${theme}-${test.info().project.name}.png`,
      fullPage: true,
    });
  });

  test(`feed-v2 stock deep-dive without alert context (${theme})`, async ({ page }) => {
    await page.goto('/feed-v2/directory');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    const firstCompanyLink = page.locator('a[href^="/feed-v2/stock/"]').first();
    await firstCompanyLink.waitFor({ timeout: 10_000 });
    await firstCompanyLink.click();
    await page.waitForSelector('text=What they do', { timeout: 10_000 });
    await hideBottomNav(page);
    await page.screenshot({
      path: `.superpowers-screenshots/feed-v2-stock-deep-dive-no-alert-${theme}-${test.info().project.name}.png`,
      fullPage: true,
    });
  });
}
