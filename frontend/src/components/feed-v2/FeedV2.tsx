import { useEffect, useState } from 'react';
import { useAuth } from '../../lib/auth';
import { getFeedV2Alert, getFeedV2Alerts, type FeedV2Alert } from '../../lib/feedV2Api';
import AlertDetail from '../AlertDetail';
import FeedRowV2 from './FeedRowV2';
import Level1SummaryV2 from './Level1SummaryV2';

export default function FeedV2() {
  const { token } = useAuth();
  const [alerts, setAlerts] = useState<FeedV2Alert[]>([]);
  const [openAlert, setOpenAlert] = useState<FeedV2Alert | null>(null);

  useEffect(() => {
    getFeedV2Alerts(token).then(setAlerts).catch(() => setAlerts([]));
  }, [token]);

  const handleOpen = (id: number) => {
    getFeedV2Alert(id, token)
      .then(setOpenAlert)
      .catch(() => setOpenAlert(null));
  };

  return (
    <div className="mx-auto w-full max-w-3xl px-4">
      <div className="rounded-lg bg-surface p-5">
        {alerts.map((alert) => (
          <FeedRowV2 key={alert.id} alert={alert} onOpen={() => handleOpen(alert.id)} />
        ))}
      </div>
      <AlertDetail open={openAlert !== null} onClose={() => setOpenAlert(null)}>
        {openAlert && <Level1SummaryV2 alert={openAlert} />}
      </AlertDetail>
    </div>
  );
}
