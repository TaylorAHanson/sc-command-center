import { useState, useEffect } from 'react';

export const useScript = (url: string, name: string) => {
    const [loaded, setLoaded] = useState(false);
    const [error, setError] = useState(false);

    useEffect(() => {
        // Check if it's already on the window (e.g. window.Highcharts)
        if ((window as any)[name]) {
            setLoaded(true);
            return;
        }

        // Check if script is already in the document
        let script = document.querySelector(`script[src="${url}"]`) as HTMLScriptElement;

        if (!script) {
            script = document.createElement('script');
            script.src = url;
            script.async = true;
            script.setAttribute('data-status', 'loading');
            document.body.appendChild(script);
        }

        const setAttributeFromEvent = (event: Event) => {
            script.setAttribute('data-status', event.type === 'load' ? 'ready' : 'error');
        };

        script.addEventListener('load', setAttributeFromEvent);
        script.addEventListener('error', setAttributeFromEvent);

        const setStateFromEvent = (event: Event) => {
            if (event.type === 'load') {
                setLoaded(true);
                setError(false);
            } else {
                setLoaded(false);
                setError(true);
            }
        };

        script.addEventListener('load', setStateFromEvent);
        script.addEventListener('error', setStateFromEvent);

        if (script.getAttribute('data-status') === 'ready') {
            setLoaded(true);
            setError(false);
        } else if (script.getAttribute('data-status') === 'error') {
            setLoaded(false);
            setError(true);
        }

        return () => {
            if (script) {
                script.removeEventListener('load', setStateFromEvent);
                script.removeEventListener('error', setStateFromEvent);
                script.removeEventListener('load', setAttributeFromEvent);
                script.removeEventListener('error', setAttributeFromEvent);
            }
        };
    }, [url, name]);

    return [loaded, error];
};
