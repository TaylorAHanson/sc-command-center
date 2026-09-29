import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Loader2 } from 'lucide-react';
import type { Loader } from 'vega';
import type { EmbedOptions, Result, VisualizationSpec } from 'vega-embed';

export type ChartMode = 'vega-lite' | 'vega';

// Fence languages the chat draws instead of printing. The runtime contract asks
// for `vega-lite`; the others are what models reach for when they improvise.
export const CHART_FENCE_MODES: ReadonlyMap<string, ChartMode> = new Map([
    ['vega-lite', 'vega-lite'],
    ['vegalite', 'vega-lite'],
    ['vega-lite-json', 'vega-lite'],
    ['vega', 'vega'],
]);

// The spec is written by a model that may have read prompt-injected tool output,
// so it must not reach the network: a data URL, an image mark or an `href` could
// carry the user's data to another host. Every loader entry point refuses, which
// leaves inline `data.values` as the only thing that renders.
const refuse = (what: string) => () =>
    Promise.reject(new Error(`${what} is disabled in chat charts; only inline data.values can be drawn`));
const BLOCKED_LOADER: Loader = {
    load: refuse('Loading external data'),
    // Answering with no href, rather than rejecting, is what Vega's callers read as
    // "nothing to link or load": the SVG export dereferences a rejection's null and
    // throws. Without an href a clicked mark's anchor goes nowhere and images stay blank.
    sanitize: () => Promise.resolve({} as { href: string }),
    http: refuse('Fetching URLs'),
    file: refuse('Reading files'),
};

// vega-tooltip turns an `image` field into an <img src> without asking the
// loader, so its default formatter is replaced by one that never emits a URL.
// `escape` is vega-tooltip's HTML escaper.
function formatTooltip(value: unknown, escape: (v: unknown) => string): string {
    const text = (v: unknown) => (v !== null && typeof v === 'object' ? JSON.stringify(v) : v);
    if (Array.isArray(value)) return `[${value.map(v => escape(text(v))).join(', ')}]`;
    if (value === null || typeof value !== 'object') return escape(value);
    const fields = { ...(value as Record<string, unknown>) };
    const title = fields.title;
    delete fields.title;
    delete fields.image;
    const rows = Object.entries(fields)
        .filter(([, v]) => v !== undefined)
        .map(([k, v]) => `<tr><td class="key">${escape(k)}</td><td class="value">${escape(text(v))}</td></tr>`);
    const html = (title ? `<h2>${escape(title)}</h2>` : '') + (rows.length ? `<table>${rows.join('')}</table>` : '');
    return html || '{}';
}

const EMBED_OPTIONS: EmbedOptions = {
    renderer: 'svg',
    // Export only: the editor action posts the spec to vega.github.io, and
    // source/compiled open it in a new window, neither of which a chat reader needs.
    actions: { export: { png: true, svg: true }, source: false, compiled: false, editor: false },
    // Interpret expressions from the AST instead of compiling them with Function:
    // the expressions are model-written, and this is also the CSP-safe path.
    ast: true,
    loader: BLOCKED_LOADER,
    tooltip: { formatTooltip },
    downloadFileName: 'chart',
    // Spec config still wins; these are only defaults suited to a narrow light bubble.
    config: {
        background: '#ffffff',
        view: { continuousHeight: 220 },
    },
};

type Parsed = { spec: VisualizationSpec; fitsWidth: boolean } | { error: string };

function findUrl(value: unknown): boolean {
    if (Array.isArray(value)) return value.some(findUrl);
    if (value === null || typeof value !== 'object') return false;
    return Object.entries(value).some(([k, v]) => (k === 'url' && typeof v === 'string') || findUrl(v));
}

function parseSpec(source: string, mode: ChartMode): Parsed {
    let raw: unknown;
    try {
        raw = JSON.parse(source);
    } catch (err) {
        return { error: `the spec isn't valid JSON (${err instanceof Error ? err.message : String(err)})` };
    }
    if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) {
        return { error: 'the spec must be a JSON object' };
    }
    // The loader would refuse these anyway, but silently, leaving an empty chart.
    if (findUrl(raw)) return { error: 'it refers to a URL; charts here can only use inline data.values' };
    // vega-embed merges `usermeta.embedOptions` over the options passed in, which
    // would let the spec turn `ast` off or put the editor action back.
    const spec = { ...(raw as Record<string, unknown>) };
    delete spec.usermeta;
    // A single view sized to the bubble rather than Vega-Lite's fixed 300px or
    // 20px-per-category default, which overflows a narrow drawer.
    if (mode === 'vega-lite' && spec.width === undefined && ('mark' in spec || 'layer' in spec)) {
        spec.width = 'container';
    }
    return { spec: spec as VisualizationSpec, fitsWidth: mode === 'vega-lite' && spec.width === 'container' };
}

function describe(err: unknown): string {
    const message = err instanceof Error ? err.message : String(err);
    return message.length > 200 ? `${message.slice(0, 200)}…` : message;
}

const DrawingPlaceholder: React.FC = () => (
    <div className="flex items-center gap-2 px-1 py-2 text-xs text-gray-500">
        <Loader2 className="w-3.5 h-3.5 animate-spin" />
        Drawing chart…
    </div>
);

/**
 * A chart the agent wrote as a fenced Vega-Lite (or Vega) spec. Vega is loaded
 * with `import()` on first mount so it costs nothing until a chart is on screen.
 * `fallback` is the code block exactly as markdown would have rendered it, shown
 * with the reason when the spec can't be drawn.
 */
export const VegaChart: React.FC<{
    source: string;
    mode: ChartMode;
    streaming: boolean;
    fallback: React.ReactNode;
}> = ({ source, mode, streaming, fallback }) => {
    const hostRef = useRef<HTMLDivElement>(null);
    // Keyed by source so a changed spec never shows the previous one's outcome.
    const [drawn, setDrawn] = useState<string | null>(null);
    const [failure, setFailure] = useState<{ source: string; message: string } | null>(null);

    // Mid-stream the fence is unclosed and the JSON is a prefix; don't try yet.
    const parsed = useMemo(() => (streaming ? null : parseSpec(source, mode)), [source, mode, streaming]);

    useEffect(() => {
        const host = hostRef.current;
        if (!host || !parsed || 'error' in parsed) return;
        let cancelled = false;
        let result: Result | undefined;
        let observer: ResizeObserver | undefined;
        // A fresh node per run, so a render that resolves after its cleanup (StrictMode,
        // a quick spec change) can't draw over the one that replaced it.
        const target = document.createElement('div');
        target.style.display = 'block';
        target.style.width = '100%';
        host.appendChild(target);

        Promise.all([import('vega-embed'), import('vega-interpreter')])
            .then(async ([{ default: embed }, { expressionInterpreter }]) => {
                if (cancelled) return;
                const r = await embed(target, parsed.spec, { ...EMBED_OPTIONS, mode, expr: expressionInterpreter });
                if (cancelled) {
                    r.finalize();
                    return;
                }
                result = r;
                setDrawn(source);
                if (!parsed.fitsWidth) return;
                // Vega re-measures a container-width chart only on window resize, and
                // the drawer is resized by dragging its edge.
                let lastWidth = r.view.container()?.clientWidth ?? 0;
                observer = new ResizeObserver(() => {
                    const width = r.view.container()?.clientWidth ?? 0;
                    if (!width || width === lastWidth) return;
                    lastWidth = width;
                    try {
                        r.view.signal('width', width).runAsync().catch(() => {});
                    } catch {
                        // A spec with no top-level width signal just keeps its size.
                    }
                });
                observer.observe(host);
            })
            .catch(err => {
                if (!cancelled) setFailure({ source, message: describe(err) });
            });

        return () => {
            cancelled = true;
            observer?.disconnect();
            result?.finalize();
            target.remove();
        };
    }, [parsed, mode, source]);

    if (streaming) return <DrawingPlaceholder />;

    const error = parsed && 'error' in parsed ? parsed.error : failure?.source === source ? failure.message : null;
    if (error) {
        return (
            <>
                {fallback}
                <p className="not-prose -mt-2 mb-2 text-[11px] leading-snug text-rose-600">Couldn't draw this chart: {error}</p>
            </>
        );
    }

    return (
        // not-prose: the typography plugin would restyle the export menu's links.
        // pr-2.5 absorbs the menu's -9px right offset so opening it doesn't scroll.
        <div className="not-prose my-2 max-w-full overflow-x-auto rounded-md border border-gray-200 bg-white p-2 pr-2.5 text-gray-800">
            <div ref={hostRef} />
            {drawn !== source && <DrawingPlaceholder />}
        </div>
    );
};

export default VegaChart;
