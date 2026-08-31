import { useState, useEffect } from 'react';

/**
 * Resolve a dotted global path: `Highcharts` or `Highcharts.mapChart`.
 *
 * Only used as a fallback when a script fails to load — see the effect below.
 */
const resolveGlobal = (path: string): unknown =>
    path.split('.').reduce<unknown>(
        (at, part) => (at == null ? at : (at as Record<string, unknown>)[part]),
        window,
    );

/**
 * CDN hosts a widget may load a library from.
 *
 * Widget code is generated from a natural-language prompt and can also be typed
 * or imported by hand, so the url reaching this hook is untrusted input that ends
 * up as a `<script>` on the same origin as the app. The generator prompt has
 * always told the model to use jsDelivr, but a prompt is advice; this is the
 * enforcement. Keep it in step with the CDN rule in
 * `server/routes/agent_instructions.md`, and with the preloads in `index.html`
 * (unpkg for Babel, code.highcharts.com for Highcharts) — a host used there but
 * missing here would block a widget from loading its own copy.
 */
const ALLOWED_SCRIPT_HOSTS = new Set([
    'cdn.jsdelivr.net',
    'code.highcharts.com',
    'unpkg.com',
    'cdnjs.cloudflare.com',
]);

/**
 * Whether `url` may become a script tag.
 *
 * Same-origin urls pass whatever the scheme, because that is the app serving its
 * own assets (and dev runs on http). Everything else must be https from an
 * allowlisted host, which is what rejects `javascript:` and `data:` payloads —
 * they parse fine as URLs and fail on the protocol test.
 */
export const isAllowedScriptUrl = (url: string): boolean => {
    let parsed: URL;
    try {
        parsed = new URL(url, window.location.href);
    } catch {
        return false;
    }
    if (parsed.origin === window.location.origin) return true;
    return parsed.protocol === 'https:' && ALLOWED_SCRIPT_HOSTS.has(parsed.hostname);
};

/**
 * Load a library from a CDN and report when it is ready.
 *
 * **The decision to fetch is made on the url, never on `name`.** It used to be
 * made on `window[name]`, and that quietly broke every plugin module: a
 * Highcharts module (maps, exporting, treemap) attaches to the `Highcharts`
 * that is already there rather than creating a global of its own, so the check
 * passed, the script was never appended, and the widget died on
 * `Highcharts.mapChart is not a function`. `index.html` preloads Highcharts,
 * which made this unconditional — no widget's own Highcharts url has ever
 * actually been fetched.
 *
 * That is also why this can't be solved by telling the generating model to pass
 * a different `name`: it has to hold for whatever the model writes, including
 * the obvious `useScript(mapUrl, 'Highcharts')`. `name` now only says what to
 * fall back to if the fetch fails.
 */
export const useScript = (url: string, name: string) => {
    const [loaded, setLoaded] = useState(false);
    const [error, setError] = useState(false);

    useEffect(() => {
        // An empty url is how a widget says "not yet", so a module can wait for
        // the library it attaches to. Hooks can't be called conditionally, so
        // there is no other way to order two of them.
        if (!url) {
            setLoaded(false);
            setError(false);
            return;
        }

        // Refused before a tag exists, so a blocked url is never fetched or run.
        // Reported as a load error, which widgets already handle, rather than by
        // throwing and taking the panel down.
        if (!isAllowedScriptUrl(url)) {
            console.error(
                `useScript refused to load "${url}": scripts must be https from an allowlisted CDN ` +
                `(${[...ALLOWED_SCRIPT_HOSTS].join(', ')}).`,
            );
            setLoaded(false);
            setError(true);
            return;
        }

        let script = document.querySelector(`script[src="${url}"]`) as HTMLScriptElement | null;

        if (!script) {
            script = document.createElement('script');
            script.src = url;
            // NOT async. For a script inserted this way, `async = false` is what
            // makes the browser run it in insertion order, so a module appended
            // after its library still runs after it even though both requests
            // are in flight at once. With async it was a race, and the module
            // losing it throws "Highcharts is not defined".
            script.async = false;
            script.setAttribute('data-status', 'loading');
            document.body.appendChild(script);
        }

        const settled = script;

        const onLoad = () => {
            settled.setAttribute('data-status', 'ready');
            setLoaded(true);
            setError(false);
        };

        const onError = () => {
            settled.setAttribute('data-status', 'error');
            // A blocked or missing CDN is survivable when the library is already
            // on the page by other means (index.html preloads Highcharts). This
            // is the only thing `name` is for.
            const present = Boolean(resolveGlobal(name));
            setLoaded(present);
            setError(!present);
        };

        script.addEventListener('load', onLoad);
        script.addEventListener('error', onError);

        // A tag left by an earlier mount has already fired its events.
        const status = script.getAttribute('data-status');
        if (status === 'ready') {
            setLoaded(true);
            setError(false);
        } else if (status === 'error') {
            onError();
        }

        return () => {
            settled.removeEventListener('load', onLoad);
            settled.removeEventListener('error', onError);
        };
    }, [url, name]);

    return [loaded, error];
};
