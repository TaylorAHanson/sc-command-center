import React, { useState } from 'react';
import { Archive, ArchiveRestore, Loader2 } from 'lucide-react';
import { archiveNote, type ArchivedView } from '../archive';
import { displayName } from '../creators';

/**
 * What a link to an archived view opens: the view's name, who archived it and
 * why, and Restore for the people who manage it. Everyone else is told whom to
 * ask. Archiving deletes nothing, so this is never a dead end.
 */
export const ArchivedViewNotice: React.FC<{
  view: ArchivedView;
  onRestore: () => Promise<string | null>;
  onDismiss: () => void;
}> = ({ view, onRestore, onDismiss }) => {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const restore = async () => {
    setBusy(true);
    setError(null);
    const refusal = await onRestore();
    setBusy(false);
    if (refusal) setError(refusal);
  };

  return (
    <div className="absolute inset-0 z-30 flex items-center justify-center overflow-y-auto bg-brand-navy/30 backdrop-blur-sm p-6">
      <div
        role="dialog"
        aria-labelledby="archived-view-title"
        className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl ring-1 ring-black/5"
      >
        <div className="flex items-start gap-3">
          <div className="rounded-full bg-amber-50 p-2 text-amber-600"><Archive size={20} aria-hidden="true" /></div>
          <div className="min-w-0">
            <h2 id="archived-view-title" className="text-lg font-semibold text-gray-900">
              “{view.name || 'This view'}” is archived
            </h2>
            <p className="mt-1 text-sm text-gray-600">{archiveNote(view, view.unused_days)}</p>
            <p className="mt-2 text-sm text-gray-600">
              {view.can_restore
                ? 'Nothing was deleted. Restore it to bring it back, exactly as it was, for everyone it is shared with.'
                : `Nothing was deleted. Ask ${view.owner ? displayName(view.owner) : 'someone who manages it'} to restore it.`}
            </p>
            {error && <p role="alert" className="mt-2 text-sm text-red-600">{error}</p>}
          </div>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onDismiss}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
          >
            Close
          </button>
          {view.can_restore && (
            <button
              type="button"
              onClick={() => { void restore(); }}
              disabled={busy}
              className="inline-flex items-center gap-1.5 rounded-md bg-brand-blue px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-navy disabled:opacity-60"
            >
              {busy ? <Loader2 size={15} className="animate-spin" /> : <ArchiveRestore size={15} />}
              Restore
            </button>
          )}
        </div>
      </div>
    </div>
  );
};
