import { forwardRef } from 'react';
import type { Alert } from '../lib/api';
import AlertCoverCard from './AlertCoverCard';

const MobileFeedCarousel = forwardRef<HTMLDivElement, { alerts: Alert[]; onOpen: (alertId: number) => void }>(
  function MobileFeedCarousel({ alerts, onOpen }, ref) {
    return (
      <div ref={ref} className="h-full min-h-0 snap-y snap-mandatory overflow-y-auto md:hidden">
        {alerts.map((alert) => (
          <AlertCoverCard key={alert.id} alert={alert} variant="carousel" onOpen={() => onOpen(alert.id)} />
        ))}
      </div>
    );
  },
);

export default MobileFeedCarousel;
