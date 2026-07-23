import { test } from '@playwright/test';

const THEMES = ['dark', 'light'] as const;

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
    await page.waitForTimeout(300); // allow the modal's open transition to settle
    // The modal panel is `position: fixed` (see AlertDetail.tsx) with its own
    // `max-h-[85vh] overflow-hidden` box and an inner `overflow-y-auto` body
    // -- Chromium excludes fixed-position content from document.scrollHeight
    // entirely regardless of overflow/max-height, so a page-level `fullPage`
    // screenshot can never include content past the modal's own scroll fold,
    // and an element screenshot of the still-clipped dialog caps at 85vh too
    // (verified against a live page: dialog.scrollHeight was 927px on a
    // 390x844 viewport, but a plain element screenshot only captured 718px,
    // exactly 85vh). Lift both the panel's own clipping and its child's
    // scroll clipping first so the element screenshot captures the true,
    // full height -- ripple + timeline content included regardless of
    // viewport height.
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
      path: `.superpowers-screenshots/feed-v2-level1-${theme}-${test.info().project.name}.png`,
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
}
