import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../lib/auth';
import { getFeedV2Alert, getFeedV2Alerts, type FeedV2Alert } from '../../lib/feedV2Api';
import AlertDetail from '../AlertDetail';
import AlertDetailPanel from './AlertDetailPanel';
import FeedRowV2 from './FeedRowV2';

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
      <div className="mb-2 flex justify-end">
        <Link to="/feed-v2/directory" className="font-sans text-xs text-muted underline">
          Browse all stocks
        </Link>
      </div>
      <div className="flex flex-col gap-4">
        {alerts.map((alert) => (
          <FeedRowV2 key={alert.id} alert={alert} onOpen={() => handleOpen(alert.id)} />
        ))}
      </div>
      <AlertDetail open={openAlert !== null} onClose={() => setOpenAlert(null)}>
        {openAlert && <AlertDetailPanel alert={openAlert} />}
      </AlertDetail>
    </div>
  );
}
