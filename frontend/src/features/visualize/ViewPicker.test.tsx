import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import ViewPicker from './ViewPicker';

describe('ViewPicker', () => {
  it('renders both view options', () => {
    render(<ViewPicker value="impact" onChange={() => {}} />);
    expect(screen.getByText('Impact Tree')).toBeInTheDocument();
    expect(screen.getByText('Sector Tree')).toBeInTheDocument();
  });

  it('calls onChange with the clicked view id', async () => {
    const onChange = vi.fn();
    render(<ViewPicker value="impact" onChange={onChange} />);
    await userEvent.click(screen.getByText('Sector Tree'));
    expect(onChange).toHaveBeenCalledWith('sector');
  });
});
