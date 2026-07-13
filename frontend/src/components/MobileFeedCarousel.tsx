import { forwardRef } from 'react';
import type { Alert } from '../lib/api';
import AlertCoverCard from './AlertCoverCard';

const MobileFeedCarousel = forwardRef<
  HTMLDivElement,
  {
    alerts: Alert[];
    onOpen: (alertId: number) => void;
    openAlertId?: number | null;
    onClose?: () => void;
    isAuthenticated?: boolean;
  }
>(function MobileFeedCarousel({ alerts, onOpen, openAlertId = null, onClose = () => {}, isAuthenticated = false }, ref) {
  return (
    <div ref={ref} className="h-full min-h-0 snap-y snap-mandatory overflow-y-auto md:hidden">
      {alerts.map((alert) => (
        <AlertCoverCard
          key={alert.id}
          alert={alert}
          variant="carousel"
          onOpen={() => onOpen(alert.id)}
          expanded={alert.id === openAlertId}
          onClose={onClose}
          isAuthenticated={isAuthenticated}
        />
      ))}
    </div>
  );
});

export default MobileFeedCarousel;
