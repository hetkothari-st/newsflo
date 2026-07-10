import type { Alert } from '../lib/api';
import AlertCoverCard from './AlertCoverCard';

export default function MobileFeedCarousel({
  alerts,
  onOpen,
}: {
  alerts: Alert[];
  onOpen: (alertId: number) => void;
}) {
  return (
    <div className="h-full min-h-0 flex-1 snap-y snap-mandatory overflow-y-auto md:hidden">
      {alerts.map((alert) => (
        <AlertCoverCard key={alert.id} alert={alert} variant="carousel" onOpen={() => onOpen(alert.id)} />
      ))}
    </div>
  );
}
