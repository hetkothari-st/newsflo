import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import RippleSection from '../components/feed-v2/RippleSection';
import { getFeedV2Alert, type FeedV2Alert } from '../lib/feedV2Api';
import { useAuth } from '../lib/auth';

export default function AlertRipplePage() {
  const { id } = useParams<{ id: string }>();
  const alertId = id !== undefined ? Number(id) : undefined;
  const { token } = useAuth();

  const [alert, setAlert] = useState<FeedV2Alert | null | undefined>(undefined);

  useEffect(() => {
    if (alertId === undefined) return;
    let active = true;
    setAlert(undefined);
    getFeedV2Alert(alertId, token)
      .then((data) => {
        if (active) setAlert(data);
      })
      .catch(() => {
        if (active) setAlert(null);
      });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [alertId, token]);

  if (alert === undefined) return null;

  if (alert === null) {
    return (
      <main className="mx-auto w-full max-w-3xl px-4 py-8">
        <p className="font-sans text-sm text-muted">Alert not found.</p>
      </main>
    );
  }

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-col gap-3 px-4 py-8">
      <Link to={`/feed-v2/alert/${alert.id}`} className="font-sans text-xs text-muted underline">
        ← Summary
      </Link>

      {alert.ripple && <RippleSection companies={alert.ripple} alertId={alert.id} />}

      <Link
        to={`/feed-v2/alert/${alert.id}/timeline`}
        className="self-end font-sans text-xs text-muted underline"
      >
        See timeline →
      </Link>
    </main>
  );
}
