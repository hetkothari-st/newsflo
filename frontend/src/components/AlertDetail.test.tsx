import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import AlertDetail from './AlertDetail';

describe('AlertDetail', () => {
  it('renders nothing when closed', () => {
    render(
      <AlertDetail open={false} onClose={() => {}}>
        <p>content</p>
      </AlertDetail>,
    );
    expect(screen.queryByText('content')).not.toBeInTheDocument();
  });

  it('renders children in a dialog when open', () => {
    render(
      <AlertDetail open onClose={() => {}}>
        <p>content</p>
      </AlertDetail>,
    );
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('content')).toBeInTheDocument();
  });

  it('calls onClose when the close button is clicked', async () => {
    const onClose = vi.fn();
    render(
      <AlertDetail open onClose={onClose}>
        <p>content</p>
      </AlertDetail>,
    );
    await userEvent.click(screen.getByRole('button', { name: /close/i }));
    expect(onClose).toHaveBeenCalled();
  });

  it('calls onClose on backdrop click', async () => {
    const onClose = vi.fn();
    const { container } = render(
      <AlertDetail open onClose={onClose}>
        <p>content</p>
      </AlertDetail>,
    );
    const backdrop = container.querySelector('[aria-hidden="true"]');
    expect(backdrop).not.toBeNull();
    if (backdrop) await userEvent.click(backdrop);
    expect(onClose).toHaveBeenCalled();
  });

  it('calls onClose on Escape', () => {
    const onClose = vi.fn();
    render(
      <AlertDetail open onClose={onClose}>
        <p>content</p>
      </AlertDetail>,
    );
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });

  it('moves focus into the dialog panel when opened', () => {
    render(
      <AlertDetail open onClose={() => {}}>
        <p>content</p>
      </AlertDetail>,
    );
    expect(screen.getByRole('dialog')).toHaveFocus();
  });

  it('gets a raised shadow instead of a border in light mode', () => {
    render(
      <AlertDetail open onClose={() => {}}>
        <p>content</p>
      </AlertDetail>,
    );
    expect(screen.getByRole('dialog')).toHaveClass('theme-light:shadow-neu');
  });

  it('defaults to a bottom sheet capped at 85vh on mobile', () => {
    render(
      <AlertDetail open onClose={() => {}}>
        <p>content</p>
      </AlertDetail>,
    );
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveClass('max-h-[85vh]', 'rounded-t-lg');
    expect(dialog).not.toHaveClass('h-full');
  });

  it('fullScreenMobile fills the viewport on mobile instead of a bottom sheet', () => {
    render(
      <AlertDetail open onClose={() => {}} fullScreenMobile>
        <p>content</p>
      </AlertDetail>,
    );
    const dialog = screen.getByRole('dialog');
    // No gap above the panel on mobile -- nothing for the page behind to
    // bleed through above an in-panel sticky header (e.g. CalendarModal's
    // day-view bar). Desktop sizing (md:*) is unaffected either way.
    expect(dialog).toHaveClass('h-full', 'max-h-full', 'rounded-none');
    expect(dialog).not.toHaveClass('max-h-[85vh]', 'rounded-t-lg');
  });
});
