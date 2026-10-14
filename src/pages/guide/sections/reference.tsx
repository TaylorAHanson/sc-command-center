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
        [<Kbd>Esc</Kbd>, 'The Add tab menu, a confirmation dialog, the past conversations list', 'Closes it. In a confirmation dialog this is the same as Cancel.'],
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
      There is no shortcut for Lock, Share, New View or the assistant. Use the buttons. To drag a widget or a tab, hold
      its header or name; the tab bar's arrow keys cover reaching a tab from the keyboard but not reordering.
    </Callout>

    <H2 id="glossary">Glossary</H2>
    <P>
      Terms are in the order you meet them. Each row links to the page that explains it.
    </P>
    <Table
      head={['Term', 'Meaning', 'Read more']}
      rows={[
        [<strong>View</strong>, 'A page of widgets that you arrange yourself, on one or more tabs. What the sidebar calls My Views, Shared Views and Global Views.', <GuideLink to="views">Views & layouts</GuideLink>],
        [<strong>Tab</strong>, 'One page inside a view. A view can have up to 50.', <GuideLink to="views" anchor="tabs">Tabs</GuideLink>],
        [<strong>Widget</strong>, 'A chart, table, form or tool you place on a view. Widgets are authored in the app, not installed from files.', <GuideLink to="widgets">Using widgets</GuideLink>],
        [<strong>Card</strong>, 'A widget sitting on a tab beside others, in its own frame, movable and resizable. A tab of this kind is Cards on a grid.', <GuideLink to="views" anchor="cards-or-page">Cards or a page</GuideLink>],
        [<strong>Page</strong>, 'A widget built to fill a whole tab, with no card around it. A tab of this kind is Full page. The library marks these PAGE.', <GuideLink to="views" anchor="cards-or-page">Cards or a page</GuideLink>],
        [<strong>Widget Library</strong>, 'The panel where you find widgets and add them to a view. Opens with the sidebar button or W.', <GuideLink to="widgets" anchor="open-the-library">Open the Widget Library</GuideLink>],
        [<strong>Widget Studio</strong>, 'Where editors describe a widget and the agent builds it. Needs editor access.', <GuideLink to="widget-studio">Widget Studio</GuideLink>],
        [<strong>Domain</strong>, 'A grouping of global views, widgets and agents, such as Finance or Supply Chain. Access is granted per domain.', <GuideLink to="roles">Roles & permissions</GuideLink>],
        [<strong>Viewer, Editor, Admin</strong>, 'The three permission levels in a domain: use, build, and manage.', <GuideLink to="roles">Roles & permissions</GuideLink>],
        [<strong>Global admin</strong>, 'Someone who is an admin across every domain and can change deployment-wide settings.', <GuideLink to="access">Access</GuideLink>],
        [<strong>Role mapping</strong>, 'The link between a Databricks group or person and a domain at a permission level. It is how access is granted.', <GuideLink to="access">Access</GuideLink>],
        [<strong>Personal view</strong>, 'A view you made. Only you can change it; anyone you send its link can open it read-only.', <GuideLink to="views" anchor="share-a-view">Share a view</GuideLink>],
        [<strong>Shared view</strong>, 'A personal view someone sent you. It is listed under Shared Views and is read-only.', <GuideLink to="views" anchor="share-a-view">Share a view</GuideLink>],
        [<strong>Global view</strong>, 'A ready-made view shared with a domain. Copy one to make it your own; admins change the original.', <GuideLink to="views" anchor="copy-a-global-view">Copy a global view</GuideLink>],
        [<strong>View on its own</strong>, 'A view whose link opens just that view, with no sidebar, under its own title and logo. Also called standalone.', <GuideLink to="views" anchor="settings-opening">Opening</GuideLink>],
        [<strong>Lock</strong>, 'Freezes a view\u2019s layout so nothing is moved, added or removed by accident.', <GuideLink to="views" anchor="lock-and-unlock">Lock and unlock</GuideLink>],
        [<strong>Filter</strong>, 'A dropdown above a view\u2019s widgets that sets a variable the widgets can follow.', <GuideLink to="views" anchor="settings-filters">Filters</GuideLink>],
        [<strong>Look</strong>, 'A view\u2019s colors, font, background and card style.', <GuideLink to="views" anchor="settings-look">Look</GuideLink>],
        [<strong>Workspace</strong>, <>Dev, Test or Prod: the three places authored widgets, views and agents live inside one app. Chosen with the sidebar's Workspace switch. Not the same as a Databricks workspace.</>, <GuideLink to="promotion">Promotion</GuideLink>],
        [<strong>Deployment environment</strong>, 'Which copy of the Command Center you are using. Our Dev app is a real Dev app, and it still has all three workspaces.', <GuideLink to="overview" anchor="workspaces">Welcome</GuideLink>],
        [<strong>Promote</strong>, 'Copy a widget or view from Dev to Test, or Test to Prod, so more people see it.', <GuideLink to="promotion">Promotion</GuideLink>],
        [<strong>Version</strong>, 'Each save of a widget makes a new version. A card can show any of them.', <GuideLink to="promotion">Promotion</GuideLink>],
        [<strong>Roll back</strong>, 'Make an older version of a widget the current one again.', <GuideLink to="promotion">Promotion</GuideLink>],
        [<strong>Certify</strong>, 'Mark a widget version in Prod as reviewed and enterprise-ready. A signal to people, not a permission.', <GuideLink to="promotion">Promotion</GuideLink>],
        [<strong>Agent</strong>, 'The assistant persona you talk to: a saved set of instructions and tools. EDH Agent is the default.', <GuideLink to="assistant" anchor="agents">Choose an agent</GuideLink>],
        [<strong>Pin</strong>, 'Making a view or tab open the assistant with a chosen agent.', <GuideLink to="assistant" anchor="pin-an-agent">Pin an agent</GuideLink>],
        [<strong>Agent Studio</strong>, 'Where editors build and save agents. Needs editor access.', <GuideLink to="agent-studio">Agent Studio</GuideLink>],
        [<strong>Tool</strong>, 'Something an agent can do, such as running SQL, asking a Genie space or calling a function. Tools run as you.', <GuideLink to="agent-studio">Agent Studio</GuideLink>],
        [<strong>Genie space</strong>, <>A Databricks space that answers plain-language data questions over chosen tables. An agent can use one as a tool. <Ext href="https://docs.databricks.com/aws/en/genie/">Databricks docs</Ext></>, <GuideLink to="agent-studio">Agent Studio</GuideLink>],
        [<strong>MCP</strong>, <>Model Context Protocol, a standard way to give an AI agent tools and data. Agent Studio lists the tools your workspace offers through it. <Ext href="https://docs.databricks.com/aws/en/agents/mcp-tools/mcp-services">Databricks docs</Ext></>, <GuideLink to="agent-studio">Agent Studio</GuideLink>],
        [<strong>Unity Catalog</strong>, <>Databricks' access control for data. It decides which tables the assistant and widgets may read for you. <Ext href="https://docs.databricks.com/aws/en/data-governance/unity-catalog/">Databricks docs</Ext></>, <GuideLink to="assistant" anchor="trust">What to trust</GuideLink>],
        [<strong>Archived</strong>, 'Where a removed global view waits, to be restored or deleted for good.', <GuideLink to="promotion">Promotion</GuideLink>],
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
