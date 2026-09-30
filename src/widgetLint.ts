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
    /** Whether `require(name)` would resolve in the preview sandbox. Injected for testing. */
    moduleAvailable?: (name: string) => boolean;
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

/** Everything `lintWidget` finds, errors first, then by line. */
export function lintWidget(code: string, options: LintOptions = {}): LintFinding[] {
    const findings: LintFinding[] = [];
    if (!code || !code.trim()) return findings;
    const has = options.moduleAvailable ?? sandboxHasModule;
    const add = (rule: string, severity: LintSeverity, index: number, message: string) => {
        findings.push({ rule, severity, line: lineAt(code, Math.max(0, index)), message });
    };

    // --- errors: will not work, or break a platform rule -----------------------

    if (!/\bexport\s+default\b/.test(code) && !/\bmodule\.exports\s*=/.test(code)) {
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

    if (options.dataSourceType && options.dataSourceType !== 'none' && !/\bdataSource\b/.test(code)) {
        add('hardcoded-data-source', 'warning', 0,
            'A data source is configured but the code never reads `props.data.dataSource`, so the configured source is ignored.');
    }

    let arbitrary = 0;
    let light = 0;
    for (const match of code.matchAll(STRING_RE)) {
        const text = match[0].slice(1, -1);
        if (!text.trim() || !CLASSY_RE.test(text)) continue;
        const index = match.index ?? 0;
        const odd = ARBITRARY_RE.exec(text);
        if (odd && arbitrary < 5) {
            arbitrary += 1;
            add('arbitrary-tailwind', 'warning', index,
                `\`${odd[1]}\` is an arbitrary Tailwind value, which the runtime does not generate. Use a standard utility or an inline style.`);
        }
        const faint = LIGHT_TEXT_RE.exec(text);
        if (faint && !DARK_BG_RE.test(text) && light < 5) {
            light += 1;
            add('light-text', 'warning', index,
                `\`${faint[1]}\` is too light to read on the widget's white background. Use a 600 shade or darker, or give this element a dark background.`);
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
