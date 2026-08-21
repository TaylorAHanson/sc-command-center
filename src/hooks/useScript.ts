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
