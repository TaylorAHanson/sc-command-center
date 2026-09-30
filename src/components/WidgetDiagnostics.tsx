import React, { useState } from 'react';
import { AlertCircle, AlertTriangle, ChevronDown, ChevronUp, Info, Loader2, Wrench } from 'lucide-react';
import type { LintFinding } from '../widgetLint';
import { formatLintFinding } from '../widgetLint';
import type { RuntimeEntry } from '../widgetRuntime';
import { formatRuntimeEntry } from '../widgetRuntime';

export type RuntimeStatus = 'idle' | 'running' | 'settled' | 'not-run';

/**
 * The studio's Problems panel: what the checks found in the code, and what the
 * widget did when it last ran in the preview.
 *
 * Both lists also go to the agent with every request, so this is the user's
 * view of what the agent is being told — and "Fix with agent" sends exactly
 * these lines, so what gets fixed is what is on screen.
 */
export const WidgetDiagnostics: React.FC<{
    findings: LintFinding[];
    runtime: RuntimeEntry[];
    runtimeStatus: RuntimeStatus;
    busy: boolean;
    onFix: (prompt: string) => void;
}> = ({ findings, runtime, runtimeStatus, busy, onFix }) => {
    const [open, setOpen] = useState(false);

    const errors = findings.filter(f => f.severity === 'error').length;
    const warnings = findings.length - errors;
    const runtimeProblems = runtime.filter(e => e.level !== 'info');
    const runtimeErrors = runtime.filter(e => e.level === 'error').length;
    const actionable = findings.length > 0 || runtimeProblems.length > 0;

    const fix = () => {
        const lines = [
            ...findings.map(formatLintFinding),
            ...runtimeProblems.map(e => `when it ran: ${formatRuntimeEntry(e)}`),
        ];
        onFix(
            'Fix these problems the studio found in the widget. Leave anything that is plainly a '
            + 'false positive, or can only be fixed outside the code, and say so.\n\n'
            + lines.map(line => `- ${line}`).join('\n'),
        );
    };

    const runtimeLabel = runtimeStatus === 'running' ? 'running…'
        : runtimeStatus === 'not-run' ? 'not run (open Live Preview)'
            : runtimeStatus === 'idle' ? 'waiting for the preview'
                : runtimeErrors ? `${runtimeErrors} error${runtimeErrors === 1 ? '' : 's'} when it ran`
                    : runtimeProblems.length ? `${runtimeProblems.length} warning${runtimeProblems.length === 1 ? '' : 's'} when it ran`
                        : 'ran cleanly';

    return (
        <div className="border-t border-slate-800 bg-slate-950/80 text-xs">
            <div className="flex items-center gap-3 px-4 py-1.5">
                <button
                    onClick={() => setOpen(v => !v)}
                    className="flex items-center gap-3 text-slate-300 hover:text-white"
                    aria-expanded={open}
                    aria-label="Problems"
                >
                    {open ? <ChevronDown size={13} /> : <ChevronUp size={13} />}
                    <span className="font-medium">Problems</span>
                    <span className={`flex items-center gap-1 ${errors ? 'text-rose-400' : 'text-slate-500'}`}>
                        <AlertCircle size={12} /> {errors}
                    </span>
                    <span className={`flex items-center gap-1 ${warnings ? 'text-amber-400' : 'text-slate-500'}`}>
                        <AlertTriangle size={12} /> {warnings}
                    </span>
                    <span className={`flex items-center gap-1 ${runtimeErrors ? 'text-rose-400' : runtimeProblems.length ? 'text-amber-400' : 'text-slate-500'}`}>
                        {runtimeStatus === 'running' ? <Loader2 size={12} className="animate-spin" /> : <Info size={12} />}
                        {runtimeLabel}
                    </span>
                </button>
                {actionable && (
                    <button
                        onClick={fix}
                        disabled={busy}
                        title="Ask the agent to fix everything listed here"
                        className="ml-auto flex items-center gap-1.5 px-2 py-1 rounded-md bg-slate-800 border border-slate-700 text-slate-200 hover:bg-slate-700 hover:text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                    >
                        <Wrench size={12} /> Fix with agent
                    </button>
                )}
            </div>

            {open && (
                <div className="max-h-48 overflow-y-auto px-4 pb-3 space-y-3">
                    <section>
                        <h4 className="text-[11px] uppercase tracking-wider text-slate-500 mb-1">Checks</h4>
                        {findings.length === 0 ? (
                            <p className="text-slate-500">Nothing found.</p>
                        ) : (
                            <ul className="space-y-1">
                                {findings.map((f, i) => (
                                    <li key={`${f.rule}-${f.line}-${i}`} className="flex items-start gap-2">
                                        {f.severity === 'error'
                                            ? <AlertCircle size={12} className="mt-0.5 shrink-0 text-rose-400" />
                                            : <AlertTriangle size={12} className="mt-0.5 shrink-0 text-amber-400" />}
                                        <span className="text-slate-300 break-words">
                                            <span className="text-slate-500">Line {f.line} · {f.rule} · </span>{f.message}
                                        </span>
                                    </li>
                                ))}
                            </ul>
                        )}
                    </section>
                    <section>
                        <h4 className="text-[11px] uppercase tracking-wider text-slate-500 mb-1">Last run in the preview</h4>
                        {runtime.length === 0 ? (
                            <p className="text-slate-500">
                                {runtimeStatus === 'settled' ? 'No requests or errors recorded.' : runtimeLabel}
                            </p>
                        ) : (
                            <ul className="space-y-1">
                                {runtime.map((e, i) => (
                                    <li key={i} className="flex items-start gap-2">
                                        {e.level === 'error'
                                            ? <AlertCircle size={12} className="mt-0.5 shrink-0 text-rose-400" />
                                            : e.level === 'warn'
                                                ? <AlertTriangle size={12} className="mt-0.5 shrink-0 text-amber-400" />
                                                : <Info size={12} className="mt-0.5 shrink-0 text-slate-500" />}
                                        <span className="text-slate-300 break-words">{formatRuntimeEntry(e)}</span>
                                    </li>
                                ))}
                            </ul>
                        )}
                    </section>
                </div>
            )}
        </div>
    );
};
