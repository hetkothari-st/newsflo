/* Storycard headline: 4-line budget with a truly inline MORE expander.
   All mechanics live in ClampedText (measured word-cut -- the button is
   flow content after the last word, never an overlay). */
import ClampedText from './ClampedText';

export default function ExpandableTitle({ title }: { title: string }) {
  return <ClampedText text={title} lines={4} as="h1" />;
}
