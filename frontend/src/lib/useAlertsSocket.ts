import { useEffect, useRef, useState } from 'react';
import type { Alert, WsAlert } from './api';

const RECONNECT_DELAY_MS = 3000;

function wsUrl(): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${proto}://${window.location.host}/ws/alerts`;
}

function normalize(ws: WsAlert): Alert {
  return {
    ...ws,
    companies: ws.companies.map((c) => ({ ...c, in_my_holdings: false })),
  };
}

export function useAlertsSocket(): Alert[] {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const socketRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closedRef = useRef(false);

  useEffect(() => {
    closedRef.current = false;

    function connect() {
      const socket = new WebSocket(wsUrl());
      socketRef.current = socket;

      socket.onmessage = (event: MessageEvent) => {
        const raw = JSON.parse(event.data as string) as WsAlert;
        const incoming = normalize(raw);
        setAlerts((prev) => {
          if (prev.some((a) => a.id === incoming.id)) return prev; // dedupe by id
          return [incoming, ...prev]; // prepend newest
        });
      };

      socket.onclose = () => {
        if (closedRef.current) return; // intentional unmount close -> do not retry
        timerRef.current = setTimeout(connect, RECONNECT_DELAY_MS);
      };
    }

    connect();

    return () => {
      closedRef.current = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      socketRef.current?.close();
    };
  }, []);

  return alerts;
}
