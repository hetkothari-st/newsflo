import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import SentimentPill, { netSentiment } from './SentimentPill';

const bull = { direction: 'bullish' };
const bear = { direction: 'bearish' };

describe('netSentiment majority vote', () => {
  it('returns bullish when more than 50% are bullish', () => {
    expect(netSentiment([bull, bull, bear])).toBe('bullish');
  });
  it('returns bearish when more than 50% are bearish', () => {
    expect(netSentiment([bear, bear, bull])).toBe('bearish');
  });
  it('returns mixed on an exact two-way tie', () => {
    expect(netSentiment([bull, bear])).toBe('mixed');
  });
  it('returns mixed for an empty list (the empty My Demat case)', () => {
    expect(netSentiment([])).toBe('mixed');
  });
  it('treats exactly 50% bullish as mixed (not a majority)', () => {
    expect(netSentiment([bull, bull, bear, bear])).toBe('mixed');
  });
});

describe('SentimentPill', () => {
  it('renders Net Bullish with bullish text styling', () => {
    render(<SentimentPill companies={[bull, bull, bear]} />);
    expect(screen.getByText('Net Bullish')).toHaveClass('text-bullish');
  });
  it('renders Net Bearish with bearish text styling', () => {
    render(<SentimentPill companies={[bear, bear, bull]} />);
    expect(screen.getByText('Net Bearish')).toHaveClass('text-bearish');
  });
  it('renders Mixed with muted styling for an empty list', () => {
    render(<SentimentPill companies={[]} />);
    expect(screen.getByText('Mixed')).toHaveClass('text-muted');
  });
});
