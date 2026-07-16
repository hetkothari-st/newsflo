import { describe, expect, it } from 'vitest';
import { eventTypeLabel, formatEvidenceRef, ruleLabel } from './ruleLabels';

describe('ruleLabel', () => {
  it('returns a human label for a known rule id', () => {
    expect(ruleLabel('RULE_REPO_RATE_CUT')).toBe('Repo rate cut');
  });

  it('falls back to the raw id for an unrecognized rule id', () => {
    expect(ruleLabel('RULE_DOES_NOT_EXIST')).toBe('RULE_DOES_NOT_EXIST');
  });
});

describe('eventTypeLabel', () => {
  it('returns a human label for a known event type', () => {
    expect(eventTypeLabel('crude_oil')).toBe('Crude oil');
  });

  it('falls back to the raw value for an unrecognized event type', () => {
    expect(eventTypeLabel('not_a_real_event')).toBe('not_a_real_event');
  });
});

describe('formatEvidenceRef', () => {
  it('formats a rule id as kind "rule" with its human label', () => {
    expect(formatEvidenceRef('RULE_CRUDE_OIL_UP')).toEqual({ text: 'Crude oil up', kind: 'rule' });
  });

  it('formats an "article:" prefix as kind "article" with the prefix stripped', () => {
    expect(formatEvidenceRef('article: crude prices spiked 8% overnight')).toEqual({
      text: 'crude prices spiked 8% overnight',
      kind: 'article',
    });
  });

  it('formats a "historical:" prefix as kind "historical" with the prefix stripped', () => {
    expect(formatEvidenceRef('historical: 2019 repo cut lifted HDFC Bank credit growth')).toEqual({
      text: '2019 repo cut lifted HDFC Bank credit growth',
      kind: 'historical',
    });
  });

  it('formats anything else as kind "other" verbatim', () => {
    expect(formatEvidenceRef('some free-text evidence')).toEqual({
      text: 'some free-text evidence',
      kind: 'other',
    });
  });
});
