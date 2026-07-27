import { test } from '@playwright/test';

const THEMES = ['dark', 'light'] as const;

for (const theme of THEMES) {
  test(`feed-v2 list (${theme})`, async ({ page }) => {
    await page.goto('/feed-v2');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    await page.waitForSelector('text=/./', { timeout: 10_000 }).catch(() => {});
    // On mobile the seeded feed has more cards than fit in one viewport, so
    // this fullPage capture is taller than the viewport just like the
    // deep-dive pages -- the fixed BottomNav must be hidden here too, or it
    // freezes at its viewport-relative position and overlaps a card partway
    // down the composited screenshot.
    await page.evaluate(() => {
      const bottomNav = document.querySelector('nav.fixed') as HTMLElement | null;
      if (bottomNav) bottomNav.style.display = 'none';
    });
    await page.screenshot({
      path: `.superpowers-screenshots/feed-v2-list-${theme}-${test.info().project.name}.png`,
      fullPage: true,
    });
  });

  test(`feed-v2 detail panel - affected tab (${theme})`, async ({ page }) => {
    await page.goto('/feed-v2');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    const firstRow = page.locator('[role="button"]').first();
    await firstRow.waitFor({ timeout: 10_000 });
    await firstRow.click();
    // The popup issues its own async fetch after opening -- wait for
    // content that only renders once that fetch resolves.
    await page.waitForSelector('text=Raw move', { timeout: 10_000 });
    await page.getByRole('button', { name: /Affected/ }).click();
    await page.waitForTimeout(300);
    await page.evaluate(() => {
      const dialog = document.querySelector('[role="dialog"]') as HTMLElement | null;
      const body = dialog?.querySelector('.overflow-y-auto') as HTMLElement | null;
      if (dialog) {
        dialog.style.overflow = 'visible';
        dialog.style.maxHeight = 'none';
      }
      if (body) {
        body.style.overflow = 'visible';
        body.style.maxHeight = 'none';
      }
    });
    await page.locator('[role="dialog"]').screenshot({
      path: `.superpowers-screenshots/feed-v2-panel-affected-${theme}-${test.info().project.name}.png`,
    });
  });

  test(`feed-v2 detail panel - ripple tab (${theme})`, async ({ page }) => {
    await page.goto('/feed-v2');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    const firstRow = page.locator('[role="button"]').first();
    await firstRow.waitFor({ timeout: 10_000 });
    await firstRow.click();
    await page.waitForSelector('text=Raw move', { timeout: 10_000 });
    await page.getByRole('button', { name: /Ripple/ }).click();
    await page.waitForTimeout(300);
    await page.evaluate(() => {
      const dialog = document.querySelector('[role="dialog"]') as HTMLElement | null;
      const body = dialog?.querySelector('.overflow-y-auto') as HTMLElement | null;
      if (dialog) {
        dialog.style.overflow = 'visible';
        dialog.style.maxHeight = 'none';
      }
      if (body) {
        body.style.overflow = 'visible';
        body.style.maxHeight = 'none';
      }
    });
    await page.locator('[role="dialog"]').screenshot({
      path: `.superpowers-screenshots/feed-v2-panel-ripple-${theme}-${test.info().project.name}.png`,
    });
  });

  test(`feed-v2 detail panel - timeline tab (${theme})`, async ({ page }) => {
    await page.goto('/feed-v2');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    const firstRow = page.locator('[role="button"]').first();
    await firstRow.waitFor({ timeout: 10_000 });
    await firstRow.click();
    await page.waitForSelector('text=Raw move', { timeout: 10_000 });
    await page.getByRole('button', { name: /Timeline/ }).click();
    await page.waitForTimeout(300);
    await page.evaluate(() => {
      const dialog = document.querySelector('[role="dialog"]') as HTMLElement | null;
      const body = dialog?.querySelector('.overflow-y-auto') as HTMLElement | null;
      if (dialog) {
        dialog.style.overflow = 'visible';
        dialog.style.maxHeight = 'none';
      }
      if (body) {
        body.style.overflow = 'visible';
        body.style.maxHeight = 'none';
      }
    });
    await page.locator('[role="dialog"]').screenshot({
      path: `.superpowers-screenshots/feed-v2-panel-timeline-${theme}-${test.info().project.name}.png`,
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
    await page.getByRole('button', { name: /Ripple/ }).click();
    const peerRow = page.locator('[role="dialog"] [role="button"][aria-label]').first();
    await peerRow.waitFor({ timeout: 10_000 });
    await peerRow.click();
    await page.waitForSelector('text=What they do', { timeout: 10_000 });
    await page.evaluate(() => {
      const bottomNav = document.querySelector('nav.fixed') as HTMLElement | null;
      if (bottomNav) bottomNav.style.display = 'none';
    });
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
    await page.evaluate(() => {
      const bottomNav = document.querySelector('nav.fixed') as HTMLElement | null;
      if (bottomNav) bottomNav.style.display = 'none';
    });
    await page.screenshot({
      path: `.superpowers-screenshots/feed-v2-stock-deep-dive-no-alert-${theme}-${test.info().project.name}.png`,
      fullPage: true,
    });
  });
}
