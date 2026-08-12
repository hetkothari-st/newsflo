/* Indian broker directory for the Portfolio connect flow. Every entry
   connects through the provider-agnostic CSV import (the parser
   auto-detects each console's export shape); Zerodha additionally
   offers a live Kite Connect OAuth import when the server has API keys
   configured. `hint` tells the user where the export lives in that
   broker's console -- exact menu names where known, generic otherwise. */

export interface Broker {
  slug: string;
  name: string;
  hint: string;
  // Connector slug in the backend registry (app/portfolio_connect) --
  // present when a live API connector exists for this broker; whether
  // it's actually usable comes from /api/portfolio/connect/status.
  live?: string;
}

const CONSOLE_HINT = 'Log in to the web console → Portfolio / Holdings → Download or Export as CSV.';

export const BROKERS: Broker[] = [
  { slug: 'zerodha', name: 'Zerodha', live: 'zerodha', hint: 'Console (console.zerodha.com) → Portfolio → Holdings → Download CSV. Or connect live below.' },
  { slug: 'groww', name: 'Groww', hint: 'Stocks → Holdings → Download statement. If it downloads as XLSX, open and save as CSV first.' },
  { slug: 'upstox', name: 'Upstox', live: 'upstox', hint: 'Account → Reports → Holdings → Download CSV. Or connect live below.' },
  { slug: 'angelone', name: 'Angel One', live: 'angelone', hint: 'Reports → Holdings statement → Export CSV. Or connect live below.' },
  { slug: 'icicidirect', name: 'ICICI Direct', live: 'icicidirect', hint: 'Portfolio → Equity → View Demat Holdings → Export. Or connect live below.' },
  { slug: 'hdfcsky', name: 'HDFC Sky / Securities', hint: CONSOLE_HINT },
  { slug: 'kotak', name: 'Kotak Securities', hint: 'Reports → Holdings → Download. Save as CSV if offered XLSX.' },
  { slug: 'sbi', name: 'SBI Securities', hint: CONSOLE_HINT },
  { slug: 'motilal', name: 'Motilal Oswal', hint: CONSOLE_HINT },
  { slug: 'sharekhan', name: 'Sharekhan', hint: CONSOLE_HINT },
  { slug: '5paisa', name: '5paisa', hint: CONSOLE_HINT },
  { slug: 'dhan', name: 'Dhan', live: 'dhan', hint: 'My Profile → DhanHQ Trading APIs → generate an access token, paste it below. Or export a holdings CSV.' },
  { slug: 'fyers', name: 'Fyers', live: 'fyers', hint: 'My Account → Reports → Holdings → Export. Or connect live below.' },
  { slug: 'paytmmoney', name: 'Paytm Money', hint: CONSOLE_HINT },
  { slug: 'indmoney', name: 'INDmoney', hint: 'Indian Stocks → Holdings → Export report.' },
  { slug: 'axisdirect', name: 'Axis Direct', hint: CONSOLE_HINT },
  { slug: 'geojit', name: 'Geojit', hint: CONSOLE_HINT },
  { slug: 'iifl', name: 'IIFL Securities', hint: CONSOLE_HINT },
  { slug: 'choice', name: 'Choice Broking', hint: CONSOLE_HINT },
  { slug: 'religare', name: 'Religare Broking', hint: CONSOLE_HINT },
  { slug: 'ventura', name: 'Ventura Securities', hint: CONSOLE_HINT },
  { slug: 'smc', name: 'SMC Global', hint: CONSOLE_HINT },
  { slug: 'anandrathi', name: 'Anand Rathi', hint: CONSOLE_HINT },
  { slug: 'plindia', name: 'Prabhudas Lilladher', hint: CONSOLE_HINT },
  { slug: 'aliceblue', name: 'Alice Blue', hint: CONSOLE_HINT },
  { slug: 'shoonya', name: 'Shoonya (Finvasia)', hint: CONSOLE_HINT },
  { slug: 'zebu', name: 'Zebu', hint: CONSOLE_HINT },
  { slug: 'mastertrust', name: 'Mastertrust', hint: CONSOLE_HINT },
  { slug: 'nuvama', name: 'Nuvama Wealth', hint: CONSOLE_HINT },
  { slug: 'jmfinancial', name: 'JM Financial', hint: CONSOLE_HINT },
  { slug: 'mstock', name: 'm.Stock (Mirae)', hint: CONSOLE_HINT },
  { slug: 'bajaj', name: 'Bajaj Broking', hint: CONSOLE_HINT },
  { slug: 'cdsl', name: 'CDSL / NSDL CAS', hint: 'Any demat account: your monthly CAS statement lists holdings with ISINs — export/convert the holdings table to CSV.' },
];
