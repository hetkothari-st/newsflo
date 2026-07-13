import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import LanguagePicker from './LanguagePicker';
import { LanguageProvider } from '../lib/language';

function renderPicker() {
  return render(
    <LanguageProvider>
      <LanguagePicker />
    </LanguageProvider>,
  );
}

afterEach(() => {
  localStorage.clear();
});

describe('LanguagePicker', () => {
  it('lists every supported language by its native name', () => {
    renderPicker();
    expect(screen.getByRole('option', { name: 'English' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'हिन्दी' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'ਪੰਜਾਬੀ' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'বাংলা' })).toBeInTheDocument();
  });

  it('defaults to English selected', () => {
    renderPicker();
    expect(screen.getByRole('combobox')).toHaveValue('en');
  });

  it('switching the selection persists the new language', async () => {
    renderPicker();
    await userEvent.selectOptions(screen.getByRole('combobox'), 'hi');
    expect(screen.getByRole('combobox')).toHaveValue('hi');
    expect(localStorage.getItem('newsflo.lang')).toBe('hi');
  });
});
