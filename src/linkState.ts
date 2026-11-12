// What a view is set to, carried in its link: the dashboard variables its
// filters and emitters set, and the settings widgets keep with `useLinkState`.
// Someone who copies the address, or presses Copy link, sends what they see.
//
//   ?v.region=West&w.3f2a91c0.sort=revenue#/app/sales/overview
//
// `v.<key>` is a dashboard variable; `w.<scope>.<key>` is one widget's setting,
// where the scope is the first 8 characters of the widget's instance id. The
// state lives in the query string because the hash is the route
// (`store/appRoute.ts`), and hash sync assigns `location.hash`, which leaves the
// query string alone; neither can overwrite the other.
//
// A string goes in as it is unless it would read as JSON, so `?v.region=West`
// stays readable and the string "2025" comes back a string; everything else is
// JSON. Keys named as text (a view's filters, which only ever hold strings) are
// always plain. A value equal to its default is left out.
//
// No React and no `window` here: `tests/link_state.test.ts` runs this under Node.

export const VARIABLE_PREFIX = 'v.';
export const WIDGET_PREFIX = 'w.';

/**
 * The most the state may add to a link, in characters of query string. A whole
 * link should stay under about 2,000, where chat and email clients, proxies and
 * older tools start to cut links short or refuse them; this leaves the rest for
 * the app's address and route. Over it, the largest entries go first (ties by
 * name), so the same state always makes the same link: a filter is a few bytes,
 * and the likeliest overflow is one long value nobody meant to share.
 */
export const MAX_LINK_STATE = 1500;

/** One widget's settings by scope, then key. */
export type WidgetLinkState = Record<string, Record<string, unknown>>;

export interface LinkState {
  variables: Record<string, unknown>;
  widgets: WidgetLinkState;
}

const NO_KEYS: ReadonlySet<string> = new Set();

/** The part of a widget's instance id its settings are filed under in a link. */
export const instanceScope = (instanceId: string): string => instanceId.slice(0, 8).replace(/\./g, '-');

// `__proto__` as a key would replace a plain object's prototype rather than add a key.
const usableKey = (key: string): boolean => key !== '' && key !== '__proto__';

const isPlainObject = (value: unknown): value is Record<string, unknown> => {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false;
  const proto = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
};

// Keys in a fixed order, so equal objects write the same text however they were built.
const ordered = (value: unknown): unknown => {
  if (Array.isArray(value)) return value.map(ordered);
  if (!isPlainObject(value)) return value;
  const out: Record<string, unknown> = {};
  for (const key of Object.keys(value).sort()) out[key] = ordered(value[key]);
  return out;
};

const readsAsJson = (text: string): boolean => {
  try {
    JSON.parse(text);
    return true;
  } catch {
    return false;
  }
};

/** A value as the link spells it, or undefined for one a link can't hold (undefined, a function). */
export const encodeValue = (value: unknown, text = false): string | undefined => {
  if (value === undefined || typeof value === 'function' || typeof value === 'symbol') return undefined;
  if (typeof value === 'string') return text || !readsAsJson(value) ? value : JSON.stringify(value);
  if (text && (typeof value === 'number' || typeof value === 'boolean')) return String(value);
  try {
    return JSON.stringify(ordered(value));
  } catch {
    return undefined;
  }
};

export const decodeValue = (raw: string, text = false): unknown => {
  if (text) return raw;
  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
};

/** Whether two values would read the same in a link. */
export const sameValue = (a: unknown, b: unknown, text = false): boolean => {
  if (Object.is(a, b)) return true;
  const encoded = encodeValue(a, text);
  return encoded !== undefined && encoded === encodeValue(b, text);
};

const paramName = (part: string): string => {
  const eq = part.indexOf('=');
  const name = (eq < 0 ? part : part.slice(0, eq)).replace(/\+/g, ' ');
  try {
    return decodeURIComponent(name);
  } catch {
    return name;
  }
};

const isLinkParam = (name: string): boolean => name.startsWith(VARIABLE_PREFIX) || name.startsWith(WIDGET_PREFIX);

const parts = (search: string): string[] => search.replace(/^\?/, '').split('&').filter(Boolean);

/** The state's own params in a query string, as written; '' when it carries none. */
export const linkStatePart = (search: string): string =>
  parts(search).filter(part => isLinkParam(paramName(part))).join('&');

/** What a query string says the view is set to. `textKeys` are variables read as plain text. */
export const readLinkState = (search: string, textKeys: ReadonlySet<string> = NO_KEYS): LinkState => {
  const variables: Record<string, unknown> = {};
  const widgets: WidgetLinkState = {};
  for (const [name, raw] of new URLSearchParams(search)) {
    if (name.startsWith(VARIABLE_PREFIX)) {
      const key = name.slice(VARIABLE_PREFIX.length);
      if (usableKey(key)) variables[key] = decodeValue(raw, textKeys.has(key));
    } else if (name.startsWith(WIDGET_PREFIX)) {
      const rest = name.slice(WIDGET_PREFIX.length);
      const dot = rest.indexOf('.');
      const scope = rest.slice(0, dot);
      const key = rest.slice(dot + 1);
      if (dot <= 0 || !usableKey(scope) || !usableKey(key)) continue;
      // Own properties only: `widgets.constructor` is otherwise Object itself.
      if (!Object.prototype.hasOwnProperty.call(widgets, scope)) widgets[scope] = {};
      widgets[scope][key] = decodeValue(raw);
    }
  }
  return { variables, widgets };
};

export interface WriteOptions {
  /** What each variable starts as; one still equal to it is left out. */
  defaults?: Record<string, unknown>;
  /** Variables always written as plain text: a view's filters. */
  textKeys?: ReadonlySet<string>;
  /** Defaults to MAX_LINK_STATE. */
  max?: number;
}

interface Entry {
  name: string;
  value: string;
  size: number;
}

const joinedLength = (entries: Entry[]): number =>
  entries.reduce((sum, e) => sum + e.size, 0) + Math.max(0, entries.length - 1);

/**
 * `search` with its state replaced by `state`, other params kept as they were.
 * `dropped` names the params the cap left out, largest first.
 */
export const writeLinkState = (search: string, state: LinkState, options: WriteOptions = {}): { search: string; dropped: string[] } => {
  const { defaults = {}, textKeys = NO_KEYS, max = MAX_LINK_STATE } = options;
  const entries: Entry[] = [];
  const add = (name: string, value: string) => {
    entries.push({ name, value, size: new URLSearchParams([[name, value]]).toString().length });
  };

  for (const key of Object.keys(state.variables).sort()) {
    if (!usableKey(key)) continue;
    const text = textKeys.has(key);
    const value = encodeValue(state.variables[key], text);
    if (value === undefined) continue;
    if (Object.prototype.hasOwnProperty.call(defaults, key) && value === encodeValue(defaults[key], text)) continue;
    add(VARIABLE_PREFIX + key, value);
  }
  for (const scope of Object.keys(state.widgets).sort()) {
    if (!usableKey(scope) || scope.includes('.')) continue;
    const values = state.widgets[scope];
    for (const key of Object.keys(values).sort()) {
      const value = usableKey(key) ? encodeValue(values[key]) : undefined;
      if (value !== undefined) add(`${WIDGET_PREFIX}${scope}.${key}`, value);
    }
  }

  const dropped: string[] = [];
  let written = entries;
  if (joinedLength(entries) > max) {
    const largestFirst = [...entries].sort((a, b) => b.size - a.size || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
    const kept = new Set(entries);
    for (const entry of largestFirst) {
      if (joinedLength([...kept]) <= max) break;
      kept.delete(entry);
      dropped.push(entry.name);
    }
    written = entries.filter(e => kept.has(e));
  }

  const own = new URLSearchParams(written.map(e => [e.name, e.value])).toString();
  const others = parts(search).filter(part => !isLinkParam(paramName(part)));
  const query = [...others, own].filter(Boolean).join('&');
  return { search: query ? `?${query}` : '', dropped };
};

/**
 * The settings widgets keep with `useLinkState`, for the app on screen. Outside
 * React so a widget's change re-renders only the hooks reading it, not the whole
 * dashboard; the provider mirrors it into the address.
 */
export interface LinkStateStore {
  /** The value held for a widget's key; undefined while it is at its default. */
  get: (scope: string, key: string) => unknown;
  /** Holds `value`, or forgets the key when it equals `fallback` or is undefined. Notifies only on a change. */
  set: (scope: string, key: string, value: unknown, fallback: unknown) => void;
  snapshot: () => WidgetLinkState;
  /** Another app's settings, or none: every hook reads again. */
  replace: (widgets: WidgetLinkState) => void;
  subscribe: (listener: () => void) => () => void;
}

const toMaps = (widgets: WidgetLinkState): Map<string, Map<string, unknown>> => {
  const out = new Map<string, Map<string, unknown>>();
  for (const [scope, values] of Object.entries(widgets)) {
    const held = new Map(Object.entries(values).filter(([, v]) => v !== undefined));
    if (held.size) out.set(scope, held);
  }
  return out;
};

// Maps rather than objects, so a key like `toString` is never read off a prototype.
export const createLinkStateStore = (initial: WidgetLinkState = {}): LinkStateStore => {
  let state = toMaps(initial);
  const listeners = new Set<() => void>();
  const notify = () => listeners.forEach(listener => listener());

  const subscribe = (listener: () => void) => {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  };

  const set = (scope: string, key: string, value: unknown, fallback: unknown) => {
    const values = state.get(scope);
    if (value === undefined || sameValue(value, fallback)) {
      if (!values?.has(key)) return;
      values.delete(key);
      if (!values.size) state.delete(scope);
    } else {
      if (values?.has(key) && sameValue(values.get(key), value)) return;
      if (values) values.set(key, value);
      else state.set(scope, new Map([[key, value]]));
    }
    notify();
  };

  return {
    get: (scope, key) => state.get(scope)?.get(key),
    set,
    snapshot: () => {
      const out: WidgetLinkState = {};
      for (const [scope, values] of state) if (usableKey(scope)) out[scope] = Object.fromEntries(values);
      return out;
    },
    replace: widgets => {
      state = toMaps(widgets);
      notify();
    },
    subscribe,
  };
};
