import { useState } from 'react';
import Feed from '../components/Feed';
import FeedTabs, { type FeedTab } from '../components/FeedTabs';

export default function FeedPage() {
  const [tab, setTab] = useState<FeedTab>('india');
  return (
    <main className="mx-auto max-w-feed px-4 py-8">
      <FeedTabs active={tab} onChange={setTab} />
      <Feed activeTab={tab} />
    </main>
  );
}
