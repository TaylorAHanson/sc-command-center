import type { WidgetDefinition } from './widgetRegistry';

/**
 * Who gets the credit for a widget.
 *
 * Shared by the library cards and the leaderboard so they agree on two things:
 * which author values name an actual person, and how a person's name is written.
 * `services/creator_stats.py` applies the same rule server-side — if you add a
 * value here, add it there, or a name the library refuses to show will still turn
 * up in the ranking.
 */

/** Author values that were never a person: what an unresolved identity was written as. */
export const NOT_A_PERSON = new Set(['', 'unknown', 'dev', 'none', 'null', 'system', 'n/a']);

/** A service principal's application id, which is who called but not a person. */
const APPLICATION_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export const isPerson = (name?: string | null): boolean => {
  const value = (name || '').trim();
  return !!value && !NOT_A_PERSON.has(value.toLowerCase()) && !APPLICATION_ID.test(value);
};

/** The widget's author, or null when there isn't one worth showing. */
export const creatorOf = (widget: WidgetDefinition): string | null => {
  const name = (widget.createdBy || '').trim();
  return isPerson(name) ? name : null;
};

/** The part of an address people recognise. Show the full value in a tooltip. */
export const displayName = (username: string): string => {
  const name = (username || '').trim();
  const local = name.includes('@') ? name.slice(0, name.indexOf('@')) : name;
  return local || name || 'unknown';
};

export const isSamePerson = (a?: string | null, b?: string | null): boolean =>
  !!a && !!b && a.trim().toLowerCase() === b.trim().toLowerCase();
