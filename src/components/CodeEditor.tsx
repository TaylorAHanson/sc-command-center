import React, { useLayoutEffect, useMemo, useRef } from 'react';
import clsx from 'clsx';
import hljs from 'highlight.js/lib/core';
import javascript from 'highlight.js/lib/languages/javascript';
import json from 'highlight.js/lib/languages/json';
import python from 'highlight.js/lib/languages/python';
import sql from 'highlight.js/lib/languages/sql';
import typescript from 'highlight.js/lib/languages/typescript';
// Token colors only. The theme also styles `.hljs` itself (its own background),
// which we deliberately don't apply — each editor keeps the surrounding panel's
// background instead.
import 'highlight.js/styles/atom-one-dark.css';

// Registered explicitly rather than importing all of highlight.js: the four
// languages actually authored in this app cost a few KB, the full set costs
// hundreds.
hljs.registerLanguage('javascript', javascript);
hljs.registerLanguage('typescript', typescript);
hljs.registerLanguage('python', python);
hljs.registerLanguage('sql', sql);
hljs.registerLanguage('json', json);

export type CodeLanguage = 'tsx' | 'typescript' | 'javascript' | 'python' | 'sql' | 'json';

const HLJS_NAME: Record<CodeLanguage, string> = {
  // highlight.js has no separate TSX grammar; its TypeScript grammar handles
  // embedded JSX, which is what widget code is.
  tsx: 'typescript',
  typescript: 'typescript',
  javascript: 'javascript',
  python: 'python',
  sql: 'sql',
  json: 'json',
};

const INDENT = '  ';

interface CodeEditorProps {
  value: string;
  /** Omit to render read-only (no textarea is mounted at all). */
  onChange?: (next: string) => void;
  language?: CodeLanguage;
  showLineNumbers?: boolean;
  placeholder?: string;
  /**
   * Applied to the scroll container: pass sizing (`absolute inset-0`, `flex-1`,
   * `h-24`) *and* a background. The background is not defaulted because the
   * sticky gutter inherits it to mask code scrolling underneath, so a
   * transparent container would let text slide behind the line numbers.
   */
  className?: string;
  ariaLabel?: string;
}

/**
 * A code editor: highlighted text with a line-number gutter, editable.
 *
 * The editing surface is still a plain `<textarea>`, laid transparently over a
 * highlighted `<pre>` that renders the same string in the same metrics. That
 * keeps the value fully controlled (identical semantics to the textareas this
 * replaced) and avoids taking on a full editor framework for what is mostly a
 * viewer. Two consequences to preserve when editing this:
 *
 *   * The `<pre>` sizes the box and the textarea is stretched over it, so the
 *     one scroll container scrolls both together — no scroll-sync code, and the
 *     gutter cannot drift out of alignment with the code.
 *   * Nothing may wrap. Wrapped lines would break the one-number-per-line gutter,
 *     so long lines scroll horizontally instead (the gutter sticks to the left).
 */
export const CodeEditor: React.FC<CodeEditorProps> = ({
  value,
  onChange,
  language = 'tsx',
  showLineNumbers = true,
  placeholder,
  className,
  ariaLabel,
}) => {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const pendingCaret = useRef<number | null>(null);

  const highlighted = useMemo(() => {
    // A `<pre>` swallows one trailing newline; the textarea does not. Without
    // this, the gutter loses a row the moment the file ends in a blank line.
    const source = value.endsWith('\n') ? `${value}\n` : value;
    try {
      return hljs.highlight(source, {
        language: HLJS_NAME[language],
        ignoreIllegals: true,
      }).value;
    } catch {
      // Half-typed code is routinely un-parseable; show it plain rather than
      // blowing up the editor.
      return source.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c] as string));
    }
  }, [value, language]);

  const lineCount = useMemo(() => value.split('\n').length, [value]);

  // Restore the caret after an edit we performed ourselves (Tab, auto-indent).
  // React re-renders from `value`, which would otherwise drop the caret to the end.
  useLayoutEffect(() => {
    if (pendingCaret.current === null || !textareaRef.current) return;
    const pos = pendingCaret.current;
    pendingCaret.current = null;
    textareaRef.current.setSelectionRange(pos, pos);
  }, [value]);

  const replaceValue = (next: string, caret: number) => {
    pendingCaret.current = caret;
    onChange?.(next);
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (!onChange) return;
    const el = event.currentTarget;
    const start = el.selectionStart;
    const end = el.selectionEnd;

    if (event.key === 'Tab') {
      // Browsers move focus out of the textarea on Tab, which is the wrong
      // behavior in a code box.
      event.preventDefault();
      const lineStart = value.lastIndexOf('\n', start - 1) + 1;
      if (event.shiftKey) {
        const indented = value.slice(lineStart).match(/^ {1,2}/);
        if (!indented) return;
        const removed = indented[0].length;
        replaceValue(
          value.slice(0, lineStart) + value.slice(lineStart + removed),
          Math.max(lineStart, start - removed),
        );
        return;
      }
      replaceValue(value.slice(0, start) + INDENT + value.slice(end), start + INDENT.length);
      return;
    }

    if (event.key === 'Enter' && start === end) {
      // Carry the current line's indentation onto the new line.
      const lineStart = value.lastIndexOf('\n', start - 1) + 1;
      const indent = (value.slice(lineStart, start).match(/^[ \t]*/) || [''])[0];
      if (!indent) return;
      event.preventDefault();
      replaceValue(
        `${value.slice(0, start)}\n${indent}${value.slice(end)}`,
        start + 1 + indent.length,
      );
    }
  };

  return (
    <div className={clsx('overflow-auto font-mono text-[13px] leading-5', className)}>
      <div className="flex min-h-full w-max min-w-full bg-inherit">
        {/* min-w keeps the code from shifting sideways as the line count crosses
            9, 99, 999 while someone is typing. */}
        {showLineNumbers && (
          <div
            aria-hidden
            className="sticky left-0 z-10 min-w-[3rem] select-none border-r border-slate-800 bg-inherit py-3 pl-3 pr-2 text-right tabular-nums text-slate-600"
          >
            {Array.from({ length: lineCount }, (_, i) => (
              <div key={i + 1}>{i + 1}</div>
            ))}
          </div>
        )}
        <div className="relative min-h-full flex-1">
          <pre aria-hidden className="m-0 whitespace-pre px-3 py-3 text-slate-300">
            <code dangerouslySetInnerHTML={{ __html: highlighted }} />
          </pre>
          {onChange && (
            <textarea
              ref={textareaRef}
              value={value}
              onChange={(e) => onChange(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={placeholder}
              aria-label={ariaLabel}
              spellCheck={false}
              autoComplete="off"
              autoCapitalize="off"
              wrap="off"
              className="absolute inset-0 h-full w-full resize-none overflow-hidden whitespace-pre border-none bg-transparent px-3 py-3 font-mono text-[13px] leading-5 text-transparent caret-slate-100 placeholder-slate-500 outline-none focus:ring-0"
            />
          )}
        </div>
      </div>
    </div>
  );
};
