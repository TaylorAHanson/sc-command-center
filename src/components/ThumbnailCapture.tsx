import React from 'react';
import { toPng } from 'html-to-image';
import type { WidgetProps } from '../widgetRegistry';
import { ExecuteActionPropInjector } from '../contexts/ActionContext';
import { BaseWidget } from './BaseWidget';

interface CaptureOptions {
  component: React.ComponentType<WidgetProps>;
  defaultProps?: Record<string, any>;
  widgetId: string;
  widgetName?: string;
  width?: number;
  height?: number;
  settleMs?: number;
  contextData?: Record<string, any>;
}

// ────────────────────────────────────────────────────────────────────────────
// Thumbnail capture host
//
// We render thumbnails through a single host component that's mounted once
// inside the main React tree (via <ThumbnailCaptureHost /> in App.tsx). This
// preserves all context providers (DashboardProvider, etc.), which matters
// because BaseWidget calls useDashboardStore() at the top of its useActionLogger
// hook — running it in a detached createRoot tree throws and produces blank
// captures.
//
// Captures are serialized through a global queue so we never mount more than
// one widget at a time, no matter how many requests arrive at once.
// ────────────────────────────────────────────────────────────────────────────

type CaptureRequest = {
  opts: CaptureOptions;
  resolve: (value: string | null) => void;
};

let hostController: {
  enqueue: (req: CaptureRequest) => void;
} | null = null;

const pending: CaptureRequest[] = [];

export const captureWidgetThumbnail = (opts: CaptureOptions): Promise<string | null> => {
  return new Promise(resolve => {
    const req: CaptureRequest = { opts, resolve };
    if (hostController) {
      console.log('[ThumbnailCapture] enqueue (host ready)', opts.widgetId);
      hostController.enqueue(req);
    } else {
      // Host hasn't mounted yet; buffer and flush when it does.
      console.log('[ThumbnailCapture] enqueue (no host yet, buffering)', opts.widgetId);
      pending.push(req);
    }
  });
};

class CaptureErrorBoundary extends React.Component<{ children: React.ReactNode }, { errored: boolean; message: string }> {
  constructor(props: any) { super(props); this.state = { errored: false, message: '' }; }
  static getDerivedStateFromError(err: any) { return { errored: true, message: err?.message || String(err) }; }
  componentDidCatch(err: any) { console.warn('Widget threw during thumbnail capture', err); }
  render() {
    if (this.state.errored) {
      return (
        <div className="flex flex-col items-center justify-center h-full w-full text-gray-400 text-xs p-4 text-center">
          <span className="font-semibold">Preview unavailable</span>
          <span className="opacity-60 mt-1 line-clamp-3">{this.state.message}</span>
        </div>
      );
    }
    return this.props.children;
  }
}

const CAPTURE_CONTAINER_ID = '__sccc_thumbnail_capture_container__';

// Mount once at the App level. Reads the queue, renders one widget at a time
// into a hidden portal node, captures, then advances.
export const ThumbnailCaptureHost: React.FC = () => {
  const [current, setCurrent] = React.useState<CaptureRequest | null>(null);
  const queueRef = React.useRef<CaptureRequest[]>([]);
  const processingRef = React.useRef(false);
  const captureNodeRef = React.useRef<HTMLDivElement>(null);

  const processNext = React.useCallback(() => {
    if (processingRef.current) return;
    const next = queueRef.current.shift();
    if (!next) return;
    processingRef.current = true;
    setCurrent(next);
  }, []);

  const enqueue = React.useCallback((req: CaptureRequest) => {
    queueRef.current.push(req);
    processNext();
  }, [processNext]);

  // Expose the enqueue function and flush any requests that arrived before mount.
  React.useEffect(() => {
    console.log('[ThumbnailCapture] host mounted, flushing', pending.length, 'pending');
    hostController = { enqueue };
    while (pending.length > 0) {
      const r = pending.shift();
      if (r) enqueue(r);
    }
    return () => {
      console.log('[ThumbnailCapture] host unmounted');
      hostController = null;
    };
  }, [enqueue]);

  // When `current` is set, wait for the widget to settle, capture, resolve,
  // unmount (by clearing state), and advance to the next request.
  React.useEffect(() => {
    if (!current) return;
    let cancelled = false;
    let settled = false;
    const settleMs = current.opts.settleMs ?? 2500;
    // Hard ceiling so a single hung widget (e.g. html-to-image getting stuck
    // on a CORS image or web font load) can't stall the whole queue.
    const HARD_TIMEOUT_MS = settleMs + 6000;

    const finalize = (result: string | null, reason: string) => {
      if (settled) return;
      settled = true;
      console.log('[ThumbnailCapture]', current.opts.widgetId, 'finalized:', reason);
      try { current.resolve(result); } catch { /* ignore */ }
      // Defer state reset to the next tick so any React updates settle first.
      setTimeout(() => {
        setCurrent(null);
        processingRef.current = false;
        setTimeout(processNext, 50);
      }, 0);
    };

    const hardTimer = window.setTimeout(() => {
      finalize(null, `hard timeout after ${HARD_TIMEOUT_MS}ms`);
    }, HARD_TIMEOUT_MS);

    const run = async () => {
      console.log('[ThumbnailCapture]', current.opts.widgetId, 'starting');
      try {
        await new Promise<void>(resolve => {
          const ric: any = (window as any).requestIdleCallback;
          if (ric) {
            ric(() => setTimeout(resolve, settleMs), { timeout: settleMs + 500 });
          } else {
            setTimeout(resolve, settleMs);
          }
        });
        await new Promise<void>(resolve =>
          requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
        );

        if (cancelled || settled) return;
        const node = captureNodeRef.current;
        if (!node) {
          finalize(null, 'capture node missing');
          return;
        }
        // Race the capture itself against a soft timeout so toPng can't hang
        // forever. The outer hardTimer is a backstop for any other stall.
        const dataUrl = await Promise.race<string | null>([
          toPng(node, { cacheBust: true, pixelRatio: 1, backgroundColor: '#ffffff' }),
          new Promise<string | null>(resolve => setTimeout(() => resolve(null), 5000)),
        ]);
        if (cancelled || settled) return;
        finalize(dataUrl, dataUrl ? 'success' : 'toPng returned null/timed out');
      } catch (err) {
        console.warn('Thumbnail capture failed for', current.opts.widgetId, err);
        finalize(null, `error: ${(err as Error)?.message || String(err)}`);
      }
    };
    run();

    return () => {
      // NOTE: do NOT call finalize() here. React 18's StrictMode unmounts +
      // remounts every effect in dev, which would otherwise cause every widget
      // to resolve `null` from the very first cycle. Instead, just signal the
      // in-flight run() to bail; the freshly-mounted effect will start a new
      // hard timer + new run() that owns the actual resolution.
      cancelled = true;
      window.clearTimeout(hardTimer);
    };
  }, [current, processNext]);

  if (!current) return null;

  const { component: Component, defaultProps, widgetId, widgetName, width = 480, height = 320, contextData } = current.opts;

  const data = {
    ...(defaultProps || {}),
    username: 'preview',
    variables: {},
    setVariable: () => { },
    ...(contextData || {}),
  };

  // The host element is positioned visibly *within the viewport* but hidden
  // with opacity:0 + z-index:-1. Far-offscreen positioning (e.g. left:-100000px)
  // caused some widgets and chart libraries to skip layout work, yielding blank
  // captures. Keeping it in the viewport bounds ensures full paint + layout.
  return (
    <div
      id={CAPTURE_CONTAINER_ID}
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        width,
        height,
        zIndex: -1,
        opacity: 0,
        pointerEvents: 'none',
        overflow: 'hidden',
        background: '#ffffff',
      }}
      aria-hidden="true"
    >
      <div ref={captureNodeRef} style={{ width: '100%', height: '100%', background: '#ffffff' }}>
        {/* Outer boundary protects against BaseWidget itself throwing (e.g. if
            a future change makes its hooks dependent on a context that isn't
            available here). Without this, an error in BaseWidget would unmount
            the entire app's React tree. */}
        <CaptureErrorBoundary>
          <BaseWidget
            id={`thumb-${widgetId}`}
            title={widgetName || 'Preview'}
            className="h-full w-full"
          >
            <CaptureErrorBoundary>
              <ExecuteActionPropInjector>
                <React.Suspense fallback={null}>
                  <Component id={`thumb-${widgetId}`} data={data} />
                </React.Suspense>
              </ExecuteActionPropInjector>
            </CaptureErrorBoundary>
          </BaseWidget>
        </CaptureErrorBoundary>
      </div>
    </div>
  );
};

