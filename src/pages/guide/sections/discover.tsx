/* eslint-disable react-refresh/only-export-components -- a section exports its data (`section`) beside its body */
import { Compass } from 'lucide-react';
import type { GuideSection } from '../types';
import { Callout, Card, Cards, GuideLink, H2, H3, Lead, List, P, Table, UI } from '../kit';

const Body = () => (
  <>
    <Lead>
      Discover finds any view you can open. The sidebar keeps the few you use; Discover is where you look for the rest, by searching or browsing
      what other people use and what your administrators recommend.
    </Lead>
    <P>
      Open it with <UI>Browse views</UI> in the sidebar, or type in the sidebar&rsquo;s search box and press <UI>Enter</UI>. The address keeps
      what you searched for and every filter, so Back, a reload or a copied link opens Discover exactly as you left it.
    </P>

    <H2 id="search">Search</H2>
    <P>
      Type in the box at the top. Up to eight views are suggested as you type; pick one to open it, or press <UI>Enter</UI> to see every match.
      Search reads each view&rsquo;s name, description, tab names, owner, domain and widget names, and names count most.
    </P>
    <P>The chips under the box choose which views to search:</P>
    <Table
      head={['Chip', 'Searches']}
      rows={[
        [<UI key="a">All I can open</UI>, 'Every published view shared with you, your groups or everyone, plus your own.'],
        [<UI key="m">Mine</UI>, 'Views you own. Only published ones: a view you haven’t published yet is under My views in the sidebar.'],
        [<UI key="s">Shared with me</UI>, 'Views someone else owns that you can open.'],
        [<UI key="f">Favorites</UI>, 'Views you starred.'],
        [<UI key="e">Everything in this deployment</UI>, 'Administrators only: every view, whoever it is shared with.'],
      ]}
    />

    <H3 id="search-modes">Why results say &ldquo;keyword&rdquo; or &ldquo;word&rdquo; matches</H3>
    <P>
      When your administrators have turned on hybrid search, a search also finds views by meaning, so &ldquo;late shipments&rdquo; finds
      &ldquo;Delayed deliveries&rdquo;. A line above the results says when a search was answered with matches for the words typed instead:
    </P>
    <List>
      <li>The app doesn&rsquo;t search by meaning yet. Administrators can <GuideLink to="settings" anchor="hybrid-search">turn on hybrid search</GuideLink>.</li>
      <li>You sorted by something other than <UI>Relevance</UI>. Other sorts list the views that contain your words, in that order.</li>
      <li>Matching by meaning took too long that time. Searching again usually helps.</li>
    </List>
    <P>
      Results sorted by relevance stop at the 500 best matches, and the count says <UI>Top 500 matches</UI>. Add a word or a filter to narrow it
      down. Right after the app is deployed, a blue <UI>Indexing views…</UI> banner shows while it reads every view; whatever it has read can
      already be found.
    </P>

    <H2 id="rails">Browse the rails</H2>
    <P>With nothing typed, Discover shows rows of views, each with a <UI>See all</UI> link. Empty rows are left out.</P>
    <Table
      head={['Rail', 'What is in it']}
      rows={[
        [<UI key="f">Featured</UI>, 'Views your administrators picked, in the order they chose.'],
        [<UI key="c">Certified</UI>, 'Views your administrators checked and vouch for, most viewed first.'],
        [<UI key="p">Popular this month</UI>, 'Opened by the most people in the last 30 days.'],
        [<UI key="t">Trending</UI>, 'Gaining viewers this week compared with before.'],
        [<UI key="u">Recently updated</UI>, 'Published most recently.'],
        [<UI key="n">New for you</UI>, 'Shared with you or your groups in the last 14 days that you haven’t opened yet.'],
      ]}
    />
    <P>
      <UI>Featured</UI> and <UI>New for you</UI> show at most 12 views even on their own; search finds any other view.
    </P>

    <H2 id="filters">Sort and filter results</H2>
    <P>
      Beside the results (under <UI>Filters</UI> on a narrow screen), tick one or more <UI>Domain</UI> or <UI>Owner</UI> values; each shows how
      many results it has. The other filters:
    </P>
    <List>
      <li><strong><UI>Certified</UI></strong>: only certified views, or only ones that aren&rsquo;t.</li>
      <li><strong><UI>Opens</UI></strong>: views that open in the workspace with the sidebar, or on their own page.</li>
      <li><strong><UI>Last opened</UI></strong>: views nobody has ever opened, or nobody has opened in 90 days. This counts everyone&rsquo;s opens, not just yours.</li>
      <li><strong><UI>Status</UI></strong>: shown once you manage a view. Picks views with unpublished changes, or without, among the views you manage.</li>
    </List>
    <P>
      <UI>Sort</UI> offers <UI>Relevance</UI> (when you&rsquo;ve typed something), <UI>Popular</UI>, <UI>Trending</UI>,{' '}
      <UI>Recently updated</UI>, <UI>Name</UI> and <UI>Most favorited</UI>. The two buttons beside it switch between cards and a list, and
      Discover remembers your choice. More results load as you scroll.
    </P>

    <H2 id="cards">What a card shows</H2>
    <P>
      Each view shows its name, owner and domain, when it was last updated, how many people opened it in the last 30 days, and how many starred
      it (that count catches up within about 15 minutes). A pencil means you can manage it, an eye that you can use it. Badges mark{' '}
      <UI>Featured</UI> and <UI>Certified</UI> views, and the same dot as in the sidebar marks a view of yours with unpublished changes.
    </P>
    <List>
      <li>Click a card to open the view. Hold <UI>Ctrl</UI> or <UI>⌘</UI> to open it in a new tab.</li>
      <li>The star adds it to your favorites, which also puts it at the top of your sidebar. Press it again to remove it.</li>
      <li>
        The <UI>⋯</UI> menu&rsquo;s <UI>Hide from rails</UI> takes a view you don&rsquo;t want recommended out of the rails, for you only.
        Search still finds it, marked <UI>Hidden</UI>, and <UI>Unhide</UI> brings it back. If you manage the view, the menu also has{' '}
        <UI>Share…</UI>.
      </li>
    </List>

    <H2 id="curate">For administrators: feature, certify and review</H2>
    <P>An administrator&rsquo;s <UI>⋯</UI> menu on every card adds:</P>
    <List>
      <li>
        <strong><UI>Feature</UI></strong> puts the view on the <UI>Featured</UI> rail for everyone who can open it, after the ones already there.{' '}
        <UI>Unfeature</UI> takes it off.
      </li>
      <li>
        <strong><UI>Certify</UI></strong> marks it as checked and trustworthy: a green badge everywhere it&rsquo;s listed, and a place on the{' '}
        <UI>Certified</UI> rail. <UI>Uncertify</UI> removes it.
      </li>
      <li><strong><UI>Share…</UI></strong> opens the same dialog as <UI>Share</UI> on the view itself.</li>
    </List>
    <P>
      Neither changes who can open a view: featuring a view nobody has been given access to shows it to nobody.
    </P>
    <Callout kind="admin" title="Find views to archive">
      The amber <UI>Not opened in 90 days</UI> chip lists every view in this deployment that nobody has opened for 90 days, or ever, by name. Its
      owner is on each card, so you can ask whether it is still needed. Archiving keeps every version, and <UI>Restore</UI> brings it back.
    </Callout>

    <H2 id="where-next">Where next</H2>
    <Cards cols={3}>
      <Card to="views" title="Using views">Tabs, filters and the sidebar.</Card>
      <Card to="sharing" title="Sharing">Give people access to a view.</Card>
      <Card to="settings" anchor="hybrid-search" title="Turn on hybrid search">Let search find views by meaning.</Card>
    </Cards>
  </>
);

export const section: GuideSection = {
  id: 'discover',
  group: 'use',
  title: 'Finding views',
  summary: 'Search every view you can open, browse what’s popular and recommended, and star your favorites.',
  icon: Compass,
  keywords: 'discover find search browse views catalog rails featured certified popular trending recently updated new for you favorites star hide unhide scope mine shared everything filter domain owner sort relevance grid list keyword hybrid meaning semantic indexing 500 archive governance not opened 90 days curate feature certify',
  Body,
};
