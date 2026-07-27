import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../../lib/auth';
import { getFeedV2Alerts, type FeedV2Alert } from '../../lib/feedV2Api';
import FeedRowV2 from './FeedRowV2';

export default function FeedV2() {
  const { token } = useAuth();
  const navigate = useNavigate();
  const [alerts, setAlerts] = useState<FeedV2Alert[]>([]);

  useEffect(() => {
    getFeedV2Alerts(token).then(setAlerts).catch(() => setAlerts([]));
  }, [token]);

  return (
    <div className="mx-auto w-full max-w-3xl px-4">
      <div className="mb-2 flex justify-end">
        <Link to="/feed-v2/directory" className="font-sans text-xs text-muted underline">
          Browse all stocks
        </Link>
      </div>
      <div className="rounded-lg bg-surface p-5">
        {alerts.map((alert) => (
          <FeedRowV2 key={alert.id} alert={alert} onOpen={() => navigate(`/feed-v2/alert/${alert.id}`)} />
        ))}
      </div>
    </div>
  );
}
