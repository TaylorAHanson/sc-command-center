import React, { useState } from 'react';
import { AlertCircle, CheckCircle2, Clock, RefreshCw, Wrench } from 'lucide-react';
import clsx from 'clsx';
import { type BackgroundJob, useCapabilities } from '../../capabilities';

/**
 * Which optional features this deployment is ready for, and what's left to do.
 *
 * Email, scheduling and hybrid search depend on setup only the customer's admins
 * can provide, so each stays off until it's there; this card is where an admin
 * finds out what's missing and the next step. It also shows when each background
 * job last ran, since "the search index looks stale" starts there.
 */

const every = (seconds: number): string => {
    if (seconds % 3600 === 0) return `every ${seconds / 3600} h`;
    if (seconds % 60 === 0) return `every ${seconds / 60} min`;
    return `every ${seconds} s`;
};

const ago = (iso?: string | null): string => {
    if (!iso) return 'not yet';
    const ms = Date.now() - new Date(iso).getTime();
    if (!Number.isFinite(ms)) return 'unknown';
    const minutes = Math.round(ms / 60000);
    if (minutes < 1) return 'just now';
    if (minutes < 60) return `${minutes} min ago`;
    const hours = Math.round(minutes / 60);
    if (hours < 48) return `${hours} h ago`;
    return `${Math.round(hours / 24)} days ago`;
};

const JobRow: React.FC<{ job: BackgroundJob }> = ({ job }) => {
    const failed = job.last_status === 'failed';
    return (
        <li className="flex items-start justify-between gap-3 py-1.5 text-xs">
            <span className="font-mono text-gray-700">{job.name}</span>
            <span className={clsx('text-right', failed ? 'text-red-600' : 'text-gray-500')} title={job.last_error || undefined}>
                {every(job.every_seconds)} · last ran {ago(job.last_finished_at || job.last_started_at)}
                {failed && ' · failed'}
            </span>
        </li>
    );
};

export const SetupCard: React.FC<{ refreshKey?: unknown }> = ({ refreshKey }) => {
    const [manual, setManual] = useState(0);
    const data = useCapabilities(manual || refreshKey || undefined);
    if (!data || (!data.capabilities.length && !data.jobs?.length)) return null;

    return (
        <div className="rounded-lg border border-gray-200 bg-white">
            <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4">
                <div className="flex items-center gap-2">
                    <Wrench size={16} className="text-brand-blue" />
                    <h2 className="text-base font-semibold text-gray-900">Setup</h2>
                </div>
                <button onClick={() => setManual(Date.now())} className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-800">
                    <RefreshCw size={13} /> Check again
                </button>
            </div>
            <div className="space-y-4 px-5 py-5">
                {data.capabilities.map(cap => (
                    <div key={cap.name} className="flex items-start gap-3">
                        {cap.available
                            ? <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-green-600" />
                            : <AlertCircle size={16} className="mt-0.5 shrink-0 text-amber-500" />}
                        <div className="min-w-0 flex-1">
                            <div className="flex items-baseline gap-2">
                                <span className="text-sm font-medium text-gray-900">{cap.label}</span>
                                <span className="text-xs text-gray-500">
                                    {cap.available ? (cap.mode ? `Ready · ${cap.mode}` : 'Ready') : 'Not set up yet'}
                                </span>
                            </div>
                            {!!cap.missing?.length && (
                                <ul className="mt-1 list-disc pl-4 text-xs text-gray-600">
                                    {cap.missing.map(item => <li key={item}>{item}</li>)}
                                </ul>
                            )}
                            {cap.next_step && <p className="mt-1 text-xs text-gray-800">Next: {cap.next_step}</p>}
                        </div>
                    </div>
                ))}
                {!!data.jobs?.length && (
                    <div className={clsx(data.capabilities.length && 'border-t border-gray-100 pt-4')}>
                        <div className="mb-1 flex items-center gap-1.5 text-xs font-medium text-gray-700">
                            <Clock size={12} /> Background jobs
                        </div>
                        <ul className="divide-y divide-gray-50">
                            {data.jobs.map(job => <JobRow key={job.name} job={job} />)}
                        </ul>
                    </div>
                )}
            </div>
        </div>
    );
};
