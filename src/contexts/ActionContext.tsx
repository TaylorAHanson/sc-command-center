import React, { createContext, useContext } from 'react';
import { appOfChildren, useWidgetEmail } from '../email';
import { useWidgetSchedule } from '../hooks/useWidgetSchedule';
import { SendEmailDialog } from '../components/SendEmailDialog';
import { WidgetScheduleDialog } from '../components/ScheduleDialog';

/**
 * What a widget's action callback is handed once the action is logged.
 *
 * `requestId` identifies this action. A widget that writes should carry it
 * into the statement it runs (the generator contract suggests a SQL comment),
 * because that id is the only thing joining the intent recorded in `action_logs`
 * to the effect recorded in Databricks' own query history.
 */
export interface ActionRunContext {
    requestId: string;
}

type RegisterActionFn = (actionName: string, callback: (ctx: ActionRunContext) => void) => void;

const ActionContext = createContext<RegisterActionFn | undefined>(undefined);

export const ActionProvider = ActionContext.Provider;

export const useActionContext = () => {
    return useContext(ActionContext);
};

export const ExecuteActionPropInjector: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const executeAction = useActionContext();
    // `props.app.sendEmail` and `props.app.schedule` open dialogs whose Send and
    // Save go through this widget's executeAction, so they are logged like any
    // other action.
    const app = appOfChildren(children);
    const email = useWidgetEmail(app, !!executeAction);
    const schedule = useWidgetSchedule(email.app, !!executeAction);

    return (
        <>
            {React.Children.map(children, child => {
                if (React.isValidElement(child)) {
                    const own = app && (child.props as { app?: unknown }).app === app;
                    return React.cloneElement(child as React.ReactElement<any>, own ? { executeAction, app: schedule.app } : { executeAction });
                }
                return child;
            })}
            {email.request && executeAction && (
                <SendEmailDialog request={email.request} executeAction={executeAction} onClose={email.close} />
            )}
            {schedule.request && executeAction && (
                <WidgetScheduleDialog request={schedule.request} executeAction={executeAction} onClose={schedule.close} />
            )}
        </>
    );
};
