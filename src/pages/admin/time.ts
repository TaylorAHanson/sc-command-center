// Postgres TIMESTAMP columns arrive without a zone and are UTC; TIMESTAMPTZ ones
// carry an offset. Reading the first kind as local time makes everything look
// hours old, so a bare value gets its `Z` before parsing.
const ZONED = /(Z|[+-]\d{2}:?\d{2})$/i;

export const parseServerTime = (value?: string | null): Date | null => {
    if (!value) return null;
    const d = new Date(ZONED.test(value) ? value : `${value}Z`);
    return Number.isNaN(d.getTime()) ? null : d;
};

export const formatServerTime = (value?: string | null): string => {
    const d = parseServerTime(value);
    return d ? d.toLocaleString() : '—';
};
