import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import CarReviewPage from './CarReviewPage';
import * as carReviewApi from '../lib/carReviewApi';
import type { CarReviewRow, CarReviewSummary } from '../lib/carReviewApi';
import { AuthProvider } from '../lib/auth';

function makeRow(overrides: Partial<CarReviewRow> = {}): CarReviewRow {
  return {
    id: 1,
    ticker: 'RELIANCE.NS',
    company_name: 'Reliance Industries',
    category: 'oil_gas',
    article_title: 'Crude oil supply shock hits refiners',
    article_url: 'https://example.com/article',
    alert_created_at: '2026-07-10T09:00:00Z',
    day0_excess_move_pct: -4.2,
    car_pct: -3.6,
    outcome_label: 'HELD',
    ...overrides,
  };
}

function makeSummary(overrides: Partial<CarReviewSummary> = {}): CarReviewSummary {
  return {
    sample_count: 6,
    hold_rate: 0.83,
    mean_car_pct: -0.4,
    by_category: [{ category: 'oil_gas', sample_count: 6, hold_rate: 0.83, mean_car_pct: -0.4 }],
    ...overrides,
  };
}

function renderPage() {
  return render(
    <AuthProvider>
      <MemoryRouter>
        <CarReviewPage />
      </MemoryRouter>
    </AuthProvider>,
  );
}

describe('CarReviewPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders a row per outcome with its label', async () => {
    vi.spyOn(carReviewApi, 'getCarReview').mockResolvedValue([makeRow()]);
    vi.spyOn(carReviewApi, 'getCarReviewSummary').mockResolvedValue(makeSummary({ sample_count: 1, hold_rate: null, mean_car_pct: null, by_category: [] }));
    renderPage();

    await waitFor(() => expect(screen.getByText('Reliance Industries')).toBeInTheDocument());
    expect(screen.getByText('HELD')).toBeInTheDocument();
    expect(screen.getByText(/4\.2/)).toBeInTheDocument();
    expect(screen.getByText(/3\.6/)).toBeInTheDocument();
  });

  it('renders REVERSED and FLAT labels distinctly', async () => {
    vi.spyOn(carReviewApi, 'getCarReview').mockResolvedValue([
      makeRow({ id: 1, ticker: 'A.NS', outcome_label: 'REVERSED' }),
      makeRow({ id: 2, ticker: 'B.NS', outcome_label: 'FLAT' }),
    ]);
    vi.spyOn(carReviewApi, 'getCarReviewSummary').mockResolvedValue(makeSummary({ sample_count: 2, hold_rate: null, mean_car_pct: null, by_category: [] }));
    renderPage();

    await waitFor(() => expect(screen.getByText('REVERSED')).toBeInTheDocument());
    expect(screen.getByText('FLAT')).toBeInTheDocument();
  });

  it('shows the aggregate summary once the threshold is met', async () => {
    vi.spyOn(carReviewApi, 'getCarReview').mockResolvedValue([makeRow()]);
    vi.spyOn(carReviewApi, 'getCarReviewSummary').mockResolvedValue(makeSummary());
    renderPage();

    await waitFor(() => expect(screen.getByText(/83/)).toBeInTheDocument());
  });

  it('omits the aggregate summary below the threshold', async () => {
    vi.spyOn(carReviewApi, 'getCarReview').mockResolvedValue([makeRow()]);
    vi.spyOn(carReviewApi, 'getCarReviewSummary').mockResolvedValue(
      makeSummary({ sample_count: 1, hold_rate: null, mean_car_pct: null, by_category: [] }),
    );
    renderPage();

    await waitFor(() => expect(screen.getByText('Reliance Industries')).toBeInTheDocument());
    expect(screen.queryByText('Hold rate')).not.toBeInTheDocument();
  });

  it('links each row to its original article', async () => {
    vi.spyOn(carReviewApi, 'getCarReview').mockResolvedValue([makeRow()]);
    vi.spyOn(carReviewApi, 'getCarReviewSummary').mockResolvedValue(makeSummary({ sample_count: 1, hold_rate: null, mean_car_pct: null, by_category: [] }));
    renderPage();

    await waitFor(() => expect(screen.getByText('Reliance Industries')).toBeInTheDocument());
    const link = screen.getByRole('link', { name: /Crude oil supply shock hits refiners/ });
    expect(link).toHaveAttribute('href', 'https://example.com/article');
  });

  it('renders an empty state when there are no outcomes yet', async () => {
    vi.spyOn(carReviewApi, 'getCarReview').mockResolvedValue([]);
    vi.spyOn(carReviewApi, 'getCarReviewSummary').mockResolvedValue(
      makeSummary({ sample_count: 0, hold_rate: null, mean_car_pct: null, by_category: [] }),
    );
    renderPage();

    await waitFor(() => expect(screen.getByText(/no outcomes yet/i)).toBeInTheDocument());
  });
});
