import React, { useEffect, useRef, useState } from 'react';
import clsx from 'clsx';
import type { AppApi } from '../appApi';
import { PAGE_HEIGHT, PAGE_WIDTHS, type PageWidth } from './pagePreviewApp';

/** The tab height plus the header (h-12), the tab bar (h-9) and the frame's borders. */
const FRAME_HEIGHT = PAGE_HEIGHT + 48 + 36 + 2;

/**
 * A page widget as it will sit in a view: under a header and tab bar, at a real
 * screen width and tab height, scrolling when it is longer than the tab. The
 * frame is laid out at that width and scaled down to fit the pane; the scale
 * sits outside the capture area so snapshots are taken at full size.
 */
export const PagePreview: React.FC<{
  title: string;
  width: PageWidth;
  app: AppApi;
  note: string | null;
  onShowHome: () => void;
  children: React.ReactNode;
}> = ({ title, width, app, note, onShowHome, children }) => {
  const px = PAGE_WIDTHS.find(w => w.id === width)?.px ?? 1280;
  const onPage = app.activeTabId === 'home';
  const outer = useRef<HTMLDivElement>(null);
  const [room, setRoom] = useState(px);
  useEffect(() => {
    const el = outer.current;
    if (!el) return;
    const measure = () => setRoom(el.clientWidth);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  const scale = Math.min(1, room / px);
  return (
    <div ref={outer} className="w-full">
      {scale < 1 && (
        <p className="mb-2 text-xs text-slate-500">Shown at {Math.round(scale * 100)}% of its {px}px width.</p>
      )}
      <div style={{ width: px * scale, height: FRAME_HEIGHT * scale }}>
        <div
          id="widget-preview-capture-area"
          data-page-preview={width}
          className="bg-white rounded-lg shadow-2xl overflow-hidden border border-gray-300 flex flex-col text-gray-800"
          style={{ width: px, height: FRAME_HEIGHT, transform: scale < 1 ? `scale(${scale})` : undefined, transformOrigin: 'top left' }}
        >
          <div className="h-12 shrink-0 flex items-center justify-between px-4 border-b border-gray-200 bg-white">
            <span className="text-base font-semibold text-gray-900 truncate">{title || 'Your view'}</span>
            <span className="text-xs text-gray-500">Settings · Share</span>
          </div>
          <div className="h-9 shrink-0 flex items-end gap-1 px-3 border-b border-gray-200 bg-white" aria-hidden>
            {app.tabs.map(t => (
              <span
                key={t.id}
                className={clsx('px-3 py-1.5 text-xs border-b-2', t.id === app.activeTabId ? 'border-brand-blue text-brand-blue font-medium' : 'border-transparent text-gray-500')}
              >
                {t.name}
              </span>
            ))}
          </div>
          <div className="relative" style={{ height: PAGE_HEIGHT }}>
            <div className="h-full w-full overflow-auto bg-gray-50">
              {onPage ? children : (
                <div className="h-full flex flex-col items-center justify-center gap-2 text-sm text-gray-500">
                  <span>The “{app.tabs.find(t => t.id === app.activeTabId)?.name}” tab would show here.</span>
                  <button type="button" onClick={onShowHome} className="text-brand-blue hover:text-brand-navy">Back to the page</button>
                </div>
              )}
            </div>
            {note && (
              <div role="status" className="absolute bottom-4 left-1/2 -translate-x-1/2 max-w-lg px-4 py-2 rounded-md bg-gray-900 text-white text-xs shadow-lg">
                {note}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
