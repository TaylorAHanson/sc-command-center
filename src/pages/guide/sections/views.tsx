/* eslint-disable react-refresh/only-export-components -- a section exports its data (`section`) beside its body */
import { LayoutGrid } from 'lucide-react';
import type { GuideSection } from '../types';
import { Callout, Card, Cards, Code, Details, GuideLink, H2, H3, Kbd, Lead, List, P, Shot, Step, Steps, Table, UI } from '../kit';

const Body = () => (
  <>
    <Lead>
      A view is a page of widgets that you arrange yourself, on one or more tabs. This page covers making views,
      organizing them with tabs, copying a global view, locking, sharing, and the view's Settings.
    </Lead>

    <Shot
      name="use-view-header"
      alt="The view header with Settings, Lock and Share buttons and the tab bar"
      legend={[
        'Settings: how the view opens, looks, filters and which agent it uses.',
        'Lock: freezes the layout so nothing moves by accident.',
        'Share: copies a link to the view.',
        'The + in the tab bar adds another tab.',
      ]}
    />

    <H2 id="create-a-view">Create and organize views</H2>
    <Steps>
      <Step>
        Under <UI>My Views</UI> in the sidebar, click <UI>New View</UI>. A blank view opens.
      </Step>
      <Step>
        To rename it, hover its name, click the pencil, type the new name and press <Kbd>Enter</Kbd>. <Kbd>Esc</Kbd>{' '}
        cancels.
      </Step>
      <Step>
        To reorder your views, drag one by the grip beside its name and drop it where you want it.
      </Step>
    </Steps>
    <P>
      Hover a view and click the small X to close it. For a view you made, that deletes it right away, with no
      confirmation. Views other people sent you appear under <UI>Shared Views</UI>; the X there only removes them from
      your list.
    </P>
    <Callout kind="warn" title="Closing deletes">
      There is no undo for closing one of your own views. Copy it first if you might want it back.
    </Callout>

    <H2 id="tabs">Add and manage tabs</H2>
    <P>
      Tabs split a view into separate canvases, for example one per team or topic. Widgets you add go on the tab you
      are looking at. Filters you set apply on every tab of the view.
    </P>
    <Steps>
      <Step title="Add the second tab">
        Click <UI>Add tab</UI> in the top right. Choose <UI>Cards on a grid</UI> or <UI>Full page</UI>, then name the new
        tab. If the tab you are on has no name yet, the same dialog asks for it too; left empty, it becomes "Overview".
      </Step>
      <Step title="Add more">
        Once there are two tabs, a tab bar appears under the header. Click its <UI>+</UI>, choose the kind of tab,
        type a name and press <Kbd>Enter</Kbd>. A view can have up to 50 tabs.
      </Step>
      <Step title="Rename, reorder or delete">
        Double-click a tab, or select it and press <Kbd>F2</Kbd>, to rename it. Drag a tab to reorder it. Click the X
        on a tab to delete it; if it holds widgets you are asked first, and the widgets stay in the Widget Library.
        The last remaining tab cannot be deleted.
      </Step>
    </Steps>
    <Shot
      name="use-tabs"
      alt="The Add tab menu offering Cards on a grid and Full page"
      legend={[
        'Add tab, at the top right of the view.',
        'Cards on a grid: several widgets, each in a card you can move and resize.',
        'Full page: one widget that fills the whole tab.',
      ]}
    />
    <Shot
      name="use-tabs-name"
      alt="The box for naming a new tab"
      legend={[
        'The name of the new tab. It starts as "Tab 2", selected so you can type over it.',
        'Add tab creates it. Back returns to the choice of layout.',
      ]}
    />
    <P>
      From the keyboard, press <Kbd>Tab</Kbd> to reach the tab bar, use the arrow keys, <Kbd>Home</Kbd> and{' '}
      <Kbd>End</Kbd> to move along it, and <Kbd>Enter</Kbd> or <Kbd>Space</Kbd> to open a tab.
    </P>
    <Callout kind="admin" title="Who can change tabs">
      Whoever may move widgets in a view may change its tabs. That is not possible while the view is locked, and on a
      global view only an admin can do it.
    </Callout>

    <H3 id="cards-or-page">Cards on a grid or a full page</H3>
    <P>
      Each tab is one of two kinds. <UI>Cards on a grid</UI> holds several widgets, each in its own card that you can
      move and resize. <UI>Full page</UI> holds one widget that fills the whole tab with no card around it, which suits a
      landing page or a hub. A view can mix them in any order.
    </P>
    <List>
      <li>
        <UI>Add tab</UI> and the <UI>+</UI> ask which kind a new tab should be.
      </li>
      <li>
        To switch the tab you are looking at, use <UI>Grid</UI> / <UI>Full page</UI> in the top right of the header. It
        is there whenever you may change the view's tabs, including on a view with only one tab. <UI>Full page</UI> is
        grayed out on a grid holding more than one widget; hover it to see why, and remove all but one widget first.
      </li>
      <li>
        To fill a page, drag a widget from the Widget Library onto it. Dropping another widget replaces the first,
        after asking.
      </li>
    </List>
    <Details summary="The page toolbar">
      <P>
        On a full page, the toolbar in the top right corner is shown only to people who may change the tab, inside the
        Command Center. It has <UI>Choose a widget</UI> (or <UI>Change widget</UI>), <UI>Edit in Widget Studio</UI> for
        editors of the widget's domain, a gear for the widget's settings, and a bin to take the widget off the page.
        The gear is grayed out when the widget was built without settings. A view opened on its own shows the page
        without the toolbar. Any widget can go on a page, but one built as a page in Widget Studio, marked{' '}
        <UI>PAGE</UI> in the library, is made to fill it.
      </P>
    </Details>

    <H2 id="copy-a-global-view">Copy a global view</H2>
    <P>
      <UI>Global Views</UI> are ready-made views shared with a domain. You see only the ones in domains where you are at
      least a Viewer, and you cannot change them unless you are an admin. To make one your own:
    </P>
    <Steps>
      <Step>In the sidebar, hover the global view you want.</Step>
      <Step>
        Click the copy icon ("Copy this template to My Views"). A copy named "<em>name</em> (Copy)", with all its tabs,
        opens under <UI>My Views</UI>, and you can edit it freely.
      </Step>
    </Steps>
    <Shot
      name="use-global-views-empty"
      alt="The Global Views heading in the sidebar with the hint Click to view, hover to copy"
      narrow
      legend={['The Global Views section of the sidebar. Click a view to open it; hover over one to copy it.']}
    />

    <H2 id="lock-and-unlock">Lock and unlock a view</H2>
    <P>
      Click <UI>Lock</UI> in the top right once the layout is how you want it. A locked view cannot be dragged, resized
      or have widgets added, removed or tabs changed. The button then reads <UI>Locked</UI>; click it to unlock when you
      want to change things again. The Widget Library tells you the view is locked instead of adding widgets.
    </P>
    <Shot
      name="use-lock"
      alt="The view header before and after locking: Lock becomes Locked"
      legend={[
        'Lock (above) becomes Locked (below). Click it again to unlock. The widget loses its grip, version box and remove button, and the + for new tabs goes.',
      ]}
    />
    <P>
      <UI>Lock</UI> and <UI>Share</UI> appear on views you own, and on global views for admins. Views shared with you do
      not show them.
    </P>

    <H2 id="share-a-view">Share a view</H2>
    <Steps>
      <Step>Open the view and click <UI>Share</UI> in the top right.</Step>
      <Step>
        The button reads <UI>Copied!</UI> and a link to the view, on the tab you are on, is on your clipboard. Copying
        the address from the browser's address bar gives the same link.
      </Step>
      <Step>
        Send it. Whoever opens it, signed in, finds the view under <UI>Shared Views</UI>, read-only. For a global view
        they also need access to its domain.
      </Step>
    </Steps>
    <Callout kind="note" title="The link carries the workspace">
      A copied link opens in the workspace it was copied from, so send Test links to testers and Prod links to users.
      Someone without access to Dev or Test who opens such a link sees Prod, with a note saying so.
    </Callout>
    <Details summary="How links are written">
      <P>
        Links use names, not codes. A global view's link is its name, for example{' '}
        <Code>#/app/supply-hub/inventory</Code> for the Inventory tab of the Supply Hub view. A second global view with
        the same name gets <Code>supply-hub-2</Code>. If a global view is renamed, links to its old name keep working.
      </P>
      <P>
        A personal view's link is its name followed by a code. That code is what keeps a personal view to the people
        you send it to, so do not strip it. A tab is named by its own name unless two tabs share one. After a tab is
        renamed, an old link to it opens the first tab. A link to the first tab leaves the tab out and opens whichever
        tab is first. Links from earlier releases still work.
      </P>
      <P>
        The share icon on a single widget copies a different link: one that opens that widget full screen. See{' '}
        <GuideLink to="widgets" anchor="full-screen">Using widgets</GuideLink>.
      </P>
    </Details>

    <H2 id="view-settings">View settings</H2>
    <P>
      Click <UI>Settings</UI> in the header to open <UI>View settings</UI>. It has four sections down its left side:{' '}
      <UI>Opening</UI>, <UI>Look</UI>, <UI>Filters</UI> and <UI>Assistant</UI>. Hover the <UI>?</UI> beside any field
      for a short explanation. A red dot marks a section with something to fix; the footer names it, and{' '}
      <UI>Save</UI> stays off until you do. Nothing is stored until you press <UI>Save</UI>.
    </P>
    <Callout kind="admin" title="Who can open Settings">
      The owner of a personal view. For a global view, an admin or an Editor in its domain. It is not offered on views
      shared with you.
    </Callout>
    <Shot
      name="use-view-settings"
      alt="The View settings dialog open on its Opening section"
      legend={[
        'The four sections: Opening, Look, Filters and Assistant.',
        'The two ways the view\u2019s link can open: Inside Command Center or On its own.',
      ]}
    />

    <H3 id="settings-opening">Opening: share a view as a page of its own</H3>
    <P>
      <UI>Opening</UI> decides what the view's link opens. <UI>Inside Command Center</UI> is the default, with the
      sidebar, Widget Library and studios around it. <UI>On its own</UI> opens just that view, with no sidebar, library
      or studios, under a title, logo and browser tab icon you set.
    </P>
    <Steps>
      <Step>Open <UI>Settings → Opening</UI> and choose <UI>On its own</UI>.</Step>
      <Step>
        Fill in <UI>Title</UI>, <UI>Logo</UI> and <UI>Browser tab icon</UI>. These fields appear only once{' '}
        <UI>On its own</UI> is chosen. The title falls back to the view's name.
      </Step>
      <Step><UI>Save</UI>, then click <UI>Preview</UI> in the header to see it as other people will.</Step>
      <Step>Share the view's link. It opens only that view, read-only, under your title and logo.</Step>
    </Steps>
    <Shot
      name="use-share"
      alt="View settings with On its own chosen and its extra fields showing"
      legend={[
        'The sections of View settings; this is Opening.',
        'On its own, chosen.',
        'The fields that appear once it is chosen: Header, Title, Logo and Browser tab icon.',
      ]}
    />
    <Details summary="More about views that open on their own">
      <List>
        <li>
          The view is read-only for everyone, including its owner; its tabs can be switched but not changed. The
          assistant appears too, unless the view's agent is <UI>No agent</UI>.
        </li>
        <li>
          <UI>Header</UI>: <UI>Show the header</UI> or <UI>No header: the page has its own</UI>. Choose the second when
          the view's page draws its own title bar. The view then starts straight with its tabs or page, the logo field
          goes away, and the title is used only on the browser tab.
        </li>
        <li>
          With <UI>No header</UI>, <UI>Copy link</UI>, <UI>Edit</UI> (or <UI>Back to editing</UI> in a preview) and the
          workspace label sit in a small bar at the bottom left, shown only to people who get at least one of them.
          Inside the Command Center, the view's editing buttons (<UI>Preview</UI>, <UI>Grid</UI> /{' '}
          <UI>Full page</UI>, <UI>Add tab</UI>, <UI>Settings</UI>, <UI>Lock</UI>, <UI>Share</UI>) move to that bar too.
        </li>
        <li>
          While you edit the view inside the Command Center, its header shows the same title and logo, so editing looks
          like the finished page. The sidebar keeps the view's own name.
        </li>
        <li>
          <UI>Copy link</UI> goes to the same people who get <UI>Share</UI>. <UI>Edit</UI> goes to anyone who may change
          the view's settings and brings the view back into the Command Center, where it stays on reload.
        </li>
        <li>
          A view opened with <UI>Preview</UI> is labelled <UI>Preview</UI> and has <UI>Back to editing</UI> (or{' '}
          <UI>Back to Command Center</UI> for someone who cannot change it), which returns to the same tab. People
          opening the link see neither. A workspace other than Prod is named beside the title.
        </li>
        <li>
          The logo and the tab icon take an upload of up to 256 KB, or an https:// address. Who can open the link is
          unchanged, and opening someone else's personal view on its own still adds it to <UI>Shared Views</UI>.
        </li>
      </List>
    </Details>

    <H3 id="settings-look">Look: colors, font, background and cards</H3>
    <P>
      <UI>Look</UI> styles the whole view, the same on every tab. Type a description such as "dark navy, like a control
      room, rounded cards" beside <UI>Suggest</UI> to have the choices filled in for you, then adjust them. <UI>Undo</UI>{' '}
      puts back what was there. A preview beside the choices shows the result.
    </P>
    <Shot
      name="use-view-settings-look"
      alt="The Look section of View settings with a live preview"
      legend={[
        'The sections of View settings; this is Look.',
        'Describe the look and click Suggest to fill the choices in.',
        'Accent color and Dark color.',
        'Card choices: Corners, Edges, Title and Spacing.',
        'A preview of the result.',
      ]}
    />
    <Table
      head={['Choice', 'What you can set']}
      rows={[
        [<UI>Accent color</UI>, "Replaces Command Center's blue: the selected tab, buttons, links and highlights in widgets. White text sits on it, so it must be dark enough to read."],
        [<UI>Dark color</UI>, "Replaces Command Center's navy: titles, headings, dark buttons and panels in widgets. It must also be dark enough for white text."],
        [<UI>Font</UI>, "Command Center's own, Inter, Manrope, Space Grotesk, Fraunces (serif), IBM Plex Sans or JetBrains Mono (monospace). Only fonts bundled with the app are offered."],
        [<UI>Header</UI>, <>The bar along the top: <UI>White</UI> or <UI>The dark color</UI>. The assistant's header beside it follows, and always lines up with it.</>],
        [<UI>Background</UI>, <>Command Center's light gray, <UI>A color</UI>, <UI>A gradient</UI> (two colors and a direction) or <UI>An image</UI> (<UI>Fill the background</UI> or <UI>Repeat as tiles</UI>; upload up to 256 KB or paste an https:// address).</>],
        [<UI>Cards</UI>, <><UI>Corners</UI> (square to very rounded), <UI>Edges</UI> (flat, outlined or shadowed), <UI>Title</UI> (in a gray bar, in an accent-color or dark-color bar, plain, or <UI>No title</UI>) and <UI>Spacing</UI> (compact or roomy). Each also has a <UI>Standard</UI> choice.</>],
        [<UI>Tabs</UI>, <><UI>Across the top</UI> (the default) or <UI>Down the side</UI>. A view with one tab shows none.</>],
      ]}
    />
    <Details summary="How the look is applied">
      <List>
        <li>
          The background covers everything under the header, tabs and filters included, so the view reads as one
          surface. Cards stay white so widgets stay readable.
        </li>
        <li>
          Text drawn straight on a dark background turns light by itself. The assistant's messages and message box turn
          translucent on a dark background; on a light background or an image they stay white. A chart in a reply keeps
          its white card.
        </li>
        <li>
          With Command Center's light gray background, the tab and filter bars take the header's color too, so the top of
          the view is one block. With a background of your own they sit on it instead.
        </li>
        <li>
          <UI>No title</UI> leaves the card's title off and shows its buttons only when you hover over the card.
        </li>
        <li>
          Inside the Command Center the look covers everything but the sidebar: the header, tabs, filters, background
          and the assistant panel. A view on its own uses it for the whole page. Studios, this guide and the Admin Panel
          keep Command Center's colors.
        </li>
        <li>
          A full page tab draws its own background, so only the colors and the font apply to a view that is one page.
          On a view set to <UI>No header</UI>, <UI>Header</UI> colors the assistant's header and the bars instead, and
          the section says so.
        </li>
        <li>
          Suggest only fills in the fields. Anything the model chose that the app cannot draw is named and left out.
        </li>
      </List>
    </Details>

    <H3 id="settings-filters">Filters: dropdowns for every tab</H3>
    <P>
      Filters add dropdowns above the widgets. Anyone who can see the view can use them.
    </P>
    <Shot
      name="use-view-settings-filters"
      alt="The Filters section of View settings with no filters yet"
      legend={[
        'The sections of View settings; this is Filters.',
        'Add a filter.',
      ]}
    />
    <Steps>
      <Step>In <UI>Settings → Filters</UI>, click <UI>Add a filter</UI>.</Step>
      <Step>
        Enter a <UI>Label</UI> (the name on the dropdown). <UI>Variable</UI> fills in from the label until you edit it.
      </Step>
      <Step>Type the choices under <UI>Options, one per line</UI> and pick which one <UI>Starts on</UI>.</Step>
      <Step><UI>Save</UI>.</Step>
    </Steps>
    <List>
      <li>
        A choice sets that dashboard variable for every widget on every tab. Only widgets written to follow that
        variable change. <UI>All</UI> clears it.
      </li>
      <li>
        Each person comes back to the choices they last made on the view, remembered in their own browser. Another
        browser or computer starts from the defaults.
      </li>
      <li>
        A view can have up to 10 filters and 100 options each. A variable uses letters, digits and underscores and
        cannot start with a digit. A view built from several views keeps their filters.
      </li>
    </List>

    <H3 id="settings-assistant">Assistant: which agent the view opens with</H3>
    <P>
      The <UI>Agent</UI> picker sets which agent the assistant starts with on this view, inside the Command Center and
      on its own. <UI>Whichever agent is open</UI> pins nothing. <UI>No agent</UI> removes the assistant from the view
      everywhere: the assistant button and panel disappear while that view is on screen. This is the same pin as the pin
      button in the assistant panel. Anyone can still switch agents while on the view. See{' '}
      <GuideLink to="assistant" anchor="agents">The assistant</GuideLink>.
    </P>
    <Shot
      name="use-view-settings-assistant"
      alt="The Assistant section of View settings with the Agent picker"
      legend={[
        'The sections of View settings; this is Assistant.',
        'The Agent picker. Whichever agent is open is the default.',
      ]}
    />

    <H2 id="where-next">Where next</H2>
    <Cards cols={3}>
      <Card to="widgets" title="Using widgets">
        Add, arrange, configure and remove widgets.
      </Card>
      <Card to="assistant" title="The assistant">
        Ask about a view and pin an agent to it.
      </Card>
      <Card to="promotion" title="Promoting work">
        Move a global view from Dev to Test to Prod.
      </Card>
    </Cards>
  </>
);

export const section: GuideSection = {
  id: 'views',
  group: 'use',
  title: 'Views & layouts',
  summary: 'Pages of widgets: tabs, settings, filters, locking and sharing.',
  icon: LayoutGrid,
  keywords: 'new view tabs lock unlock share link copy template global shared standalone on its own header look theme filters settings preview',
  Body,
};
