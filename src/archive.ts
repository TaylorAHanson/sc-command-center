import { parseServerTime } from './pages/admin/time';
import type { ArchiveMarker } from './widgetRegistry';

/** What the server sends when a view's link names an archived view (`GET /api/apps/{ref}`, 410). */
export interface ArchivedView extends ArchiveMarker {
  id: string;
  name: string;
  owner: string | null;
  /** The caller manages it (or is an administrator), so Restore is theirs to press. */
  can_restore: boolean;
  /** The Settings value behind an automatic archive, for saying why. */
  unused_days?: number;
}

const day = (value?: string | null) => parseServerTime(value)?.toLocaleDateString() ?? null;

/**
 * One sentence saying who archived something and why, for a tooltip or a notice:
 * "Archived automatically on 24/11/2026 after going unused for 60 days."
 */
export const archiveNote = (marker: ArchiveMarker | null | undefined, days?: number | null): string => {
  if (!marker) return '';
  const on = day(marker.archived_at);
  const when = on ? ` on ${on}` : '';
  if (marker.reason === 'unused') {
    return `Archived automatically${when} after going unused${days ? ` for ${days} days` : ''}.`;
  }
  return `Archived${marker.archived_by ? ` by ${marker.archived_by}` : ''}${when}.`;
};
