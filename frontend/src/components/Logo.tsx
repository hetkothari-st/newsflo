import logoDark from '../assets/logo-dark.png';
import logoLight from '../assets/logo-light.png';
import { useTheme } from '../lib/theme';

export default function Logo({ className }: { className?: string }) {
  const { theme } = useTheme();
  return <img src={theme === 'light' ? logoLight : logoDark} alt="NewsFlo" className={className} />;
}
