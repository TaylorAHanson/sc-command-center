import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
// Authored at the repo root and bundled at build time, so a deployment's notes
// always match the code that deployment is running.
import releaseNotesMarkdown from '../../RELEASE_NOTES.md?raw';

// react-markdown has no raw-HTML plugin here, so it escapes an HTML comment into
// visible text instead of dropping it. The file opens with one holding the
// authoring conventions, for whoever edits it next — strip comments so that
// guidance stays out of the rendered page.
const RELEASE_NOTES = releaseNotesMarkdown.replace(/<!--[\s\S]*?-->/g, '').trimStart();

export const ReleaseNotesPage: React.FC = () => (
  <div className="h-full overflow-y-auto bg-white">
    <div className="max-w-3xl mx-auto p-8">
      <div className="prose prose-slate max-w-none prose-headings:font-semibold prose-h1:text-2xl prose-h2:text-xl prose-h2:mt-10 prose-h2:pb-2 prose-h2:border-b prose-h2:border-gray-200 prose-h3:text-base prose-h3:text-gray-500 prose-h3:uppercase prose-h3:tracking-wide prose-h3:mb-2 prose-li:my-1">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{RELEASE_NOTES}</ReactMarkdown>
      </div>
    </div>
  </div>
);
