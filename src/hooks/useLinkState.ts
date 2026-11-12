import React from 'react';
import { createLinkStateStore, instanceScope, type LinkStateStore } from '../linkState';

/**
 * The placed widget a component renders for (`widget.i`). The grid and a page
 * tab provide it; it is what files a widget's link settings under its own name.
 */
export const WidgetInstanceContext = React.createContext<string | null>(null);

/** Where widgets' link settings are held: the dashboard's, mirrored to the address, or a studio's own. */
export const LinkStateContext = React.createContext<LinkStateStore | null>(null);

type SetLinkState<T> = (next: T | ((previous: T) => T)) => void;

/**
 * `React.useState` whose value is saved in the page's link, injected into widget
 * code beside `useScript`. The first default stands, as with `useState`, so an
 * inline `[]` doesn't hand back a new array every render.
 *
 * Outside a placed widget (the thumbnail capture, anything else that mounts a
 * widget on its own) it is plain component state that never reaches a link.
 */
export function useLinkState<T>(key: string, initial: T): [T, SetLinkState<T>] {
  const instance = React.useContext(WidgetInstanceContext);
  const shared = React.useContext(LinkStateContext);
  const [own] = React.useState(createLinkStateStore);
  const [fallback] = React.useState(() => initial);
  const store = instance && shared ? shared : own;
  const scope = instance ? instanceScope(instance) : '';
  const held = React.useSyncExternalStore(store.subscribe, () => store.get(scope, key));

  const setValue = React.useCallback<SetLinkState<T>>(next => {
    const current = store.get(scope, key);
    const previous = (current === undefined ? fallback : current) as T;
    const value = typeof next === 'function' ? (next as (p: T) => T)(previous) : next;
    store.set(scope, key, value, fallback);
  }, [store, scope, key, fallback]);

  return [(held === undefined ? fallback : held) as T, setValue];
}
