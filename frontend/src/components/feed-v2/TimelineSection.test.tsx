import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import TimelineSection from './TimelineSection';
import type { TimelineEntry } from '../../lib/feedV2Api';

describe('TimelineSection', () => {
  it('renders nothing when there are no entries', () => {
    const { container } = render(<TimelineSection entries={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders one row per entry with horizon label and description', () => {
    const entries: TimelineEntry[] = [
      { horizon: 'TODAY', description: 'Markets react immediately.' },
      { horizon: 'WEEKS', description: 'Effects persist for weeks.' },
    ];
    render(<TimelineSection entries={entries} />);
    expect(screen.getByText('Today')).toBeInTheDocument();
    expect(screen.getByText('Markets react immediately.')).toBeInTheDocument();
    expect(screen.getByText('Next few weeks')).toBeInTheDocument();
    expect(screen.getByText('Effects persist for weeks.')).toBeInTheDocument();
  });

  it('only renders horizons that are present, in the order given', () => {
    const entries: TimelineEntry[] = [
      { horizon: 'TODAY', description: 'Today effect.' },
      { horizon: 'QUARTERS', description: 'Quarters effect.' },
    ];
    render(<TimelineSection entries={entries} />);
    expect(screen.queryByText('Next few days')).not.toBeInTheDocument();
    expect(screen.queryByText('Next few months')).not.toBeInTheDocument();
    expect(screen.getByText('Next few quarters')).toBeInTheDocument();
  });
});
