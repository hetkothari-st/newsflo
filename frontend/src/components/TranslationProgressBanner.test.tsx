import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import TranslationProgressBanner from './TranslationProgressBanner';
import { LanguageProvider, useLanguage } from '../lib/language';
import * as api from '../lib/api';

function Harness() {
  const { setLanguage } = useLanguage();
  return (
    <>
      <button type="button" onClick={() => setLanguage('hi')}>
        switch
      </button>
      <button type="button">some other app control</button>
      <TranslationProgressBanner />
    </>
  );
}

function renderHarness() {
  return render(
    <LanguageProvider>
      <Harness />
    </LanguageProvider>,
  );
}

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe('TranslationProgressBanner', () => {
  it('renders nothing while the current language is English', () => {
    renderHarness();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('shows progress while a translation drain is still running, without disabling the rest of the app', async () => {
    vi.spyOn(api, 'triggerTranslation').mockResolvedValue({ started: true });
    // running: true -- the poll loop's sleep-before-next-poll means this
    // state stays rendered (not immediately superseded by a second poll),
    // unlike a running: false response which flips translating off in the
    // same batch as the progress update.
    vi.spyOn(api, 'getTranslationStatus').mockResolvedValue({ total: 10, translated: 4, running: true });
    renderHarness();

    await userEvent.click(screen.getByRole('button', { name: 'switch' }));

    expect(await screen.findByRole('status')).toBeInTheDocument();
    expect(screen.getByText('4 / 10')).toBeInTheDocument();
    // The rest of the app's controls stay enabled/clickable -- this is a
    // banner in normal flow, not a blocking overlay.
    const otherControl = screen.getByRole('button', { name: 'some other app control' });
    expect(otherControl).toBeEnabled();
    await userEvent.click(otherControl);
  });

  it('hides once the drain reports done', async () => {
    vi.spyOn(api, 'triggerTranslation').mockResolvedValue({ started: true });
    vi.spyOn(api, 'getTranslationStatus').mockResolvedValue({ total: 10, translated: 10, running: false });
    renderHarness();

    await userEvent.click(screen.getByRole('button', { name: 'switch' }));

    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument());
  });

  it('can be dismissed early while still translating, and reappears on the next switch', async () => {
    vi.spyOn(api, 'triggerTranslation').mockResolvedValue({ started: true });
    vi.spyOn(api, 'getTranslationStatus').mockResolvedValue({ total: 10, translated: 4, running: true });
    renderHarness();

    await userEvent.click(screen.getByRole('button', { name: 'switch' }));
    await screen.findByRole('status');

    await userEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
    expect(screen.queryByRole('status')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'switch' }));
    expect(await screen.findByRole('status')).toBeInTheDocument();
  });
});
