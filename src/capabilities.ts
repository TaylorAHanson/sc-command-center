import { useEffect, useState } from 'react';

/**
 * What this deployment can do (`GET /api/capabilities`). Features whose setup only
 * the customer's admins can provide — email, scheduling, hybrid search — read this
 * to decide whether to offer a button or to say it isn't set up yet.
 *
 * Fetched on first use, not at page load, and shared: everything asking during a
 * page's life gets the same promise. A failed fetch reads as "nothing is set up",
 * which disables optional features rather than offering ones that would fail.
 */

export interface Capability {
    name: string;
    label: string;
    available: boolean;
    /** How it's running when there's more than one way, e.g. search: basic / keyword / hybrid. */
    mode: string | null;
    /** Administrators only. */
    missing?: string[];
    /** Administrators only. */
    next_step?: string;
}

export interface BackgroundJob {
    name: string;
    every_seconds: number;
    last_started_at?: string | null;
    last_finished_at?: string | null;
    last_status?: string | null;
    last_error?: string | null;
    last_duration_ms?: number | null;
    runs?: number;
}

export interface CapabilitiesResponse {
    capabilities: Capability[];
    /** Administrators only. */
    jobs?: BackgroundJob[];
}

const EMPTY: CapabilitiesResponse = { capabilities: [] };

let pending: Promise<CapabilitiesResponse> | null = null;

export const fetchCapabilities = (refresh = false): Promise<CapabilitiesResponse> => {
    if (!pending || refresh) {
        pending = fetch(`/api/capabilities${refresh ? '?refresh=true' : ''}`)
            .then(async res => {
                if (!res.ok) throw new Error(`${res.statusText} (HTTP ${res.status})`);
                const data = await res.json();
                return { capabilities: data?.capabilities ?? [], jobs: data?.jobs };
            })
            .catch(err => {
                console.warn('Could not load capabilities:', err);
                // Ask again next time rather than remembering the failure.
                pending = null;
                return EMPTY;
            });
    }
    return pending;
};

/** The capabilities, or null until they've loaded. Pass a changing `refreshKey` to refetch. */
export const useCapabilities = (refreshKey?: unknown): CapabilitiesResponse | null => {
    const [data, setData] = useState<CapabilitiesResponse | null>(null);
    useEffect(() => {
        let live = true;
        fetchCapabilities(refreshKey !== undefined && refreshKey !== null).then(next => {
            if (live) setData(next);
        });
        return () => { live = false; };
    }, [refreshKey]);
    return data;
};

export const findCapability = (data: CapabilitiesResponse | null, name: string): Capability | undefined =>
    data?.capabilities.find(c => c.name === name);

export const isAvailable = (data: CapabilitiesResponse | null, name: string): boolean =>
    !!findCapability(data, name)?.available;
