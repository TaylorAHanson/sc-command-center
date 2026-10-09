/**
 * Deterministic checks on widget code, run in the browser after every compile.
 *
 * The widget contract (`server/routes/agent_instructions.md`) is enforced by
 * asking a model to follow it and then asking a second model call — the review
 * — whether it did. Some of the rules are mechanical enough to check in a
 * millisecond instead: an import the sandbox can't satisfy, a CDN `useScript`
 * refuses, a write that bypasses the audit trail. Each of those otherwise costs
 * a render, a confused user and a turn to find.
 *
 * Errors are things that will not work or break a platform rule; the studio
 * auto-fixes them in code the agent produced. Warnings are patterns that are
 * usually wrong but can be deliberate, so they are shown and handed to the
 * agent as context, never acted on alone. Keep every rule in step with the
 * contract it cites — a lint that disagrees with the instructions sends the
 * agent in circles.
 */
import { isAllowedScriptUrl } from './hooks/useScript';
import { FONTS } from './fonts';
import { withBrandColors } from './brand';

export type LintSeverity = 'error' | 'warning';

export type LintFinding = {
    rule: string;
    severity: LintSeverity;
    /** 1-based. */
    line: number;
    message: string;
};

export type LintOptions = {
    dataSourceType?: string;
    /** A page draws its own background; a card sits on white. */
    layoutKind?: 'card' | 'page';
    /** Whether `require(name)` would resolve in the preview sandbox. Injected for testing. */
    moduleAvailable?: (name: string) => boolean;
    /** Every class the app's stylesheet defines; null skips the check. Injected for testing. */
    compiledClasses?: Set<string> | null;
};

const MAX_FINDINGS = 30;

// Mirrors the `require` shim in WidgetStudio's compile step and widgetRegistry:
// React, ReactDOM, or a global of that name (Highcharts preloaded by index.html).
const sandboxHasModule = (name: string): boolean => {
    if (name === 'react' || name === 'react-dom') return true;
    const w = window as unknown as Record<string, unknown>;
    return Boolean(w[name] || w[name.charAt(0).toUpperCase() + name.slice(1)]);
};

const lineAt = (code: string, index: number) => code.slice(0, index).split('\n').length;

// String literals, each with where it starts. Template literals are included
// whole, `${…}` and all, which is fine for class names.
const STRING_RE = /'(?:\\.|[^'\\\n])*'|"(?:\\.|[^"\\\n])*"|`(?:\\.|[^`\\])*`/g;

const TAILWIND_COLORS = 'slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose';
const LIGHT_TEXT_RE = new RegExp(`(?:^|\\s)((?:[a-z-]+:)*(?:text-white|text-(?:${TAILWIND_COLORS})-(?:50|100|200|300|400)|placeholder-(?:${TAILWIND_COLORS})-(?:50|100|200|300|400)))(?=\\s|$)`);
const DARK_BG_RE = new RegExp(`(?:^|\\s)(?:[a-z-]+:)*bg-(?:(?:${TAILWIND_COLORS})-(?:600|700|800|900|950)|black|brand-navy|brand-blue|gradient-to-[a-z]+)(?=\\s|$)`);
const ARBITRARY_RE = /(?:^|\s)((?:[a-z-]+:)*-?[a-z][a-z0-9]*(?:-[a-z0-9]+)*-\[[^\]\s]+\])(?=\s|$)/;
// Enough of a class list to be worth reading as one: two or more tokens, or a single utility.
const CLASSY_RE = /^[\s\w:/.[\]#%-]+$/;

// An inline background as written in a style object: `background: '…'`, `backgroundColor: "…"`.
const INLINE_BG_RE = /\bbackground(?:Color|Image)?\s*:\s*(['"`])([^'"`]*)\1/g;
const COLOUR_RE = /#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?\b|rgba?\(\s*\d+[\s,]+\d+[\s,]+\d+[^)]*\)/g;
const NAMED_DARK = /\b(?:black|navy|midnightblue|darkslategray|darkslategrey)\b/i;

/** Relative luminance, 0 (black) to 1 (white), of `#rgb`, `#rrggbb` or `rgb()`. */
const luminance = (colour: string): number => {
    let rgb: number[];
    if (colour.startsWith('#')) {
        const hex = colour.length === 4 ? colour.slice(1).split('').map(c => c + c).join('') : colour.slice(1, 7);
        rgb = [0, 2, 4].map(i => parseInt(hex.slice(i, i + 2), 16));
    } else {
        rgb = (colour.match(/\d+/g) || []).slice(0, 3).map(Number);
    }
    const [r, g, b] = rgb.map(v => {
        const c = v / 255;
        return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};

/** Whether an inline background reads as dark; null if it names no colour we can judge. */
const darkBackground = (value: string): boolean | null => {
    const colours = value.match(COLOUR_RE);
    if (!colours) return NAMED_DARK.test(value) ? true : null;
    const mean = colours.reduce((sum, c) => sum + luminance(c), 0) / colours.length;
    // White text on a background this dark passes WCAG AA for large text.
    return mean < 0.2;
};

/** The JSX tag a class string sits in, braces and all; '' if it isn't in one. */
const enclosingTag = (code: string, index: number): string => {
    const start = code.lastIndexOf('<', index);
    if (start < 0 || !/[A-Za-z]/.test(code[start + 1] || '')) return '';
    let depth = 0;
    for (let i = start; i < code.length && i < start + 4000; i++) {
        const ch = code[i];
        if (ch === '{') depth++;
        else if (ch === '}') depth--;
        else if (ch === '>' && depth === 0) return code.slice(start, i + 1);
    }
    return '';
};

const BG_CLASS_RE = new RegExp(`(?:^|[\\s"'\`{])(?:(?:sm|md|lg|xl):)?bg-(white|black|(?:${TAILWIND_COLORS})-\\d+|brand-[a-z]+|gradient-to-[a-z]+)(?:\\/(\\d+))?(?=[\\s"'\`}]|$)`);

/**
 * Whether whatever is drawn behind `index` is dark: the nearest enclosing element
 * that sets a background decides, from an inline `style` or a `bg-*` class; null
 * when nothing encloses it. A translucent fill (`bg-white/10`) is see-through, so
 * the walk carries on past it. JSX is read as tags only, so a `<` in a generic or
 * a comparison can miscount; this feeds a warning, not an error.
 */
const backgroundBehind = (code: string, index: number): boolean | null => {
    let pending = 0;
    let seen = 0;
    for (let pos = code.lastIndexOf('<', index); pos >= 0 && seen < 12 && index - pos < 20000; pos = code.lastIndexOf('<', pos - 1)) {
        const next = code[pos + 1] || '';
        if (next === '/') { pending++; continue; }
        if (next === '>') { if (pending) pending--; continue; }
        if (!/[A-Za-z]/.test(next)) continue;
        const tag = enclosingTag(code, pos);
        if (!tag || tag.endsWith('/>')) continue;
        if (pending) { pending--; continue; }
        seen++;
        const inline = [...tag.matchAll(INLINE_BG_RE)].map(m => darkBackground(m[2])).find(v => v !== null);
        if (inline !== undefined) return inline;
        const fill = BG_CLASS_RE.exec(tag);
        if (fill && !(fill[2] && Number(fill[2]) < 50)) return DARK_BG_RE.test(`bg-${fill[1]}`);
    }
    return null;
};

// Tokens that are Tailwind utilities, which exist only if the build compiled
// them. Anything else may be the widget's own name for an element.
const UTILITY_RE = /^(?:[a-z-]+:)*-?(?:(?:p|m)[xytrbl]?-(?:[\d.]+|px|auto)$|(?:gap(?:-[xy])?|space-[xy]|inset|top|left|right|bottom|translate-[xy])-(?:[\d.]+|px|full|\d\/\d)$|(?:text|bg|from|via|to|grid-cols|col-span|row-span|rounded(?:-[trbl]{1,2})?|shadow|w|h|min-h|min-w|max-h|max-w|leading|tracking|font|border(?:-[xytrbl])?|ring|opacity|z|scale|rotate|blur|backdrop-blur|duration|aspect)(?:-|$))/;

let stylesheetClasses: { sheets: number; classes: Set<string> } | null = null;

/** The class names the page's stylesheets define, unescaped; null where there are none to read. */
const pageStylesheetClasses = (): Set<string> | null => {
    if (typeof document === 'undefined') return null;
    const sheets = document.styleSheets.length;
    if (stylesheetClasses && stylesheetClasses.sheets === sheets) {
        return stylesheetClasses.classes.size > 500 ? stylesheetClasses.classes : null;
    }
    const classes = new Set<string>();
    const walk = (rules: CSSRuleList) => {
        for (const rule of Array.from(rules)) {
            if (rule instanceof CSSStyleRule) {
                for (const m of rule.selectorText.matchAll(/\.((?:\\.|[\w-])+)/g)) classes.add(m[1].replace(/\\(.)/g, '$1'));
            } else if ('cssRules' in rule) {
                walk((rule as CSSGroupingRule).cssRules);
            }
        }
    };
    for (const sheet of Array.from(document.styleSheets)) {
        try { walk(sheet.cssRules); } catch { /* another origin's sheet */ }
    }
    // Too few to be the app's stylesheet: still loading, or not this app.
    stylesheetClasses = { sheets, classes };
    return classes.size > 500 ? classes : null;
};

const GENERIC_FAMILIES = new Set(['serif', 'sans-serif', 'monospace', 'cursive', 'system-ui', 'ui-sans-serif', 'ui-serif', 'ui-monospace', 'inherit', 'initial', 'unset']);
const BUNDLED_FAMILIES = new Set(FONTS.map(f => f.family.toLowerCase()));
const FONT_FAMILY_RE = /\bfontFamily\s*:\s*(['"`])((?:(?!\1).)*)\1/g;

/** Everything `lintWidget` finds, errors first, then by line. */
export function lintWidget(code: string, options: LintOptions = {}): LintFinding[] {
    const findings: LintFinding[] = [];
    if (!code || !code.trim()) return findings;
    const has = options.moduleAvailable ?? sandboxHasModule;
    const add = (rule: string, severity: LintSeverity, index: number, message: string) => {
        findings.push({ rule, severity, line: lineAt(code, Math.max(0, index)), message });
    };

    // --- errors: will not work, or break a platform rule -----------------------

    if (!/\bexport\s+default\b/.test(code) && !/\bmodule\.exports\s*=/.test(code)
        && !/\bexport\s*\{[^}]*\bas\s+default\b/.test(code)) {
        add('no-default-export', 'error', 0,
            'No `export default`. The studio renders the default export, so without one nothing renders.');
    }

    for (const match of code.matchAll(/^\s*import\s+(type\s+)?(?:[\s\S]*?\s+from\s+)?['"]([^'"]+)['"]/gm)) {
        const [, typeOnly, name] = match;
        if (typeOnly || name === '../widgetRegistry' || has(name)) continue;
        add('unavailable-import', 'error', match.index ?? 0,
            name === 'lucide-react'
                ? '`lucide-react` is not available to widgets. Use an inline <svg> or a text symbol instead.'
                : `\`${name}\` is not available in the widget sandbox. Load a library with \`useScript(url, globalName)\` instead of importing it.`);
    }

    const redefined = /\b(?:function\s+useScript\b|(?:const|let|var)\s+useScript\s*=)/.exec(code);
    if (redefined) {
        add('redefined-useScript', 'error', redefined.index,
            '`useScript` is provided by the runtime. Defining your own replaces the one that enforces the CDN allowlist and load order.');
    }

    for (const match of code.matchAll(/\buseScript\(\s*(['"`])([^'"`$]+)\1/g)) {
        const url = match[2];
        if (!isAllowedScriptUrl(url)) {
            add('script-host', 'error', match.index ?? 0,
                `useScript will refuse \`${url}\`: scripts must be https from cdn.jsdelivr.net, code.highcharts.com, unpkg.com or cdnjs.cloudflare.com.`);
        }
    }

    const topLevelRender = /\b(?:ReactDOM\.render|ReactDOM\.hydrate|createRoot|hydrateRoot)\s*\(/.exec(code);
    if (topLevelRender) {
        add('top-level-render', 'error', topLevelRender.index,
            'Widgets are mounted by the dashboard. Remove the ReactDOM render call and export the component instead.');
    }

    const write = code.indexOf('/api/sql/execute-write');
    if (write >= 0 && !/\bexecuteAction\b/.test(code)) {
        add('write-without-action', 'error', write,
            'This widget writes data without `props.executeAction`, so the change bypasses the audit trail. Run the write inside an executeAction callback.');
    }

    // --- warnings: usually wrong, sometimes deliberate -------------------------

    if (write >= 0 && !/\brequestId\b/.test(code)) {
        add('write-without-request-id', 'warning', write,
            'The write does not tag its statement with `ctx.requestId`, so the audit record cannot be joined to Databricks query history.');
    }

    const read = code.indexOf('/api/sql/execute-raw');
    if (read >= 0 && !/\.ok\b|\.status\b/.test(code)) {
        add('unchecked-sql-response', 'warning', read,
            'The SQL response is read without checking `res.ok`, so a refused query shows up as "no data" instead of its reason.');
    }

    // A number sized to the data on the day the widget was built: correct then,
    // silently short once the table grows past it. A pager's page size is fine.
    if (read >= 0 && !/\bOFFSET\b/i.test(code)) {
        for (const match of code.matchAll(/\bmax_rows['"]?\s*:\s*(\d[\d_]*)/g)) {
            const rows = Number(match[1].replace(/_/g, ''));
            if (rows < 1000) continue;
            add('fixed-row-cap', 'warning', match.index ?? 0,
                `\`max_rows: ${match[1]}\` keeps only the first ${rows.toLocaleString()} rows, so anything filtered, totalled or charted from them goes wrong once the data passes that. Send \`all_rows: true\` to get every row.`);
            break;
        }
    }

    if (options.dataSourceType && options.dataSourceType !== 'none' && !/\bdataSource\b/.test(code)) {
        add('hardcoded-data-source', 'warning', 0,
            'A data source is configured but the code never reads `props.data.dataSource`, so the configured source is ignored.');
    }

    for (const match of code.matchAll(FONT_FAMILY_RE)) {
        const first = match[2].split(',')[0].trim().replace(/^['"]|['"]$/g, '');
        if (!first || first.startsWith('$') || GENERIC_FAMILIES.has(first.toLowerCase()) || BUNDLED_FAMILIES.has(first.toLowerCase())) continue;
        add('unknown-font', 'warning', match.index ?? 0,
            `\`${first}\` isn't bundled with the app, so it shows in the system font instead. Use one of ${FONTS.map(f => `'${f.family}'`).join(', ')}.`);
    }

    // A page that opens on a dark background is read against that, not white.
    const firstBackground = code.match(new RegExp(INLINE_BG_RE.source));
    const darkPage = options.layoutKind === 'page' && firstBackground !== null && darkBackground(firstBackground[2]) === true;

    const compiled = options.compiledClasses === undefined ? pageStylesheetClasses() : options.compiledClasses;
    const missing = new Set<string>();
    let arbitrary = 0;
    let light = 0;
    for (const match of code.matchAll(STRING_RE)) {
        const text = match[0].slice(1, -1);
        if (!text.trim() || !CLASSY_RE.test(text)) continue;
        const index = match.index ?? 0;
        // Compiled as the runtime compiles them, old brand names mapped to `brand-*`.
        const tokens = withBrandColors(text).split(/\s+/).filter(Boolean);
        // A string holding no real class is a label or an option value, not a class list.
        if (compiled && tokens.some(t => compiled.has(t))) {
            for (const token of tokens) {
                if (!token.includes('-') || token.includes('[') || missing.has(token) || compiled.has(token) || !UTILITY_RE.test(token)) continue;
                missing.add(token);
                if (missing.size <= 5) {
                    add('missing-class', 'warning', index,
                        `\`${token}\` isn't in the app's stylesheet, so it has no effect. Use a nearby standard class that is, or an inline style.`);
                }
            }
        }
        const odd = ARBITRARY_RE.exec(text);
        if (odd && arbitrary < 5) {
            arbitrary += 1;
            add('arbitrary-tailwind', 'warning', index,
                `\`${odd[1]}\` is an arbitrary Tailwind value, which the runtime does not generate. Use a standard utility or an inline style.`);
        }
        const faint = LIGHT_TEXT_RE.exec(text);
        const behind = faint && !DARK_BG_RE.test(text) ? backgroundBehind(code, index) : null;
        if (faint && !DARK_BG_RE.test(text) && light < 5 && behind !== true && !(behind === null && darkPage)) {
            light += 1;
            add('light-text', 'warning', index, options.layoutKind === 'page'
                ? `\`${faint[1]}\` is too light to read on a light background. Use a 600 shade or darker, or give this element a dark background.`
                : `\`${faint[1]}\` is too light to read on the widget's white background. Use a 600 shade or darker, or give this element a dark background.`);
        }
    }

    const order = { error: 0, warning: 1 };
    return findings
        .sort((a, b) => order[a.severity] - order[b.severity] || a.line - b.line)
        .slice(0, MAX_FINDINGS);
}

/** One finding as the agent and the Problems panel read it. */
export const formatLintFinding = (finding: LintFinding): string =>
    `line ${finding.line}: ${finding.severity} [${finding.rule}] ${finding.message}`;
