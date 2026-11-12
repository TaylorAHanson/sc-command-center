/* eslint-disable react-refresh/only-export-components -- a section exports its data (`section`) beside its body */
import { Book, Bot, LayoutGrid, Rocket, Search } from 'lucide-react';
import type { GuideSection } from '../types';
import { Callout, Card, Cards, GuideLink, H2, Kbd, Lead, List, OpenLink, P, Shot, Table, UI } from '../kit';

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
      Anyone can build widgets in Widget Studio and agents in Agent Studio, and assemble views from them. What you
      build is yours until you share it, and people you share it with see the version you last published.
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
        'Browse views: views other people have shared with you.',
        'Find widgets: opens the Widget Library.',
        'Build your own widget: opens Widget Studio.',
        'Build your own agent: opens Agent Studio.',
      ]}
    />
    <Table
      head={['Card', 'What it does', 'Who can use it']}
      rows={[
        [<UI>Ask the assistant</UI>, 'Types a starter question into the message box for you. It never sends it; you press Send.', 'Everyone'],
        ['Browse views', 'Lists the views other people have shared with you, so you can open one.', 'Everyone'],
        [<UI>Find widgets</UI>, <>Opens the Widget Library. You can also press <Kbd>W</Kbd>.</>, 'Everyone'],
        [<UI>Build your own widget</UI>, 'Opens Widget Studio, where you describe what you need and the studio writes it.', 'Everyone'],
        [<UI>Build your own agent</UI>, 'Opens Agent Studio, where you give an assistant its own instructions, data and tools.', 'Everyone'],
      ]}
    />
    <P>
      Close the panel with <UI>Got it</UI>,
      the X or <UI>Esc</UI>. To see it again, open <UI>Resources → Getting Started</UI>. It does not open when you
      arrive from a link to a view. <UI>Or start from a blank view</UI> at the bottom makes an empty view of your own.
    </P>

    <H2 id="tour">A tour of the screen</H2>
    <Table
      head={['Part', 'Where', 'What it does']}
      rows={[
        [<UI>Search views</UI>, 'Sidebar, top', 'Finds any view you can open as you type. Enter shows every match in Browse views.'],
        [<><UI>Favorites</UI> and <UI>Recent</UI></>, 'Sidebar', <>The views you starred, in your order, and the last five you opened. See <GuideLink to="views" anchor="sidebar">Your views in the sidebar</GuideLink>.</>],
        [<UI>My views</UI>, 'Sidebar', <>The eight views you own that changed last; <UI>All my views</UI> shows the rest. Hover a view to rename or close it. See <GuideLink to="views">Views and layouts</GuideLink>.</>],
        [<><UI>New view</UI> and <UI>Browse views</UI></>, 'Sidebar', 'Start a blank view, or find views other people have shared with you. New for you, above them, counts the ones shared lately.'],
        [<UI>Archived</UI>, 'Sidebar, collapsed', <>Archived views you manage, which you can restore. See <GuideLink to="publishing" anchor="archive">Archive, restore or delete a view</GuideLink>.</>],
        [<UI>Widget Library</UI>, 'Sidebar', <>Opens the tray of widgets you can add. See <GuideLink to="widgets">Using widgets</GuideLink>.</>],
        [<><UI>Widget Studio</UI> and <UI>Agent Studio</UI></>, 'Sidebar', <>Where widgets and agents are built. See <GuideLink to="widget-studio">Widget Studio</GuideLink> and <GuideLink to="agent-studio">Agent Studio</GuideLink>.</>],
        [<UI>Resources</UI>, 'Sidebar, bottom', <><UI>Getting Started</UI>, <UI>User Guide</UI>, <UI>Release Notes</UI> and, if you have access, <UI>Admin Panel</UI>.</>],
        ['View header', 'Top of the screen', <>The view's name, with a chip saying whether it is published on views you manage. On the right: <UI>Draft</UI> / <UI>Published</UI> when there are unpublished changes, the <UI>⋯</UI> menu (layout, <UI>Add a tab…</UI>, <UI>View settings…</UI>, <UI>Lock layout</UI>, version history), <UI>Share</UI>, and <UI>Publish</UI> when there is something to publish.</>],
        ['The assistant', 'Button at the bottom right', <>Opens a panel down the right side that answers questions about the view and your data. See <GuideLink to="assistant">The assistant</GuideLink>.</>],
      ]}
    />
    <Callout kind="tip" title="More room">
      The menu icon at the top of the sidebar collapses it to a narrow strip. The assistant panel collapses with the
      button at its top right, and you can drag its left edge to change its width.
    </Callout>

    <H2 id="sharing-at-a-glance">Who can do what</H2>
    <P>
      Every view, widget and agent has its own access list, like a Databricks dashboard. The person who made it can
      manage it, and shares it with people or groups at one of two levels. The highest level you hold applies.
    </P>
    <Table
      head={['', 'Can use', 'Can manage']}
      rows={[
        ['See and open the published version', 'Yes', 'Yes'],
        ['Place a published widget on your own views, chat with a published agent', 'Yes', 'Yes'],
        ['Edit the draft, publish, discard and revert', 'No', 'Yes'],
        ['Change who it is shared with', 'No', 'Yes'],
      ]}
    />
    <P>
      Anyone can create views, widgets and agents of their own. <UI>Administrators</UI> can manage everything and see the
      Admin Panel. See <GuideLink to="sharing">Sharing &amp; permissions</GuideLink> for the full picture,{' '}
      <GuideLink to="publishing">Drafts &amp; publishing</GuideLink> for how changes reach people, and{' '}
      <GuideLink to="access">Administrators &amp; access</GuideLink> to ask for access.
    </P>
    <Callout kind="note" title="Your data access is separate">
      What you can see in a table or query is decided by Databricks, as you. Sharing something here never widens it.
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
