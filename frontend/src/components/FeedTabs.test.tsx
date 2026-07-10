import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import FeedTabs from './FeedTabs';

describe('FeedTabs', () => {
  it('renders all three tabs', () => {
    render(<FeedTabs active="india" onChange={() => {}} />);
    expect(screen.getByRole('tab', { name: /india/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /global/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /custom/i })).toBeInTheDocument();
  });

  it('marks the active tab as selected', () => {
    render(<FeedTabs active="global" onChange={() => {}} />);
    expect(screen.getByRole('tab', { name: /global/i })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: /india/i })).toHaveAttribute('aria-selected', 'false');
  });

  it('calls onChange with the tab key when a tab is clicked', async () => {
    const onChange = vi.fn();
    render(<FeedTabs active="india" onChange={onChange} />);
    await userEvent.click(screen.getByRole('tab', { name: /custom/i }));
    expect(onChange).toHaveBeenCalledWith('custom');
  });
});
