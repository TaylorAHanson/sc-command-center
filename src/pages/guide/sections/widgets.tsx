/* eslint-disable react-refresh/only-export-components -- a section exports its data (`section`) beside its body */
import { MousePointerClick } from 'lucide-react';
import type { GuideSection } from '../types';
import { Callout, Card, Cards, Details, GuideLink, H2, Kbd, Lead, List, P, Shot, Step, Steps, Table, UI } from '../kit';

const Body = () => (
  <>
    <Lead>
      Widgets are the building blocks of a view: charts, tables, forms and tools. You find them in the Widget Library,
      drop them on a tab, then move, resize and set them up.
    </Lead>

    <H2 id="open-the-library">Open the Widget Library</H2>
    <P>
      Click <UI>Widget Library (w)</UI> in the sidebar, or press <Kbd>W</Kbd> when you are not typing in a box. A panel
      rises over the bottom three quarters of the screen. <Kbd>Esc</Kbd>, the X, or a click outside the panel closes
      it. The library lists the published widgets shared with you, and the widgets you manage, in the domain you have
      selected, most used first. A widget nobody has shared with you doesn&rsquo;t appear.
    </P>
    <Shot
      name="use-widget-library"
      alt="The Widget Library panel with search, view toggle, filters and widget cards"
      legend={[
        'Search widgets: matches names and descriptions.',
        'Switch between grid and list view.',
        'Filters: Certified, and which widgets you may use.',
        'A widget card. Click it or drag it onto the view; hover for Clone, Edit and Delete.',
      ]}
    />
    <Table
      head={['Control', 'What it does']}
      rows={[
        [<UI>Search widgets…</UI>, 'Searches names and descriptions across every group, ignoring the group you picked on the left.'],
        [<><UI>Categories</UI> / <UI>Domains</UI></>, 'Groups the list down the left side; the number beside each group is how many widgets it holds. Domains are labels for finding things, not permissions.'],
        [<><UI>Grid View</UI> / <UI>List View</UI></>, 'Cards with previews, or a table of name, creator, status, popularity and size. A row shows the same badges under Status, and the same hover icons, as a card.'],
        [<UI>Certified</UI>, 'Shows widgets marked certified, plus your own. Your choice is remembered in this browser.'],
        [<><UI>All</UI> / <UI>Mine</UI> / <UI>Shared with me</UI></>, 'Every widget you can see, the widgets you built, or the widgets other people built and shared with you.'],
        [<UI>Top creators</UI>, <>Lists who builds the widgets people use. Click a name to see only their widgets; the <UI>by …</UI> button next to the filters clears it.</>],
      ]}
    />
    <Details summary="What a card shows">
      <List>
        <li>A <UI>CERTIFIED</UI> badge when the widget has been reviewed, and a <UI>PAGE</UI> badge when it is built to fill a whole tab.</li>
        <li>The number of times people have added it, the creator ("by you" for yours), its domain, its default size, such as 10×8, and an icon for who it is shared with.</li>
        <li>
          On a widget you can manage, a <UI>NOT PUBLISHED YET</UI> or <UI>UNPUBLISHED CHANGES</UI> chip when other people
          don&rsquo;t yet see what you have saved.
        </li>
        <li>
          On widgets with no creator recorded, someone who can manage the widget sees <UI>Did you build this? Claim it</UI>.
          Confirm to be credited as its creator.
        </li>
        <li>
          Hover icons: <UI>Clone widget</UI> opens a copy in Widget Studio as a new widget of your own, the share icon
          opens <UI>Share</UI> to see who has the widget (and change that, if you can manage it), and{' '}
          <UI>Edit in Widget Studio</UI> and <UI>Delete widget</UI> appear for people who can manage the widget. In list
          view the same icons appear at the end of the row when you hover it.
        </li>
        <li>
          Can&rsquo;t find a widget you were told about? It has to be shared with you and published. A widget you only
          see on a view someone shared with you shows there, but the library doesn&rsquo;t offer it. See{' '}
          <GuideLink to="access" anchor="ask">Ask for access</GuideLink>.
        </li>
      </List>
    </Details>
    <Callout kind="warn" title="Delete widget is permanent">
      <UI>Delete widget</UI> removes the widget from the library for everyone, after one confirmation that says it
      cannot be undone. To take a widget off just your view, use the X on the widget instead.
    </Callout>

    <H2 id="add-a-widget">Add a widget to a view</H2>
    <Steps>
      <Step>Open the view and the tab you want the widget on. If it is locked, choose <UI>Unlock layout</UI> in the <UI>⋯</UI> menu.</Step>
      <Step>Open the Widget Library and find the widget.</Step>
      <Step>
        Click its card to add it automatically, or drag the card onto the view and drop it where you want it.
      </Step>
      <Step>
        The library stays open after a click, so you can add several widgets in a row. It closes itself shortly after
        you start a drag.
      </Step>
      <Step>
        If a <UI>Widget settings</UI> dialog opens, fill it in and click <UI>Add widget</UI>. See{' '}
        <GuideLink to="widgets" anchor="settings">Widget settings</GuideLink>.
      </Step>
    </Steps>
    <P>
      On an empty tab the message "This tab is empty" repeats the way in. On a locked view the library shows{' '}
      <UI>View is Locked</UI> instead; choose <UI>Unlock layout</UI> in the view&rsquo;s <UI>⋯</UI> menu first. A tab that is a full
      page holds one widget; see{' '}
      <GuideLink to="views" anchor="cards-or-page">Views and layouts</GuideLink>.
    </P>

    <H2 id="arrange-and-resize">Arrange and resize</H2>
    <Shot
      name="use-widget-card"
      alt="A widget card with its header buttons and resize handle"
      legend={[
        'The grip. Drag the widget by its header to move it.',
        'Header buttons: version, copy link, help, full screen and remove.',
        'The resize handle in the bottom right corner.',
      ]}
    />
    <Steps>
      <Step>
        To move a widget, hold its header, the bar with the grip and the title, and drag. The other widgets flow out of
        the way.
      </Step>
      <Step>
        To resize, hover the bottom right corner until the small handle shows, then drag it to change the width and
        height.
      </Step>
    </Steps>
    <P>
      Layouts are saved as you go. Lock the view to freeze them: a locked view shows no grip and cannot be dragged or
      resized. See <GuideLink to="views" anchor="lock-and-unlock">Lock and unlock a view</GuideLink>.
    </P>

    <H2 id="header-buttons">What the header buttons do</H2>
    <P>
      Which buttons you see depends on the widget and on whether you may change the view. Hover one for its name.
    </P>
    <Table
      head={['Button', 'Name on hover', 'What it does']}
      rows={[
        [<UI>v1</UI>, 'Widget Version', <>Picks which published version of the widget this card shows. A blue dot and "Update available" mean a newer version has been published. Hidden on locked views and views you can only use.</>],
        ['Arrow out of a box', 'Open in New Tab', 'Opens the widget\u2019s own web address in a new browser tab. Only on widgets that have one.'],
        ['Chain link', 'Copy direct link to this widget', <>Copies a link that opens this view with the widget full screen. Turns into <UI>Link copied!</UI> for a moment. Not shown on a view that opens on its own.</>],
        ['Question mark', 'Help', <>Opens the widget's own help in a window titled "<em>Widget</em> - Help". Only on widgets that have help.</>],
        ['Cog', 'Widget settings', <>Opens the widget's settings. Only on widgets that have settings, and not on locked views or views you can only use.</>],
        ['Two arrows', 'Fullscreen', <>Fills the whole window with the widget. Click <UI>Exit Fullscreen</UI> or press <Kbd>Esc</Kbd> to return.</>],
        ['X', 'Remove Widget', <>Takes the widget off this tab. In full screen it reads <UI>Close</UI> and only leaves full screen.</>],
      ]}
    />

    <H2 id="settings">Widget settings</H2>
    <P>
      A widget that has settings shows a cog in its header. Click it to open <UI>Widget settings</UI>, change the values
      and click <UI>Save</UI>. A star beside a field means it is required; leave one empty and the dialog says what is
      missing instead of saving.
    </P>
    <List>
      <li>
        Some widgets need their settings before they can be placed. For those, <UI>Widget settings</UI> opens as you add
        the widget, and the button reads <UI>Add widget</UI>. Cancel and nothing is added.
      </li>
      <li>
        Settings belong to this card. The same widget on another view has its own values. On a view you manage, a
        change to them goes into the view&rsquo;s draft until you publish.
      </li>
      <li>
        A widget with no defined fields shows a single <UI>Configuration (JSON)</UI> box instead. Leave it alone unless
        the widget's author told you what to type.
      </li>
    </List>
    <Details summary="Links that go somewhere you choose">
      <P>
        A widget whose tiles or buttons lead somewhere, such as a hub page's Sales and Operations tiles, has named
        links, and you decide where each one goes. Open the widget's cog: every link offers the view's tabs,{' '}
        <UI>Not set</UI>, or <UI>Web address…</UI> (an http or https address, which opens in a new browser tab).
      </P>
      <List>
        <li>The choice belongs to this card, so the same widget can go to different tabs on different views.</li>
        <li>Renaming a tab keeps its links. Deleting a tab leaves links to it going nowhere, and the cog says so.</li>
        <li>A tile whose link is not set looks muted and does nothing.</li>
      </List>
    </Details>
    <Details summary="Values that differ in another deployment">
      <P>
        Because settings belong to the placed card, moving a view to another deployed app with Data Migration copies
        its card settings with it. Open each card&rsquo;s cog there when a value, such as a catalog or schema, must
        differ. See <GuideLink to="migration">Moving data to another app</GuideLink>.
      </P>
    </Details>

    <H2 id="full-screen">Full screen and direct links</H2>
    <P>
      Use the two-arrow button for a closer look at one widget, then <Kbd>Esc</Kbd> to come back. To send someone to
      that widget, click the chain link instead. The link opens your view with the widget in
      full screen. The person needs access to the view, not just the link, and it does not work for a widget on a
      full-page tab, which is already full size.
    </P>

    <H2 id="email">Send a widget&rsquo;s numbers by email</H2>
    <P>
      Some widgets have an email button. It opens the <UI>Send</UI> dialog, and nothing is sent until you press <UI>Send</UI> there. An agent
      with <GuideLink to="agent-studio" anchor="draft-emails">Draft emails</GuideLink> switched on opens the same dialog from a card in the chat.
    </P>
    <Steps>
      <Step title="Choose who it goes to">
        Type addresses in <UI>To</UI>, separated by commas. The widget may have filled some in; change them as you like. The line under the box says
        how many people and which domains this app allows.
      </Step>
      <Step title="Check the subject and the preview">
        The preview is the email exactly as it will arrive: its message or layout, any tables and pictures, with the attached files listed under it.
        A note under the preview says if an image was left out because it would have loaded from another site.
      </Step>
      <Step title="Send">
        Press <UI>Send</UI>. The email comes from the app&rsquo;s own address, replies come to you, and its footer names you and the view, with a link back
        to it. The send is recorded in <UI>Action Logs</UI>.
      </Step>
    </Steps>
    <Callout kind="note" title="Why Send might be unavailable">
      <List>
        <li><UI>Email isn&rsquo;t set up in this app yet</UI>: your administrators haven&rsquo;t finished setting up email. Ask them.</li>
        <li>An address is outside the domains this app allows, or the email has too many recipients. The dialog names the problem.</li>
        <li>You have reached the number of emails one person may send in 24 hours (50 unless an administrator changed it).</li>
      </List>
    </Callout>
    <P>
      To have the same numbers emailed on a timetable instead, use the widget&rsquo;s <UI>Schedule</UI> button if it has one; see{' '}
      <GuideLink to="schedules">Scheduled reports</GuideLink>.
    </P>

    <H2 id="remove-a-widget">Remove a widget</H2>
    <P>
      Click the X in the widget's header. It leaves the tab at once, with no confirmation, and its settings go with
      it. The widget is still in the Widget Library, so you can add it again, though you would set it up again too. The
      X is hidden while the view is locked.
    </P>

    <H2 id="where-next">Where next</H2>
    <Cards cols={3}>
      <Card to="views" title="Views and layouts">Tabs, locking, sharing and view settings.</Card>
      <Card to="assistant" title="The assistant">Ask about the widgets on your tab.</Card>
      <Card to="widget-studio" title="Widget Studio">Build a widget the library does not have.</Card>
    </Cards>
  </>
);

export const section: GuideSection = {
  id: 'widgets',
  group: 'use',
  title: 'Using widgets',
  summary: 'Find a widget, drop it on a view, arrange it and set it up.',
  icon: MousePointerClick,
  keywords: 'widget library drag drop resize move remove gear settings version fullscreen link certified search clone email send recipients csv',
  Body,
};
