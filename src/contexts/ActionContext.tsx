import React, { createContext, useContext } from 'react';

type RegisterActionFn = (actionName: string, callback: () => void) => void;

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
