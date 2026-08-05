import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import BusinessDescription from './BusinessDescription';

describe('BusinessDescription', () => {
  it('renders the sentence with a link to its source', () => {
    render(
      <BusinessDescription
        text="Alkem Laboratories Limited is an Indian multinational pharmaceutical company."
        sourceUrl="https://en.wikipedia.org/wiki/Alkem_Laboratories"
      />,
    );
    expect(screen.getByText(/Alkem Laboratories Limited is an Indian/)).toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'Wikipedia' });
    expect(link).toHaveAttribute('href', 'https://en.wikipedia.org/wiki/Alkem_Laboratories');
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'));
  });

  it('renders nothing when the text cannot be attributed', () => {
    // CC BY-SA: the sentence may never appear without its credit, so an
    // unsourced description is not shown at all rather than shown bare.
    const { container } = render(
      <BusinessDescription text="An LLM made this up." sourceUrl={null} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing when there is no description', () => {
    const { container } = render(
      <BusinessDescription text={null} sourceUrl="https://en.wikipedia.org/wiki/Foo" />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
