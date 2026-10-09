import React from 'react';
import clsx from 'clsx';
import { CONTENT_ENVS, CONTENT_ENV_LABELS, setContentEnv, type ContentEnv } from '../contentEnv';
import { useContentEnv, useWorkspaceAccess } from '../hooks/useContentEnv';

const SELECTED: Record<ContentEnv, string> = {
  dev: 'bg-sky-600 text-white border-sky-600',
  test: 'bg-amber-500 text-white border-amber-500',
  prod: 'bg-emerald-600 text-white border-emerald-600',
};

const ABOUT = 'Widgets, views and agents in this app. Promotion copies between these. Not which Command Center was deployed.';
const NEED_PERM = 'Dev and Test need Editor or Admin on a domain.';

/**
 * Dev / Test / Prod for authored content in *this* app, in the sidebar. The
 * amber deployment badge is a different thing: that names which Databricks App
 * you opened.
 */
export const ContentEnvSwitch: React.FC<{ compact?: boolean }> = ({ compact = false }) => {
  const [env] = useContentEnv();
  const { canSwitch } = useWorkspaceAccess();

  return (
    <div
      className={clsx('flex flex-col gap-1', compact && 'items-center')}
      title={canSwitch ? ABOUT : `${ABOUT} ${NEED_PERM}`}
    >
      <div className={clsx('flex items-center', !compact && 'gap-2')}>
        {!compact && (
          <span className="text-[10px] font-semibold uppercase tracking-wider shrink-0 text-gray-500">
            Workspace
          </span>
        )}
        <div
          role="radiogroup"
          aria-label="Workspace"
          className={clsx('inline-flex rounded-md border border-gray-600 overflow-hidden', compact && 'flex-col')}
        >
          {CONTENT_ENVS.map(option => {
            const on = option === env;
            const locked = !canSwitch && option !== 'prod';
            return (
              <button
                key={option}
                type="button"
                role="radio"
                aria-checked={on}
                disabled={locked}
                title={locked ? NEED_PERM : undefined}
                onClick={() => {
                  if (option !== env) setContentEnv(option);
                }}
                className={clsx(
                  'px-2 font-semibold uppercase tracking-wide transition-colors',
                  compact ? 'py-1 text-[9px] leading-none' : 'py-1 text-[11px]',
                  on ? SELECTED[option] : locked ? 'text-gray-600 cursor-not-allowed' : 'text-gray-400 hover:text-white hover:bg-gray-800',
                )}
              >
                {compact ? option[0] : CONTENT_ENV_LABELS[option]}
              </button>
            );
          })}
        </div>
      </div>
      {!compact && !canSwitch && (
        <span className="text-[10px] leading-tight text-gray-500">{NEED_PERM}</span>
      )}
    </div>
  );
};
