/**
 * What a role-mapping name resolves to in Databricks, as reported by
 * `GET /api/roles/principals/check` (`server/services/principals.py`).
 */

export type PrincipalStatus = 'group' | 'user' | 'mismatch' | 'unknown' | 'unverified' | 'checking' | 'empty';

export interface PrincipalVerdict {
    status: PrincipalStatus;
    name: string;
    detail?: string;
    suggestion?: string;
}

/**
 * Whether a form may save `value` given the last verdict. Mirrors
 * `principals.is_blocking` on the server — and requires the verdict to be *about*
 * `value`: checks are debounced, so for a moment after each keystroke the latest
 * verdict describes the previous text, and a stale "group" must not enable Save
 * for a name that hasn't been checked.
 */
export const principalAllowsSave = (v: PrincipalVerdict | null, value: string): boolean =>
    !!v && v.name === value.trim() && (v.status === 'group' || v.status === 'user' || v.status === 'unverified');
