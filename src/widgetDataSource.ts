/**
 * Reading a tested data source's response into what the agent is shown: a
 * schema, and a few real rows.
 *
 * Plain `api` sources are tested here in the browser rather than on the server,
 * because the widget will call them from the browser — a test that passes on the
 * server says nothing about CORS or the user's own session — and because a
 * server that fetches any URL it is handed is a way into its network.
 */

const SAMPLE_ROWS = 5;
const SAMPLE_CELL_CHARS = 200;

type Row = Record<string, unknown>;

const isRow = (value: unknown): value is Row =>
    !!value && typeof value === 'object' && !Array.isArray(value);

const typeName = (value: unknown): string => {
    if (value === null || value === undefined) return 'string';
    if (Array.isArray(value)) return 'array';
    if (typeof value === 'number') return Number.isInteger(value) ? 'int' : 'float';
    return typeof value === 'object' ? 'object' : typeof value;
};

/**
 * The records in a response: the array itself, or the first array of objects
 * one level down (`{"jobs": [...]}`), or the object as a single record.
 */
const records = (data: unknown): Row[] => {
    if (Array.isArray(data)) return data.map(item => (isRow(item) ? item : { value: item }));
    if (isRow(data)) {
        const nested = Object.values(data).find(v => Array.isArray(v) && v.length > 0 && isRow(v[0]));
        return nested ? (nested as unknown[]).filter(isRow) : [data];
    }
    return [{ value: data }];
};

/** Field name to a simple type, from the first record. Same shape the server returns. */
export const schemaFromJson = (data: unknown): Record<string, string> => {
    const first = records(data)[0] ?? {};
    return Object.fromEntries(Object.entries(first).map(([key, value]) => [key, typeName(value)]));
};

/** A few records, long strings cut, ready to be sent with every agent turn. */
export const sampleRows = (data: unknown): Row[] =>
    records(data).slice(0, SAMPLE_ROWS).map(row => Object.fromEntries(
        Object.entries(row).slice(0, 40).map(([key, value]) => [
            key,
            typeof value === 'string' && value.length > SAMPLE_CELL_CHARS ? `${value.slice(0, SAMPLE_CELL_CHARS - 1)}…` : value,
        ]),
    ));
