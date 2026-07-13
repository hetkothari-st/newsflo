import type { Alert } from '../lib/api';
import AlertCoverCard from './AlertCoverCard';

export default function DesktopFeedGrid({
  alerts,
  onOpen,
}: {
  alerts: Alert[];
  onOpen: (alertId: number) => void;
}) {
  return (
    <div className="hidden gap-4 py-6 md:grid md:grid-cols-2 lg:grid-cols-3">
      {alerts.map((alert) => (
        <AlertCoverCard key={alert.id} alert={alert} variant="grid" onOpen={() => onOpen(alert.id)} />
      ))}
    </div>
  );
}
