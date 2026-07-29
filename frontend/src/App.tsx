import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { useState, type ReactElement } from 'react';
import BottomNav from './components/BottomNav';
import CalendarModal from './components/CalendarModal';
import NavBar from './components/NavBar';
import TranslationProgressBanner from './components/TranslationProgressBanner';
import AccountPage from './pages/AccountPage';
import HoldingsPage from './pages/HoldingsPage';
import LoginPage from './pages/LoginPage';
import RegisterPage from './pages/RegisterPage';
import Shell from './v3/Shell';
import { useAuth } from './lib/auth';

// -- COMMENTED OUT (superseded by the card-feed shell at "/", built from
// docs/NEWS_IMPACT_APP_SPEC_V2.md + the approved visual prototype
// newsflo_full_frontend.html -- the old feed, feed-v2, charts, company
// analysis, directory, deep-dive and CAR pages are all replaced by the
// shell's own views and sheets):
// import AlertChartsPage from './pages/AlertChartsPage';
// import AlertCompanyAnalysisPage from './pages/AlertCompanyAnalysisPage';
// import CarReviewPage from './pages/CarReviewPage';
// import CompanyPage from './pages/CompanyPage';
// import DirectoryPage from './pages/DirectoryPage';
// import FeedPage from './pages/FeedPage';
// import FeedV2Page from './pages/FeedV2Page';
// import StockDeepDivePage from './pages/StockDeepDivePage';

function RequireAuth({ children }: { children: ReactElement }) {
  const { token } = useAuth();
  if (!token) return <Navigate to="/login" replace />;
  return children;
}

export default function App() {
  const [calendarOpen, setCalendarOpen] = useState(false);
  const location = useLocation();
  // The card-feed shell owns the whole viewport (its own top bar + bottom
  // nav, spec v2 §7) -- the legacy NavBar/BottomNav chrome only wraps the
  // remaining auth/account/holdings pages.
  const isShell = location.pathname === '/';

  if (isShell) {
    return <Shell />;
  }

  return (
    <div className="min-h-screen bg-page pb-14 font-sans text-ink md:pb-0">
      <TranslationProgressBanner />
      <NavBar onOpenCalendar={() => setCalendarOpen(true)} />
      <Routes>
        {/* -- COMMENTED OUT (superseded by the card-feed shell at "/"):
        <Route path="/" element={<FeedPage />} />
        <Route path="/feed-v2" element={<FeedV2Page />} />
        <Route path="/feed-v2/stock/:ticker" element={<StockDeepDivePage />} />
        <Route path="/feed-v2/directory" element={<DirectoryPage />} />
        <Route path="/company/:id" element={<CompanyPage />} />
        <Route path="/alerts/:id/charts" element={<AlertChartsPage />} />
        <Route path="/alerts/:id/company/:companyId" element={<AlertCompanyAnalysisPage />} />
        <Route path="/car-review" element={<RequireAuth><CarReviewPage /></RequireAuth>} />
        */}
        <Route
          path="/holdings"
          element={
            <RequireAuth>
              <HoldingsPage />
            </RequireAuth>
          }
        />
        <Route
          path="/account"
          element={
            <RequireAuth>
              <AccountPage />
            </RequireAuth>
          }
        />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <BottomNav onOpenCalendar={() => setCalendarOpen(true)} />
      <CalendarModal open={calendarOpen} onClose={() => setCalendarOpen(false)} />
    </div>
  );
}
