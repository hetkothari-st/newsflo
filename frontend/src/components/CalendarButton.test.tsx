import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import CalendarButton from './CalendarButton';
import { LanguageProvider } from '../lib/language';

describe('CalendarButton', () => {
  it('calls onClick when clicked', async () => {
    const onClick = vi.fn();
    render(
      <LanguageProvider>
        <CalendarButton onClick={onClick} />
      </LanguageProvider>,
    );
    await userEvent.click(screen.getByRole('button', { name: /calendar/i }));
    expect(onClick).toHaveBeenCalled();
  });
});
