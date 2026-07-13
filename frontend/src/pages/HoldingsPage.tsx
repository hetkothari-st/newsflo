import { useCallback, useEffect, useState } from 'react';
import { getHoldings, type Holding } from '../lib/api';
import { useAuth } from '../lib/auth';
import HoldingsForm from '../components/HoldingsForm';
import HoldingsCsvUpload from '../components/HoldingsCsvUpload';
import HoldingsList from '../components/HoldingsList';

export default function HoldingsPage() {
  const { token } = useAuth();
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    if (!token) return;
    getHoldings(token)
      .then((data) => {
        setHoldings(data);
        setError(null);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Failed to load holdings.'));
  }, [token]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <main className="mx-auto max-w-feed px-4 py-8">
      <h1 className="mb-6 font-display text-3xl font-bold text-ink">My Holdings</h1>
      <div className="flex flex-col gap-6">
        <HoldingsForm onAdded={refresh} />
        <HoldingsCsvUpload onUploaded={refresh} />
        {error && <p role="alert" className="text-xs text-bearish">{error}</p>}
        <HoldingsList holdings={holdings} />
      </div>
    </main>
  );
}
