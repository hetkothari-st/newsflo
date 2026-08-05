// The "what they do" sentence, with the credit it owes.
//
// Renders nothing without a source URL. That is not a styling choice: the
// backend only sends text it can attribute (app.companies.descriptions),
// and Wikipedia's CC BY-SA licence requires the attribution to travel with
// the text. Keeping both in one component is what stops a later refactor
// from rendering the sentence on its own.
interface Props {
  text: string | null | undefined;
  sourceUrl: string | null | undefined;
}

export default function BusinessDescription({ text, sourceUrl }: Props) {
  if (!text || !sourceUrl) return null;
  return (
    <p className="bdesc">
      {text}{' '}
      <a className="bdesc-src" href={sourceUrl} target="_blank" rel="noopener noreferrer">
        Wikipedia
      </a>
    </p>
  );
}
