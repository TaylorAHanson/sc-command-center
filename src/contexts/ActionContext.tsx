import React, { createContext, useContext } from 'react';

/**
 * What a widget's action callback is handed when the user confirms.
 *
 * `requestId` identifies this approval. A widget that writes should carry it
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

    return (
        <>
            {React.Children.map(children, child => {
                if (React.isValidElement(child)) {
                    return React.cloneElement(child as React.ReactElement<any>, { executeAction });
                }
                return child;
            })}
        </>
    );
};
