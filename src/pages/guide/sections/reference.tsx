/* eslint-disable react-refresh/only-export-components -- a section exports its data (`section`) beside its body */
import { Keyboard } from 'lucide-react';
import type { GuideSection } from '../types';
import { Callout, Ext, GuideLink, H2, Kbd, Lead, P, Table, UI } from '../kit';

const Body = () => (
  <>
    <Lead>
      Every keyboard shortcut in the app, and a short definition of each word it uses, with a link to where the word is
      explained.
    </Lead>

    <H2 id="shortcuts">Keyboard shortcuts</H2>
    <Table
      head={['Keys', 'Where', 'What happens']}
      rows={[
        [<Kbd>W</Kbd>, 'Anywhere in the Command Center, outside a text box', <>Opens the <UI>Widget Library</UI>. It does not work on a full-screen page such as this guide.</>],
        [<Kbd>Esc</Kbd>, 'Widget Library', 'Closes it.'],
        [<Kbd>Esc</Kbd>, 'A widget in full screen', 'Returns to the view.'],
        [<Kbd>Esc</Kbd>, 'A view\u2019s ⋯ menu, the Add a tab menu, a confirmation dialog, the past conversations list', 'Closes it. In a confirmation dialog this is the same as Cancel.'],
        [<Kbd>Esc</Kbd>, 'The Getting Started panel', 'Closes it, when there is a view behind it to go back to.'],
        [<Kbd>Esc</Kbd>, 'An enlarged picture in this guide, a field\u2019s ? help bubble', 'Closes it.'],
        [<Kbd>F2</Kbd>, 'A selected tab', 'Renames it. Only if you may change the view.'],
        [<>Arrow keys, <Kbd>Home</Kbd>, <Kbd>End</Kbd></>, 'In the tab bar', 'Move between tabs. Right and down go forward, left and up go back, and the ends wrap around.'],
        [<><Kbd>Enter</Kbd> or <Kbd>Space</Kbd></>, 'A focused tab', 'Opens it.'],
        [<><Kbd>Enter</Kbd> / <Kbd>Esc</Kbd></>, 'Naming a tab, a view in the sidebar, or a past conversation', 'Enter saves the name; Esc cancels.'],
        [<Kbd>Enter</Kbd>, 'The assistant message box', 'Sends the message. It never stops an answer that is being written.'],
        [<><Kbd>Shift</Kbd>+<Kbd>Enter</Kbd></>, 'The assistant message box', 'Starts a new line.'],
        [<><Kbd>Ctrl</Kbd>+<Kbd>V</Kbd> / <Kbd>Cmd</Kbd>+<Kbd>V</Kbd></>, 'The assistant message box', 'Attaches an image on the clipboard as a file. Copied text is pasted as text.'],
        [<Kbd>Enter</Kbd>, 'The box beside Suggest in View settings → Look', 'Fills in the look from your description, the same as clicking Suggest.'],
        [<><Kbd>Enter</Kbd> / <Kbd>Shift</Kbd>+<Kbd>Enter</Kbd></>, 'The prompt box in Widget Studio and Agent Studio', 'Enter sends and Shift+Enter starts a new line. Enter does nothing while the agent is still working.'],
        [<><Kbd>Tab</Kbd> / <Kbd>Shift</Kbd>+<Kbd>Tab</Kbd></>, 'A code box in Widget Studio or Agent Studio', 'Indents or outdents instead of moving to the next field. Enter keeps the current line\u2019s indentation.'],
        [<><Kbd>Up</Kbd> / <Kbd>Down</Kbd>, <Kbd>Enter</Kbd>, <Kbd>Esc</Kbd></>, 'A model picker (Agent Studio, Admin settings)', 'Move through the list, choose the highlighted model or the text you typed, and close the list.'],
        [<Kbd>/</Kbd>, 'This guide, outside a text box', 'Jumps to the search box.'],
        [<Kbd>Esc</Kbd>, 'The guide search box', 'Clears the search and leaves the box.'],
      ]}
    />
    <Callout kind="note" title="Mouse and keyboard">
      There is no shortcut for Lock, Share, New view or the assistant. Use the buttons. To drag a widget or a tab, hold
      its header or name; the tab bar's arrow keys cover reaching a tab from the keyboard but not reordering. Sidebar
      favorites move with <Kbd>Alt</Kbd>+<Kbd>↑</Kbd> and <Kbd>Alt</Kbd>+<Kbd>↓</Kbd>.
    </Callout>

    <H2 id="glossary">Glossary</H2>
    <P>
      Terms are in the order you meet them. Each row links to the page that explains it.
    </P>
    <Table
      head={['Term', 'Meaning', 'Read more']}
      rows={[
        [<strong>View</strong>, 'A page of widgets that you arrange yourself, on one or more tabs. The sidebar lists the ones you use under Favorites and Recent; My views and Browse views find the rest.', <GuideLink to="views">Views & layouts</GuideLink>],
        [<strong>Tab</strong>, 'One page inside a view. A view can have up to 50.', <GuideLink to="views" anchor="tabs">Tabs</GuideLink>],
        [<strong>Widget</strong>, 'A chart, table, form or tool you place on a view. Widgets are authored in the app, not installed from files.', <GuideLink to="widgets">Using widgets</GuideLink>],
        [<strong>Card</strong>, 'A widget sitting on a tab beside others, in its own frame, movable and resizable. A tab of this kind is Cards on a grid.', <GuideLink to="views" anchor="cards-or-page">Cards or a page</GuideLink>],
        [<strong>Page</strong>, 'A widget built to fill a whole tab, with no card around it. A tab of this kind is Full page. The library marks these PAGE.', <GuideLink to="views" anchor="cards-or-page">Cards or a page</GuideLink>],
        [<strong>Widget Library</strong>, 'The panel where you find widgets and add them to a view. Opens with the sidebar button or W.', <GuideLink to="widgets" anchor="open-the-library">Open the Widget Library</GuideLink>],
        [<strong>Widget Studio</strong>, 'Where you describe a widget and the agent builds it. Anyone can use it.', <GuideLink to="widget-studio">Widget Studio</GuideLink>],
        [<strong>Domain</strong>, 'A label such as Finance or Supply Chain put on views, widgets and agents so people can find them. It does not control access.', <GuideLink to="access" anchor="domains">Categories and domains</GuideLink>],
        [<strong>Share</strong>, 'Give a person, a group or everyone in this app access to a view, widget or agent.', <GuideLink to="sharing" anchor="share">Share something</GuideLink>],
        [<strong>Can use, Can manage</strong>, 'The two access levels. Can use sees the published version; Can manage also edits, publishes and shares.', <GuideLink to="sharing" anchor="levels">Sharing & permissions</GuideLink>],
        [<strong>Owner</strong>, 'Whoever created a view, widget or agent. The owner can manage it.', <GuideLink to="sharing">Sharing & permissions</GuideLink>],
        [<strong>Everyone in this app</strong>, 'Every person who can sign in to this app, as one entry on an access list.', <GuideLink to="sharing" anchor="who">Who you can share with</GuideLink>],
        [<strong>Administrator</strong>, 'Someone who can manage everything in the app and open the Admin Panel.', <GuideLink to="access" anchor="administrators">Administrators & access</GuideLink>],
        [<strong>Favorites</strong>, 'Views you starred, kept at the top of the sidebar in the order you choose.', <GuideLink to="views" anchor="sidebar">Your views in the sidebar</GuideLink>],
        [<strong>View on its own</strong>, 'A view whose link opens just that view, with no sidebar, under its own title and logo. Also called standalone.', <GuideLink to="views" anchor="settings-opening">Opening</GuideLink>],
        [<strong>Lock layout</strong>, 'In a view\u2019s ⋯ menu: stops widgets being moved, resized, added or removed by accident.', <GuideLink to="views" anchor="lock-and-unlock">Lock and unlock</GuideLink>],
        [<strong>Filter</strong>, 'A dropdown above a view\u2019s widgets that sets a variable the widgets can follow.', <GuideLink to="views" anchor="settings-filters">Filters</GuideLink>],
        [<strong>Look</strong>, 'A view\u2019s colors, font, background and card style.', <GuideLink to="views" anchor="settings-look">Look</GuideLink>],
        [<strong>Draft</strong>, 'The working copy of a view, widget or agent. Only people who can manage it see it; saving changes it in place.', <GuideLink to="publishing" anchor="draft-and-published">Drafts & publishing</GuideLink>],
        [<strong>Publish</strong>, 'Turn the draft into the next published version, which everyone with Can use sees.', <GuideLink to="publishing" anchor="publish">Publish</GuideLink>],
        [<strong>Version</strong>, 'Each publish makes a new version. A card can show any published version of a widget.', <GuideLink to="publishing" anchor="history">History</GuideLink>],
        [<strong>Revert</strong>, 'Copy an older published version into the draft, to publish again.', <GuideLink to="publishing" anchor="history">History</GuideLink>],
        [<strong>Discard draft</strong>, 'Throw away unpublished changes and go back to the latest published version.', <GuideLink to="publishing" anchor="history">History</GuideLink>],
        [<strong>Certify</strong>, 'Mark a published widget version as reviewed and ready for wide use. A signal to people, and a requirement for shared views only when an Administrator turns that on.', <GuideLink to="publishing" anchor="certify">Certify a widget</GuideLink>],
        [<strong>Deployment</strong>, 'Which copy of the Command Center you are using, such as a development app or production. Each has its own database.', <GuideLink to="migration">Moving data to another app</GuideLink>],
        [<strong>Agent</strong>, 'The assistant persona you talk to: a saved set of instructions and tools. EDH Agent is the default.', <GuideLink to="assistant" anchor="agents">Choose an agent</GuideLink>],
        [<strong>Pin</strong>, 'Making a view or tab open the assistant with a chosen agent.', <GuideLink to="assistant" anchor="pin-an-agent">Pin an agent</GuideLink>],
        [<strong>Agent Studio</strong>, 'Where you build, save and publish agents. Anyone can use it.', <GuideLink to="agent-studio">Agent Studio</GuideLink>],
        [<strong>Tool</strong>, 'Something an agent can do, such as running SQL, asking a Genie space or calling a function. Tools run as you.', <GuideLink to="agent-studio">Agent Studio</GuideLink>],
        [<strong>Genie space</strong>, <>A Databricks space that answers plain-language data questions over chosen tables. An agent can use one as a tool. <Ext href="https://docs.databricks.com/aws/en/genie/">Databricks docs</Ext></>, <GuideLink to="agent-studio">Agent Studio</GuideLink>],
        [<strong>MCP</strong>, <>Model Context Protocol, a standard way to give an AI agent tools and data. Agent Studio lists the tools your workspace offers through it. <Ext href="https://docs.databricks.com/aws/en/agents/mcp-tools/mcp-services">Databricks docs</Ext></>, <GuideLink to="agent-studio">Agent Studio</GuideLink>],
        [<strong>Unity Catalog</strong>, <>Databricks' access control for data. It decides which tables the assistant and widgets may read for you. <Ext href="https://docs.databricks.com/aws/en/data-governance/unity-catalog/">Databricks docs</Ext></>, <GuideLink to="assistant" anchor="trust">What to trust</GuideLink>],
        [<strong>Archived</strong>, 'Where an archived view waits, to be restored or deleted for good.', <GuideLink to="publishing" anchor="archive">Archive a view</GuideLink>],
      ]}
    />
    <P>
      Something missing? Ask the assistant, or see <GuideLink to="troubleshooting">Troubleshooting</GuideLink>.
    </P>
  </>
);

export const section: GuideSection = {
  id: 'reference',
  group: 'reference',
  title: 'Shortcuts & glossary',
  summary: 'Keyboard shortcuts and the words this app uses.',
  icon: Keyboard,
  keywords: 'keyboard shortcut keys hotkey glossary terms definitions vocabulary esc enter f2',
  Body,
};
