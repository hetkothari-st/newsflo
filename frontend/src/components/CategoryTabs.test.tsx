import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import CategoryTabs from './CategoryTabs';

function renderTabs(overrides: Partial<Parameters<typeof CategoryTabs>[0]> = {}) {
  return render(
    <CategoryTabs
      active="india"
      onChange={() => {}}
      connected
      lastAlertAt={null}
      newCount={0}
      onRevealNew={() => {}}
      onOpenCustomSettings={() => {}}
      {...overrides}
    />,
  );
}

describe('CategoryTabs', () => {
  it('renders all three tabs and marks the active one selected', () => {
    renderTabs({ active: 'global' });
    expect(screen.getByRole('tab', { name: /global/i })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: /india/i })).toHaveAttribute('aria-selected', 'false');
  });

  it('calls onChange with the tab key when a tab is clicked', async () => {
    const onChange = vi.fn();
    renderTabs({ onChange });
    await userEvent.click(screen.getByRole('tab', { name: /custom/i }));
    expect(onChange).toHaveBeenCalledWith('custom');
  });

  it('shows the Live status', () => {
    renderTabs({ connected: true });
    expect(screen.getByText('Live')).toBeInTheDocument();
  });

  it('shows an "N new" pill only when newCount > 0, and it calls onRevealNew', async () => {
    const onRevealNew = vi.fn();
    const { rerender } = renderTabs({ newCount: 0, onRevealNew });
    expect(screen.queryByText(/new/i)).not.toBeInTheDocument();
    rerender(
      <CategoryTabs
        active="india"
        onChange={() => {}}
        connected
        lastAlertAt={null}
        newCount={3}
        onRevealNew={onRevealNew}
        onOpenCustomSettings={() => {}}
      />,
    );
    const pill = screen.getByText('3 new');
    await userEvent.click(pill);
    expect(onRevealNew).toHaveBeenCalled();
  });

  it('shows the settings gear only on the Custom tab', () => {
    const { rerender } = renderTabs({ active: 'india' });
    expect(screen.queryByLabelText(/custom feed settings/i)).not.toBeInTheDocument();
    rerender(
      <CategoryTabs
        active="custom"
        onChange={() => {}}
        connected
        lastAlertAt={null}
        newCount={0}
        onRevealNew={() => {}}
        onOpenCustomSettings={() => {}}
      />,
    );
    expect(screen.getByLabelText(/custom feed settings/i)).toBeInTheDocument();
  });

  it('calls onOpenCustomSettings when the gear is clicked', async () => {
    const onOpenCustomSettings = vi.fn();
    renderTabs({ active: 'custom', onOpenCustomSettings });
    await userEvent.click(screen.getByLabelText(/custom feed settings/i));
    expect(onOpenCustomSettings).toHaveBeenCalled();
  });
});
