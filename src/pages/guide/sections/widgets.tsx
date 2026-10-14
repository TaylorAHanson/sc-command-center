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
      it. The library lists the widgets in the domain you have selected, most used first.
    </P>
    <Shot
      name="use-widget-library"
      alt="The Widget Library panel with search, view toggle, filters and widget cards"
      legend={[
        'Search widgets: matches names and descriptions.',
        'Switch between grid and list view.',
        'Filters: Certified, and All, Accessible to me or Access Request Needed.',
        'A widget card. Click it or drag it onto the view; hover for Clone, Edit and Delete.',
      ]}
    />
    <Table
      head={['Control', 'What it does']}
      rows={[
        [<UI>Search widgets…</UI>, 'Searches names and descriptions across every group, ignoring the group you picked on the left.'],
        [<><UI>Categories</UI> / <UI>Domains</UI></>, 'Groups the list down the left side; the number beside each group is how many widgets it holds.'],
        [<><UI>Grid View</UI> / <UI>List View</UI></>, 'Cards with previews, or a table of name, creator, status, popularity and size.'],
        [<UI>Certified</UI>, 'Shows widgets marked certified, plus your own. Your choice is remembered in this browser.'],
        [<><UI>All</UI> / <UI>Accessible to me</UI> / <UI>Access Request Needed</UI></>, 'Filters by whether you may use the widget.'],
        [<UI>Top creators</UI>, <>Lists who builds the widgets people use. Click a name to see only their widgets; the <UI>by …</UI> button next to the filters clears it.</>],
      ]}
    />
    <Details summary="What a card shows">
      <List>
        <li>A <UI>CERTIFIED</UI> badge when the widget has been reviewed, and a <UI>PAGE</UI> badge when it is built to fill a whole tab.</li>
        <li>The number of times people have added it, the creator ("by you" for yours), its domain and its default size, such as 10×8.</li>
        <li>
          On widgets with no creator recorded, an editor of the domain sees <UI>Did you build this? Claim it</UI>.
          Confirm to be credited as its creator.
        </li>
        <li>
          A lock and <UI>Access Restricted</UI> on a widget you may not use yet. It cannot be added, and the access
          filters above separate these from the rest. See <GuideLink to="access">Access and permissions</GuideLink>.
        </li>
        <li>
          Hover icons: <UI>Clone widget</UI> opens a copy in Widget Studio, <UI>Edit in Widget Studio</UI> appears for
          editors of the widget's domain, and <UI>Delete widget</UI> appears for its author.
        </li>
      </List>
    </Details>
    <Callout kind="warn" title="Delete widget is permanent">
      <UI>Delete widget</UI> removes the widget from the library for everyone, after one confirmation that says it
      cannot be undone. To take a widget off just your view, use the X on the widget instead.
    </Callout>

    <H2 id="add-a-widget">Add a widget to a view</H2>
    <Steps>
      <Step>Open the view and the tab you want the widget on. Unlock the view if it is locked.</Step>
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
      <UI>View is Locked</UI> and tells you to unlock it with the lock button in the top right. A tab that is a full
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
        [<UI>v1</UI>, 'Widget Version', <>Picks which version of the widget this card shows. A blue dot and "Update available" mean a newer version exists. Hidden on locked and shared views.</>],
        ['Arrow out of a box', 'Open in New Tab', 'Opens the widget\u2019s own web address in a new browser tab. Only on widgets that have one.'],
        ['Chain link', 'Copy direct link to this widget', <>Copies a link that opens this view with the widget full screen. Turns into <UI>Link copied!</UI> for a moment. Not shown on a view that opens on its own.</>],
        ['Question mark', 'Help', <>Opens the widget's own help in a window titled "<em>Widget</em> - Help". Only on widgets that have help.</>],
        ['Cog', 'Widget settings', <>Opens the widget's settings. Only on widgets that have settings, and not on locked or shared views.</>],
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
        Settings belong to this card, in this workspace. The same widget on another view, or in another workspace,
        has its own values.
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
    <Details summary="Values that differ between Dev, Test and Prod">
      <P>
        Because settings belong to the placed card in the current workspace, a promoted widget arrives without your
        values: drop it in each workspace and fill in its settings there. Promoting a whole view copies its existing
        card settings, so open each promoted card's cog when a value must differ in the target workspace. See{' '}
        <GuideLink to="promotion">Promotion</GuideLink>.
      </P>
    </Details>

    <H2 id="full-screen">Full screen and direct links</H2>
    <P>
      Use the two-arrow button for a closer look at one widget, then <Kbd>Esc</Kbd> to come back. To send someone to
      that widget, click the chain link instead. The link opens your view in the same workspace with the widget in
      full screen. The person needs access to the view, not just the link, and it does not work for a widget on a
      full-page tab, which is already full size.
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
  keywords: 'widget library drag drop resize move remove gear settings version fullscreen link certified search clone',
  Body,
};
