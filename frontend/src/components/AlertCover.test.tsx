import { render, fireEvent } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import AlertCover from './AlertCover';

describe('AlertCover', () => {
  it('renders the real image when a URL is given', () => {
    const { container } = render(<AlertCover imageUrl="https://example.com/pic.jpg" category="oil_energy" />);
    const img = container.querySelector('img');
    expect(img).toHaveAttribute('src', 'https://example.com/pic.jpg');
  });

  it('falls back to a category cover when there is no image URL', () => {
    const { container } = render(<AlertCover imageUrl={null} category="banking" />);
    expect(container.querySelector('img')).not.toBeInTheDocument();
  });

  it('falls back to a category cover when the image fails to load', () => {
    const { container } = render(<AlertCover imageUrl="https://example.com/broken.jpg" category="auto_ev" />);
    const img = container.querySelector('img');
    expect(img).toBeInTheDocument();
    if (img) fireEvent.error(img);
    expect(container.querySelector('img')).not.toBeInTheDocument();
  });

  it('renders a single photo that fills its box with no letterboxing or blur', () => {
    const { container } = render(<AlertCover imageUrl="https://example.com/pic.jpg" category="oil_energy" />);
    const imgs = container.querySelectorAll('img');
    expect(imgs).toHaveLength(1);
    expect(imgs[0]).toHaveClass('h-full');
    expect(imgs[0]).toHaveClass('w-full');
    expect(imgs[0]).toHaveClass('object-cover');
    expect(container.querySelector('.blur-2xl')).not.toBeInTheDocument();
  });
});
