import React, { useEffect, useState } from 'react';
import { Trophy, X, AlertCircle, RefreshCw } from 'lucide-react';
import clsx from 'clsx';
import { displayName, isSamePerson } from '../creators';

/**
 * Who is building the widgets other people use.
 *
 * Deliberately a small panel rather than a page: it is a nudge and a way to find
 * a prolific colleague's work, not a performance review. Clicking a name filters
 * the library to their widgets, which is the thing that makes it useful rather
 * than decorative.
 */

export type Creator = {
  username: string;
  rank: number;
  score: number;
  /** Live widgets they authored. */
  published: number;
  /** Other people with one of their widgets on a view. */
  reach: number;
  /** Times their widgets appear across everyone's views. */
  placements: number;
  /** Times their widgets were added from the library. */
  adds: number;
};

type Board = {
  creators: Creator[];
  total_creators: number;
  unattributed_widgets: number;
};

const MEDALS = ['bg-amber-100 text-amber-700 border-amber-200',
  'bg-slate-100 text-slate-600 border-slate-300',
  'bg-orange-100 text-orange-700 border-orange-200'];

const rankStyle = (rank: number) =>
  MEDALS[rank - 1] || 'bg-gray-50 text-gray-500 border-gray-200';

export const CreatorLeaderboard: React.FC<{
  onClose: () => void;
  /** Filter the library to one person's widgets. */
  onSelect: (username: string) => void;
  /** Whose row to mark as "you". */
  currentUser: string | null;
  selected: string | null;
}> = ({ onClose, onSelect, currentUser, selected }) => {
  const [board, setBoard] = useState<Board | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    fetch('/api/widgets/creators?limit=10')
      .then(async res => {
        if (!res.ok) {
          const body = await res.json().catch(() => null);
          throw new Error(body?.detail || res.statusText);
        }
        return res.json();
      })
      .then(data => { if (live) setBoard(data); })
      .catch(e => { if (live) setError(e instanceof Error ? e.message : String(e)); });
    return () => { live = false; };
  }, []);

  return (
    <div className="absolute right-4 top-14 z-40 w-[22rem] bg-white border border-gray-200 rounded-lg shadow-xl overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-gray-100 bg-gray-50">
        <div className="flex items-center gap-2">
          <Trophy className="w-4 h-4 text-amber-500" />
          <h3 className="text-sm font-semibold text-qualcomm-navy">Top creators</h3>
        </div>
        <button onClick={onClose} className="p-1 rounded hover:bg-gray-200 text-gray-500" aria-label="Close leaderboard">
          <X className="w-4 h-4" />
        </button>
      </div>

      {error ? (
        <div className="p-4 text-xs text-gray-600 flex items-start gap-2">
          <AlertCircle className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" />
          <span>Couldn't load the leaderboard. {error}</span>
        </div>
      ) : !board ? (
        <div className="p-6 flex items-center justify-center text-gray-400">
          <RefreshCw className="w-4 h-4 animate-spin" />
        </div>
      ) : board.creators.length === 0 ? (
        <div className="p-4 text-xs text-gray-500">
          No published widgets are credited to anyone yet. Publish one from Widget Studio
          and you'll be the first.
        </div>
      ) : (
        <>
          <ul className="max-h-80 overflow-y-auto divide-y divide-gray-50">
            {board.creators.map(creator => {
              const isMe = isSamePerson(creator.username, currentUser);
              const isSelected = isSamePerson(creator.username, selected);
              return (
                <li key={creator.username}>
                  <button
                    onClick={() => onSelect(creator.username)}
                    title={`${creator.username} — show their widgets`}
                    className={clsx(
                      'w-full text-left px-3 py-2 flex items-center gap-3 transition-colors',
                      isSelected ? 'bg-blue-50' : 'hover:bg-gray-50'
                    )}
                  >
                    <span className={clsx(
                      'w-6 h-6 shrink-0 rounded-full border text-[11px] font-bold flex items-center justify-center',
                      rankStyle(creator.rank)
                    )}>
                      {creator.rank}
                    </span>

                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-1.5">
                        <span className="text-sm font-medium text-qualcomm-navy truncate">
                          {displayName(creator.username)}
                        </span>
                        {isMe && (
                          <span className="text-[9px] uppercase font-bold tracking-wider text-qualcomm-blue bg-blue-50 border border-blue-100 px-1 rounded">
                            you
                          </span>
                        )}
                      </span>
                      <span className="block text-[11px] text-gray-500 truncate">
                        {creator.published} widget{creator.published === 1 ? '' : 's'}
                        {' · '}{creator.reach} {creator.reach === 1 ? 'person' : 'people'}
                        {' · '}{creator.placements} placement{creator.placements === 1 ? '' : 's'}
                      </span>
                    </span>

                    <span className="text-sm font-semibold text-gray-700 tabular-nums">{creator.score}</span>
                  </button>
                </li>
              );
            })}
          </ul>

          <div className="px-3 py-2 border-t border-gray-100 bg-gray-50 text-[11px] text-gray-500 leading-relaxed">
            Ranked on widgets published, how many people use them, and where they're placed.
            {board.unattributed_widgets > 0 && (
              <span className="block mt-1 text-amber-700">
                {board.unattributed_widgets} widget{board.unattributed_widgets === 1 ? '' : 's'}{' '}
                {board.unattributed_widgets === 1 ? 'has' : 'have'} no author recorded.
              </span>
            )}
          </div>
        </>
      )}
    </div>
  );
};
