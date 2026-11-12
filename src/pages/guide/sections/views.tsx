/* eslint-disable react-refresh/only-export-components -- a section exports its data (`section`) beside its body */
import { LayoutGrid } from 'lucide-react';
import type { GuideSection } from '../types';
import { Callout, Card, Cards, Code, Details, GuideLink, H2, H3, Kbd, Lead, List, P, Shot, Step, Steps, Table, UI } from '../kit';

const Body = () => (
  <>
    <Lead>
      A view is a page of widgets that you arrange yourself, on one or more tabs. This page covers making views,
      organizing them with tabs, locking, sharing, publishing your changes, and View settings.
    </Lead>

    <Shot
      name="use-view-header"
      alt="The view header with the state chip, the ⋯ menu, Share and Publish, and the tab bar"
      legend={[
        'The state chip beside the name: Not published yet, Published or Unpublished changes.',
        'The ⋯ menu: the tab\u2019s layout, Add a tab…, View settings…, Lock layout and version history.',
        'Share: opens the share dialog, where you choose who can use or manage the view.',
        'Publish: makes your draft what everyone sees. Shown only when there is something to publish.',
        'The + in the tab bar adds another tab.',
      ]}
    />

    <H2 id="create-a-view">Create and organize views</H2>
    <Steps>
      <Step>
        In the sidebar, click <UI>New view</UI>. A blank view opens. It is a draft that only you can see until you
        share and publish it.
      </Step>
      <Step>
        To rename it, hover it under <UI>My views</UI>, click the pencil, type the new name and press{' '}
        <Kbd>Enter</Kbd>. <Kbd>Esc</Kbd> cancels.
      </Step>
      <Step>
        To keep a view at the top of the sidebar, star it: the star beside its name in the view header, or on its
        sidebar row when you hover it.
      </Step>
    </Steps>
    <H3 id="sidebar">Your views in the sidebar</H3>
    <P>
      The sidebar lists the views you use, not every view you can open. The rest are in <UI>Browse views</UI>, one
      click away. With no link, the app opens the view you opened last.
    </P>
    <List>
      <li>
        <UI>Search views</UI>, at the top, shows matching views as you type. Use <Kbd>↑</Kbd> and <Kbd>↓</Kbd> to pick
        one and <Kbd>Enter</Kbd> to open it, or press <Kbd>Enter</Kbd> straight away to see every match in Browse
        views. With the sidebar collapsed, the magnifying glass opens it at the search box.
      </li>
      <li>
        <UI>Favorites</UI> lists the views you starred, up to 15, in your order; <UI>All favorites</UI> shows the rest.
        Drag one to move it, or select it and press <Kbd>Alt</Kbd>+<Kbd>↑</Kbd> or <Kbd>Alt</Kbd>+<Kbd>↓</Kbd>. A view
        that has never been published can&rsquo;t be starred yet.
      </li>
      <li>
        <UI>Recent</UI> lists the last five views you opened that aren&rsquo;t favorites. Hover one and click its{' '}
        <UI>×</UI> to take it off Recent. It is still shared with you, and opening it again brings it back.
      </li>
      <li>
        <UI>My views</UI> lists the eight views you own that changed last; <UI>All my views</UI> shows every one. Hover
        one and click its <UI>×</UI> to close it. You are asked first. A view only you can open is then deleted, and a
        view shared with anyone else is archived instead.
      </li>
      <li>
        <UI>New for you</UI>, when it appears, counts views shared with you lately and shows them in Browse views.
      </li>
      <li>
        <UI>Browse views</UI> finds every view shared with you. A view someone else made opens as they last published
        it; <UI>Make a copy</UI> in its <UI>⋯</UI> menu gives you a copy of your own under My views.
      </li>
      <li>
        <UI>Archived</UI>, collapsed at the bottom, lists archived views you manage, each with <UI>Restore</UI> and{' '}
        <UI>Delete permanently</UI>. See <GuideLink to="publishing" anchor="archive">Archive, restore or delete a view</GuideLink>.
      </li>
    </List>
    <P>
      An icon beside each view says who it is shared with: a lock for only the people on its list (often just you),
      people for particular people or groups, and a globe for everyone in this app. On a view you manage, a small dot
      means it has changes nobody else sees yet. The dot is grey when the view has never been published and amber when
      it has unpublished changes.
    </P>
    <Callout kind="admin" title="Administrators and the sidebar">
      Administrators can manage every view, but their sidebar lists only the views they own or that are shared with
      them. <UI>Admin Panel → Content</UI> lists every view, and an Administrator can open any view by its link.
    </Callout>

    <H2 id="header">The view header</H2>
    <P>
      On a view you manage, a chip beside its name says where it stands: <UI>Not published yet</UI>,{' '}
      <UI>Published</UI> or <UI>Unpublished changes</UI>. Hover it to see what that means. On the right, in this order:
    </P>
    <List>
      <li>
        <UI>Draft</UI> / <UI>Published</UI>, only when the view has unpublished changes, or while you are looking at
        Published so you can get back. See <GuideLink to="publishing" anchor="draft-and-published">The draft and the published version</GuideLink>.
      </li>
      <li>The <UI>⋯</UI> menu, described below.</li>
      <li><UI>Share</UI>, for everyone who can open the view.</li>
      <li>
        <UI>Publish</UI>, the last and only filled button. It appears only when there is something to publish, so on a
        view with no unpublished changes it isn&rsquo;t there at all.
      </li>
    </List>
    <P>The <UI>⋯</UI> menu (<UI>More view options</UI>) holds what you need now and then, in three groups:</P>
    <Table
      head={['Group', 'Items']}
      rows={[
        [<UI key="l">Layout</UI>, <><UI>Cards on a grid</UI> or <UI>Full page</UI>, with a check against the current one, and <UI>Add a tab…</UI> on a view with one tab. Called <UI>This tab</UI> when the view has several tabs, because the choice applies to the tab you are on.</>],
        [<UI key="v">View</UI>, <><UI>Preview as a viewer</UI> on a view that opens on its own, <UI>View settings…</UI>, and <UI>Lock layout</UI> or <UI>Unlock layout</UI>.</>],
        [<UI key="h">Versions</UI>, <><UI>Version history…</UI> once the view has been published, and <UI>Discard draft…</UI> when it has unpublished changes. Only for people who can manage the view.</>],
      ]}
    />
    <P>
      On a view you can only use, the header shows <UI>Share</UI> and the <UI>⋯</UI> menu only when it has something
      for you, such as <UI>Preview as a viewer</UI>.
    </P>

    <H2 id="tabs">Add and manage tabs</H2>
    <P>
      Tabs split a view into separate canvases, for example one per team or topic. Widgets you add go on the tab you
      are looking at. Filters you set apply on every tab of the view.
    </P>
    <Steps>
      <Step title="Add the second tab">
        Open the <UI>⋯</UI> menu in the top right and choose <UI>Add a tab…</UI>. Choose <UI>Cards on a grid</UI> or{' '}
        <UI>Full page</UI>, then name the new
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
      alt="The Add a tab menu offering Cards on a grid and Full page"
      legend={[
        'Add a tab…, in the ⋯ menu at the top right of the view.',
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
      Whoever can manage a view may change its tabs, in its draft. That is not possible while the view is locked, and
      people who can only use the view see it read-only.
    </Callout>

    <H3 id="cards-or-page">Cards on a grid or a full page</H3>
    <P>
      Each tab is one of two kinds. <UI>Cards on a grid</UI> holds several widgets, each in its own card that you can
      move and resize. <UI>Full page</UI> holds one widget that fills the whole tab with no card around it, which suits a
      landing page or a hub. A view can mix them in any order.
    </P>
    <List>
      <li>
        <UI>Add a tab…</UI> and the <UI>+</UI> ask which kind a new tab should be.
      </li>
      <li>
        To switch the tab you are looking at, open the <UI>⋯</UI> menu and pick <UI>Cards on a grid</UI> or{' '}
        <UI>Full page</UI>; the current one has a check. The choice is there whenever you may change the view's tabs,
        including on a view with only one tab. <UI>Full page</UI> can&rsquo;t be picked on a grid holding more than one
        widget; hover it to see why, and remove all but one widget first.
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
        people who can manage the widget, a gear for the widget's settings, and a bin to take the widget off the page.
        The gear is grayed out when the widget was built without settings. A view opened on its own shows the page
        without the toolbar. Any widget can go on a page, but one built as a page in Widget Studio, marked{' '}
        <UI>PAGE</UI> in the library, is made to fill it.
      </P>
    </Details>

    <H2 id="lock-and-unlock">Lock and unlock a view</H2>
    <P>
      Once the layout is how you want it, open the <UI>⋯</UI> menu and choose <UI>Lock layout</UI>. It stops widgets
      being moved, resized or removed by accident, and tabs can&rsquo;t be changed either. The menu item then reads{' '}
      <UI>Unlock layout</UI>; choose it when you want to change things again. The Widget Library tells you the view is
      locked instead of adding widgets.
    </P>
    <Shot
      name="use-lock"
      alt="A widget card before and after the view's layout is locked"
      legend={[
        'Unlocked (above) and locked (below). A locked card loses its grip, version box and remove button, and the + for new tabs goes.',
      ]}
    />
    <P>
      <UI>Lock layout</UI>, <UI>View settings…</UI>, the state chip and <UI>Publish</UI> are for people who can manage
      the view. On views you can only use, they are not shown and the view is read-only. <UI>Share</UI> is there for
      everyone who can open the view. It shows who has access and copies the link, and only people who can manage the
      view can change the list.
    </P>
    <P>
      A widget on the view that has never been published shows a <UI>Not published yet</UI> card, in its place, to people
      who can only use the view.
    </P>

    <H2 id="share-a-view">Share a view</H2>
    <Steps>
      <Step>Open the view and click <UI>Share</UI> in the top right.</Step>
      <Step>
        Add the people or groups who should see it, as <UI>Can use</UI> or <UI>Can manage</UI>, or choose{' '}
        <UI>Everyone in this app can use</UI>. Changes save straight away. See{' '}
        <GuideLink to="sharing" anchor="share">Share something</GuideLink>.
      </Step>
      <Step>
        Publish the view if you haven&rsquo;t, so there is something for them to see. See{' '}
        <GuideLink to="publishing">Drafts &amp; publishing</GuideLink>.
      </Step>
      <Step>
        Click <UI>Copy link</UI> in the dialog and send it. It opens the view set the way you have it now, filters
        included. The people you shared it with also find it in <UI>Browse views</UI> and under{' '}
        <UI>New for you</UI>.
      </Step>
    </Steps>
    <Callout kind="note" title="A link opens only for people the view is shared with">
      Anyone else is told the view isn&rsquo;t there, and so is everyone while the view is archived. Inside the Command
      Center, people who can manage the view see its draft and people who can use it see the latest published version.
      A view set to open on its own always shows the published version there, read-only, even to its managers. Everyone
      who could open a view before sharing was introduced still can.
    </Callout>
    <H3 id="link-settings">A link keeps what the view is set to</H3>
    <P>
      The address follows the view&rsquo;s filters, the values widgets pass to each other, and the settings a widget
      keeps in the link, such as a sort, a search or a date range. A reload, Back, or a link you copy and send all
      open the view set the same way. Switching tabs keeps them; opening another view starts it without them.
    </P>
    <H3 id="publish-a-view">Your changes are a draft until you publish</H3>
    <P>
      Moving widgets, changing tabs, View settings and the assistant pin all change the view&rsquo;s draft. The chip
      beside the view&rsquo;s name shows <UI>Not published yet</UI>, <UI>Published</UI> or{' '}
      <UI>Unpublished changes</UI>, and <UI>Publish</UI> makes your draft what everyone sees. In the <UI>⋯</UI> menu,{' '}
      <UI>Version history…</UI> appears once the view has been published, and <UI>Discard draft…</UI> when it has
      unpublished changes. A view that has never been published can&rsquo;t be discarded; delete it instead.
      Publishing a view checks the widgets on it; see{' '}
      <GuideLink to="publishing" anchor="publish-a-view">Publishing a view checks what is on it</GuideLink>.
    </P>
    <Details summary="How links are written">
      <P>
        Links use names, not codes. A published view's link is its name, for example{' '}
        <Code>#/app/supply-hub/inventory</Code> for the Inventory tab of the Supply Hub view. A second view with the
        same name gets <Code>supply-hub-2</Code>. If a view is renamed, it takes the new name when it is next published,
        and links to its old name keep working.
      </P>
      <P>
        A view that has never been published is linked by its name followed by a code. A tab is named by its own name
        unless two tabs share one. After a tab is
        renamed, an old link to it opens the first tab. A link to the first tab leaves the tab out and opens whichever
        tab is first. Links from earlier releases still work.
      </P>
      <P>
        What the view is set to sits before the <Code>#</Code>, as in{' '}
        <Code>{'?v.region=West&w.3f2a91c0.sort=revenue'}</Code>. A setting still at its default is left out, and if
        the settings would make a link longer than about 1,500 characters, the largest are left out of it. A link
        that carries settings opens with exactly those, not the filter choices you last left the view on; a filter
        option the view no longer offers falls back to its default.
      </P>
      <P>
        The share icon on a single widget copies a different link: one that opens that widget full screen, with the
        view&rsquo;s filters and that widget&rsquo;s own settings. See{' '}
        <GuideLink to="widgets" anchor="full-screen">Using widgets</GuideLink>.
      </P>
    </Details>

    <H2 id="view-settings">View settings</H2>
    <P>
      Open the <UI>⋯</UI> menu in the header and choose <UI>View settings…</UI>. It has four sections down its left side:{' '}
      <UI>Opening</UI>, <UI>Look</UI>, <UI>Filters</UI> and <UI>Assistant</UI>. Hover the <UI>?</UI> beside any field
      for a short explanation. A red dot marks a section with something to fix; the footer names it, and{' '}
      <UI>Save</UI> stays off until you do. Nothing is stored until you press <UI>Save</UI>, and <UI>Save</UI> writes the
      view&rsquo;s draft: other people see the new settings once you publish.
    </P>
    <Callout kind="admin" title="Who can open View settings">
      Anyone who can manage the view. It is not offered to people who can only use it.
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
      <Step>Open <UI>View settings… → Opening</UI> and choose <UI>On its own</UI>.</Step>
      <Step>
        Fill in <UI>Title</UI>, <UI>Logo</UI> and <UI>Browser tab icon</UI>. These fields appear only once{' '}
        <UI>On its own</UI> is chosen. The title falls back to the view's name.
      </Step>
      <Step><UI>Save</UI>, then choose <UI>Preview as a viewer</UI> in the <UI>⋯</UI> menu to see it as other people will.</Step>
      <Step>Publish the view, then share its link. It opens only that view, read-only, under your title and logo.</Step>
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
          The view is read-only for everyone, including its owner, and always shows the latest published version; its
          tabs can be switched but not changed. The assistant appears too, unless the view's agent is <UI>No agent</UI>.
        </li>
        <li>
          <UI>Header</UI>: <UI>Show the header</UI> or <UI>No header: the page has its own</UI>. Choose the second when
          the view's page draws its own title bar. The view then starts straight with its tabs or page, the logo field
          goes away, and the title is used only on the browser tab.
        </li>
        <li>
          With <UI>No header</UI>, <UI>Share</UI>, <UI>Edit</UI> (or <UI>Back to editing</UI> in a preview) sit in a small bar at the bottom left, shown only to people who get at least one of them.
          Inside the Command Center, the view's controls (the state chip, <UI>Draft</UI> / <UI>Published</UI>, the{' '}
          <UI>⋯</UI> menu, <UI>Share</UI> and <UI>Publish</UI>) move to that bar too.
        </li>
        <li>
          While you edit the view inside the Command Center, its header shows the same title and logo, so editing looks
          like the finished page. The sidebar keeps the view's own name.
        </li>
        <li>
          <UI>Share</UI> goes to everyone who can open the view: it shows who has access and copies the link.{' '}
          <UI>Edit</UI> goes to anyone who can manage the view and brings the view back into the Command Center, where it
          stays on reload.
        </li>
        <li>
          A view opened with <UI>Preview as a viewer</UI> is labelled <UI>Preview</UI> and has <UI>Back to editing</UI> (or{' '}
          <UI>Back to Command Center</UI> for someone who cannot change it), which returns to the same tab. People
          opening the link see neither.
        </li>
        <li>
          The logo and the tab icon take an upload of up to 256 KB, or an https:// address. The link opens only for
          people the view is shared with.
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
        browser or computer starts from the defaults. A link that carries filter choices opens on those instead, and
        the address follows each choice, so a link you copy shares them.
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
      <Card to="sharing" title="Sharing & permissions">
        Choose who can use or manage your view.
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
  keywords: 'new view tabs lock unlock layout share link shared with me archived draft publish standalone on its own header more options menu look theme filters settings preview version history discard address url reload back saved in the link',
  Body,
};
