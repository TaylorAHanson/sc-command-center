/* eslint-disable react-refresh/only-export-components -- a section exports its data (`section`) beside its body */
import { Book, Bot, LayoutGrid, Rocket, Search } from 'lucide-react';
import type { GuideSection } from '../types';
import { Callout, Card, Cards, GuideLink, H2, Kbd, Lead, List, Needs, OpenLink, P, Shot, Table, UI } from '../kit';

const Body = () => (
  <>
    <Lead>
      The Command Center puts the data you watch and the actions you take on one screen, so you can see what changed
      and act on it without switching tools. This page shows what is on the screen and where to go first.
    </Lead>

    <P>
      Everything on screen is built from three things, and all three are made inside the app, not installed
      from outside it:
    </P>
    <List>
      <li><UI>Widgets</UI> are the pieces: a chart, a table, a form, a button that does something.</li>
      <li><UI>Views</UI> are pages of widgets that you arrange, on one or more tabs.</li>
      <li><UI>Agents</UI> are the assistants you can ask questions of. Each has its own instructions, data and tools.</li>
    </List>
    <P>
      People with editor access build widgets in Widget Studio and agents in Agent Studio. Everyone else uses what
      is there, and can assemble their own views from it.
    </P>

    <H2 id="five-ways-in">Five ways in</H2>
    <P>
      The first time you open the app with no views of your own, a welcome panel offers five ways to start, with the
      assistant open beside it. Hover a card to see where that feature lives in the sidebar.
    </P>
    <Shot
      name="use-welcome"
      alt="The welcome panel with five numbered cards"
      legend={[
        'Ask the assistant: pick a starter question, or choose Ask your own.',
        'Browse global views: ready-made views your team shares.',
        'Find widgets: opens the Widget Library.',
        'Build your own widget: opens Widget Studio.',
        'Build your own agent: opens Agent Studio.',
      ]}
    />
    <Table
      head={['Card', 'What it does', 'Who can use it']}
      rows={[
        [<UI>Ask the assistant</UI>, 'Types a starter question into the message box for you. It never sends it; you press Send.', 'Everyone'],
        [<UI>Browse global views</UI>, 'Lists ready-made views from your domains. Open one as it is, or copy it to My Views to make it yours.', 'Everyone'],
        [<UI>Find widgets</UI>, <>Opens the Widget Library. You can also press <Kbd>W</Kbd>.</>, 'Everyone'],
        [<UI>Build your own widget</UI>, 'Opens Widget Studio, where you describe what you need and the studio writes it.', <>Editor in a domain <Needs role="Editor" /></>],
        [<UI>Build your own agent</UI>, 'Opens Agent Studio, where you give an assistant its own instructions, data and tools.', <>Editor in a domain <Needs role="Editor" /></>],
      ]}
    />
    <P>
      Without editor access, the two studio cards say so and do not open anything. Close the panel with <UI>Got it</UI>,
      the X or <UI>Esc</UI>. To see it again, open <UI>Resources → Getting Started</UI>. It does not open when you
      arrive from a link to a view. <UI>Or start from a blank view</UI> at the bottom makes an empty view of your own.
    </P>

    <H2 id="tour">A tour of the screen</H2>
    <Shot
      name="use-overview"
      alt="The Command Center with a view open, the sidebar on the left and the assistant button at the bottom right"
      legend={[
        'My Views in the sidebar, with New View below them.',
        'The Workspace switcher: Dev, Test and Prod.',
        'The view header: Settings, Lock and Share for the view on screen.',
        'The assistant button, named after the agent that is selected.',
      ]}
    />
    <Table
      head={['Part', 'Where', 'What it does']}
      rows={[
        [<UI>My Views</UI>, 'Sidebar', <>Your own views. <UI>New View</UI> adds one. Hover a view to rename or close it, and drag the grip to reorder. See <GuideLink to="views">Views and layouts</GuideLink>.</>],
        [<UI>Shared Views</UI>, 'Sidebar, when you have any', 'Views other people sent you by link. They are read-only for you.'],
        [<UI>Global Views</UI>, 'Sidebar', 'Ready-made views shared with a domain. Click one to open it, hover and click the copy icon to put a copy in My Views.'],
        [<UI>Workspace</UI>, 'Sidebar, near the top', <>Dev, Test or Prod: which copy of the authored content you are looking at. See <GuideLink to="overview" anchor="workspaces">the three workspaces</GuideLink>.</>],
        [<UI>Widget Library</UI>, 'Sidebar', <>Opens the tray of widgets you can add. See <GuideLink to="widgets">Using widgets</GuideLink>.</>],
        [<><UI>Widget Studio</UI> and <UI>Agent Studio</UI></>, 'Sidebar, editors only', <>Where widgets and agents are built. See <GuideLink to="widget-studio">Widget Studio</GuideLink> and <GuideLink to="agent-studio">Agent Studio</GuideLink>.</>],
        [<UI>Resources</UI>, 'Sidebar, bottom', <><UI>Getting Started</UI>, <UI>User Guide</UI>, <UI>Release Notes</UI> and, if you have access, <UI>Admin Panel</UI>.</>],
        ['View header', 'Top of the screen', <>The view's name, with <UI>Settings</UI>, <UI>Lock</UI> and <UI>Share</UI> on the right, and <UI>Add tab</UI> while a view has one tab.</>],
        ['The assistant', 'Button at the bottom right', <>Opens a panel down the right side that answers questions about the view and your data. See <GuideLink to="assistant">The assistant</GuideLink>.</>],
      ]}
    />
    <Callout kind="tip" title="More room">
      The menu icon at the top of the sidebar collapses it to a narrow strip. The assistant panel collapses with the
      button at its top right, and you can drag its left edge to change its width.
    </Callout>

    <H2 id="workspaces">The three workspaces</H2>
    <P>
      Every Command Center has three workspaces, <UI>Dev</UI>, <UI>Test</UI> and <UI>Prod</UI>, so that widgets,
      views and agents under construction do not reach the people relying on the finished ones. Editors build in
      Dev, check in Test, then promote to Prod. You need Editor or Admin on a domain to open Dev or Test; everyone
      else stays on Prod. A workspace is not the same as which Command Center you opened. The{' '}
      <GuideLink to="promotion">Promoting work</GuideLink> page explains how work moves between them.
    </P>

    <H2 id="roles-at-a-glance">What your role lets you do</H2>
    <P>
      Access is set per domain, and the highest level you hold on a domain applies there.
    </P>
    <Table
      head={['', 'Viewer', 'Editor', 'Admin']}
      rows={[
        ['See and use the domain\'s global views and widgets', 'Yes', 'Yes', 'Yes'],
        ['Build your own views and use the assistant', 'Yes', 'Yes', 'Yes'],
        ['Create and edit widgets, agents and global views in the domain', 'No', 'Yes', 'Yes'],
        ['Open Dev and Test, and promote, roll back and certify', 'No', 'Yes', 'Yes'],
        ['Assign domain permissions to people and groups', 'No', 'No', 'Yes'],
      ]}
    />
    <P>
      Roles come from your Databricks groups. See <GuideLink to="roles">Roles and permissions</GuideLink> for the
      full picture and <GuideLink to="access">Managing access</GuideLink> to ask for more.
    </P>
    <Callout kind="note" title="Your data access is separate">
      What you can see in a table or query is decided by Databricks, as you. A role here never widens it.
    </Callout>

    <H2 id="where-next">Where next</H2>
    <Cards>
      <Card to="quickstart" title="Your first ten minutes" icon={<Rocket className="w-4 h-4 text-brand-blue" />}>
        Make a view, add a widget, ask the assistant and share it.
      </Card>
      <Card to="views" title="Views and layouts" icon={<LayoutGrid className="w-4 h-4 text-brand-blue" />}>
        Tabs, settings, filters, locking and sharing.
      </Card>
      <Card to="widgets" title="Using widgets" icon={<Search className="w-4 h-4 text-brand-blue" />}>
        Find a widget, drop it on a view and set it up.
      </Card>
      <Card to="assistant" title="The assistant" icon={<Bot className="w-4 h-4 text-brand-blue" />}>
        Ask questions, attach files and keep conversations.
      </Card>
    </Cards>
    <P>
      To build your own, start with <GuideLink to="widget-studio">Widget Studio</GuideLink> or{' '}
      <GuideLink to="agent-studio">Agent Studio</GuideLink>. You can also open them directly:{' '}
      <OpenLink page="studio">Widget Studio</OpenLink> and <OpenLink page="agent-studio">Agent Studio</OpenLink>.
    </P>
  </>
);

export const section: GuideSection = {
  id: 'overview',
  group: 'start',
  title: 'Welcome',
  summary: 'What the Command Center is and how to find your way around.',
  icon: Book,
  keywords: 'start introduction getting started tour sidebar first run welcome',
  Body,
};
