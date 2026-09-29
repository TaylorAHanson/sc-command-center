import { getAppBrand } from './api';

/**
 * Widgets saved before the palette was renamed use the deployment's brand name
 * in their colour classes (`text-<brand>-blue`), and they live in the database,
 * not here. Only `brand-*` exists in the compiled stylesheet, so their code is
 * rewritten to it just before compiling. The name comes from `APP_BRAND` on the
 * server, which keeps any customer's name out of this repo.
 *
 * Matching the text rather than a class list covers every variant for free —
 * `hover:bg-<brand>-blue`, `text-<brand>-navy/70` — and the stored code is never
 * changed, so turning the setting off is a redeploy, not a migration.
 */
let legacyColor: RegExp | null = null;
let ready: Promise<void> | null = null;

export const brandReady = (): Promise<void> => {
    ready ??= getAppBrand().then((brand) => {
        legacyColor = brand && brand !== 'brand'
            ? new RegExp(`(?<=-)${brand}-(navy|blue|light)(?![\\w-])`, 'g')
            : null;
    });
    return ready;
};

export const withBrandColors = (code: string): string =>
    legacyColor ? code.replace(legacyColor, 'brand-$1') : code;
