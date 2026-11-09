import React from 'react';
import { Globe, Lock, Users } from 'lucide-react';
import clsx from 'clsx';
import type { AccessSummary } from '../../sharing';

const META: Record<AccessSummary, { Icon: typeof Lock; title: string }> = {
    private: { Icon: Lock, title: 'Only you and managers' },
    shared: { Icon: Users, title: 'Shared' },
    everyone: { Icon: Globe, title: 'Everyone in this app' },
};

export interface AccessIconProps {
    summary: AccessSummary;
    /** Applied to the icon; colour it with `text-*`. */
    className?: string;
    size?: number;
}

export const AccessIcon: React.FC<AccessIconProps> = ({ summary, className, size = 14 }) => {
    const { Icon, title } = META[summary] || META.private;
    return (
        <span role="img" aria-label={title} title={title} className="inline-flex shrink-0">
            <Icon size={size} aria-hidden="true" className={clsx('shrink-0', className)} />
        </span>
    );
};

export default AccessIcon;
