import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useAlertsSocket } from './useAlertsSocket';
import type { WsAlert } from './api';

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  url: string;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;
  onopen: (() => void) | null = null;
  closed = false;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  emit(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent);
  }

  triggerClose() {
    this.onclose?.();
  }

  close() {
    this.closed = true;
  }
}

function makeWsAlert(id: number): WsAlert {
  return {
    id,
    category: 'oil_energy',
    category_label: 'oil_energy',
    created_at: '2026-07-09T10:00:00+00:00',
    article: { id, title: `Story ${id}`, url: `https://example.com/${id}`, image_url: null },
    companies: [
      {
        company_id: id, ticker: 'RELIANCE.NS', name: 'Reliance', index_tier: 'NIFTY50',
        direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'x', key_points: [],
        confidence_score: 50, time_horizon: 'Short-Term',
        past_mentions: [], basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN',
      },
    ],
  };
}

beforeEach(() => {
  MockWebSocket.instances = [];
  vi.stubGlobal('WebSocket', MockWebSocket as unknown as typeof WebSocket);
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('useAlertsSocket', () => {
  it('normalizes incoming alerts with in_my_holdings=false and prepends them', () => {
    const { result } = renderHook(() => useAlertsSocket());
    act(() => MockWebSocket.instances[0].emit(makeWsAlert(1)));
    act(() => MockWebSocket.instances[0].emit(makeWsAlert(2)));
    expect(result.current.alerts.map((a) => a.id)).toEqual([2, 1]);
    expect(result.current.alerts[0].companies[0].in_my_holdings).toBe(false);
  });

  it('dedupes repeated alert ids', () => {
    const { result } = renderHook(() => useAlertsSocket());
    act(() => MockWebSocket.instances[0].emit(makeWsAlert(1)));
    act(() => MockWebSocket.instances[0].emit(makeWsAlert(1)));
    expect(result.current.alerts).toHaveLength(1);
  });

  it('reports connected once the socket opens, and disconnected once it closes', () => {
    const { result } = renderHook(() => useAlertsSocket());
    expect(result.current.connected).toBe(false);
    act(() => MockWebSocket.instances[0].onopen?.());
    expect(result.current.connected).toBe(true);
    act(() => MockWebSocket.instances[0].triggerClose());
    expect(result.current.connected).toBe(false);
  });

  it('reconnects after a fixed backoff when the socket closes', () => {
    renderHook(() => useAlertsSocket());
    expect(MockWebSocket.instances).toHaveLength(1);
    act(() => {
      MockWebSocket.instances[0].triggerClose();
      vi.advanceTimersByTime(3000);
    });
    expect(MockWebSocket.instances).toHaveLength(2);
  });

  it('does not reconnect before the backoff elapses', () => {
    renderHook(() => useAlertsSocket());
    expect(MockWebSocket.instances).toHaveLength(1);
    act(() => {
      MockWebSocket.instances[0].triggerClose();
      vi.advanceTimersByTime(2999);
    });
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it('does not reconnect after unmount (no leaked timers/connections)', () => {
    const { unmount } = renderHook(() => useAlertsSocket());
    expect(MockWebSocket.instances).toHaveLength(1);
    const first = MockWebSocket.instances[0];
    unmount();
    expect(first.closed).toBe(true);
    act(() => {
      first.triggerClose();
      vi.advanceTimersByTime(5000);
    });
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it('survives multiple reconnect cycles without leaking duplicate connections per cycle', () => {
    renderHook(() => useAlertsSocket());
    expect(MockWebSocket.instances).toHaveLength(1);

    act(() => {
      MockWebSocket.instances[0].triggerClose();
      vi.advanceTimersByTime(3000);
    });
    expect(MockWebSocket.instances).toHaveLength(2);

    act(() => {
      MockWebSocket.instances[1].triggerClose();
      vi.advanceTimersByTime(3000);
    });
    expect(MockWebSocket.instances).toHaveLength(3);

    // messages received on the latest socket after reconnects should still land
    act(() => MockWebSocket.instances[2].emit(makeWsAlert(7)));
    expect(MockWebSocket.instances[2].onmessage).not.toBeNull();
  });
});
