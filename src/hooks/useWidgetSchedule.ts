import { useCallback, useMemo, useRef, useState } from 'react';
import type { AppApi } from '../appApi';
import type { ExecuteAction } from '../email';
import {
    createSchedule,
    type ConnectionStatus,
    type CreatePayload,
    type Schedule,
    type ScheduleOutcome,
    type ScheduleRequest,
} from '../schedules';

const CANCELLED: ScheduleOutcome = { scheduled: false, status: 'cancelled' };

export type CreateResult =
    | { ok: true; schedule: Schedule; connection: ConnectionStatus | null }
    | { ok: false; error: string };

/**
 * Create through the widget's `executeAction`, so saving a schedule leaves an
 * action log row like any other widget action. When the log can't be written,
 * `executeAction` alerts and never calls back, and nothing is created.
 */
export const logAndCreate = (
    executeAction: ExecuteAction,
    actionName: string,
    payload: CreatePayload,
): Promise<CreateResult> =>
    new Promise(resolve => {
        let ran = false;
        const notLogged = () => {
            if (!ran) resolve({ ok: false, error: 'Not saved: the action log couldn’t record it.' });
        };
        let started: unknown;
        try {
            started = executeAction(actionName, () => {
                ran = true;
                void createSchedule(payload).then(res => resolve(res.ok
                    ? { ok: true, schedule: res.data.schedule, connection: res.data.connection }
                    : { ok: false, error: res.error }));
            });
        } catch (e) {
            resolve({ ok: false, error: e instanceof Error ? e.message : String(e) });
            return;
        }
        if (started && typeof (started as PromiseLike<unknown>).then === 'function') {
            (started as PromiseLike<unknown>).then(notLogged, notLogged);
        } else {
            notLogged();
        }
    });

/**
 * `app` with `schedule` bound to this widget: calling it holds the request for
 * the Schedule dialog and returns a promise the dialog settles on close. A
 * second call while the dialog is open replaces the first, which resolves as
 * cancelled. Without an action log (`canLog` false) `app` comes back unchanged,
 * and its own `schedule` opens nothing.
 */
export const useWidgetSchedule = (app: AppApi | undefined, canLog: boolean) => {
    const [request, setRequest] = useState<ScheduleRequest | null>(null);
    const settle = useRef<((outcome: ScheduleOutcome) => void) | null>(null);

    const open = useCallback((asked: ScheduleRequest) => new Promise<ScheduleOutcome>(resolve => {
        settle.current?.(CANCELLED);
        settle.current = resolve;
        setRequest(asked && typeof asked === 'object' ? { ...asked } : { sql: '' });
    }), []);

    const close = useCallback((outcome: ScheduleOutcome) => {
        settle.current?.(outcome);
        settle.current = null;
        setRequest(null);
    }, []);

    const bound = useMemo(
        () => (app && canLog ? { ...app, schedule: open } : app),
        [app, canLog, open],
    );

    return { app: bound, request, close };
};
