/* eslint-disable react-refresh/only-export-components -- a section exports its data (`section`) beside its body */
import { Upload } from 'lucide-react';
import type { GuideSection } from '../types';
import {
  Callout, Card, Cards, Details, GuideLink, H2, Lead, List, Needs, P, Step, Steps, Table, UI,
} from '../kit';

const Body = () => (
  <>
    <Lead>
      Views, widgets and agents each have a draft that you work on and published versions that everyone else sees. Saving
      changes the draft; publishing is how your changes reach the people you shared with.
    </Lead>

    <H2 id="draft-and-published">The draft and the published version</H2>
    <P>
      The <UI>draft</UI> is your working copy. Only people who can manage something see its draft, and every change they
      make, from dragging a widget to clicking <UI>Save draft</UI> in Widget Studio, updates it in place. People with{' '}
      <UI>Can use</UI> always see the latest <UI>published</UI> version, so nothing you are halfway through reaches them.
    </P>
    <P>
      Wherever you can manage something, a chip shows where it stands: beside the name on a view, and in the bar under
      the header in Widget Studio and Agent Studio. Hover it to see what it means.
    </P>
    <Table
      head={['Chip', 'What it means']}
      rows={[
        [<UI key="n">Not published yet</UI>, 'Only the people who can manage it can see it, even if it is shared with others.'],
        [<UI key="u">Published</UI>, 'People it is shared with see exactly what you see. There is nothing to publish, so Publish isn\u2019t shown.'],
        [<UI key="c">Unpublished changes</UI>, 'You have changed something since the last publish. People with Can use still see the last published version.'],
      ]}
    />
    <P>
      When there are unpublished changes, a <UI>Draft</UI> / <UI>Published</UI> switch appears beside the chip. It lets
      you look at the published version, exactly as people with Can use see it, and then switch back to your draft.
      Otherwise the two are the same and the switch isn&rsquo;t shown, except while you are on Published, so you can get
      back.
    </P>

    <H2 id="publish">Publish</H2>
    <P>
      <Needs role="Can manage" /> Click <UI>Publish</UI>: the last, filled button in a view&rsquo;s header, or in the bar
      under the header in the studios. The draft becomes the next published version, and people with Can use see it
      straight away. <UI>Publish</UI> appears only when there is something to publish; when everything is published it
      is hidden rather than greyed out.
    </P>
    <Callout kind="tip" title="Saved, but nobody else sees the change?">
      Saving only changes the draft. Publish to make the change reach people, and check under <UI>Share</UI> that it is
      shared with them at all. See <GuideLink to="sharing">Sharing &amp; permissions</GuideLink>.
    </Callout>

    <H2 id="publish-a-view">Publishing a view checks what is on it</H2>
    <P>
      A view shows each widget at its latest published version, so a widget you have only saved would not show to the
      people using the view. When you publish a view, the Publish dialog lists:
    </P>
    <List>
      <li><strong>Widgets on the view that have never been published</strong>, which show &ldquo;Not published yet&rdquo; to people using the view.</li>
      <li><strong>Widgets with unpublished changes</strong>, which people would see without those changes.</li>
      <li><strong>The pinned agent</strong>, if it is in either state.</li>
      <li>
        <strong>Widgets that aren&rsquo;t certified</strong>, when an Administrator has turned on{' '}
        <UI>Shared views may only contain certified widgets</UI> and the view is shared with anyone besides you. The view
        can&rsquo;t be published until they are certified.
      </li>
    </List>
    <P>
      The dialog offers to publish the unpublished ones together with the view. Anything you can&rsquo;t manage is named so
      you can ask whoever does.
    </P>
    <Callout kind="note" title="Share the pinned agent too">
      Using a view doesn&rsquo;t give anyone use of the agent pinned to it. Share the agent with the same people as the view.
    </Callout>

    <H2 id="history">History, Revert and Discard draft</H2>
    <List>
      <li>
        <strong>History</strong> lists the published versions, who published each and when. Nothing published is ever
        overwritten. On a view it is <UI>Version history…</UI> in the <UI>⋯</UI> menu, for people who can manage the
        view; in Widget Studio it is <UI>History</UI> in the header, and in Agent Studio it is in the bar under the header.
      </li>
      <li>
        <strong>Revert</strong> copies an older version into the draft. Publish it to make it live again, or keep editing
        first.
      </li>
      <li>
        <strong>Discard draft</strong> throws away every unpublished change and goes back to the latest published version.
        You are asked to confirm. It is offered only when there are unpublished changes: on a view it is{' '}
        <UI>Discard draft…</UI> in the <UI>⋯</UI> menu, and in the studios it is in the bar under the header. Something
        never published has nothing to go back to, so it can&rsquo;t be discarded; delete it instead.
      </li>
      <li>
        <strong>Publishing a widget checks it again.</strong> The safety check that runs when you save a draft runs again
        when you publish.
      </li>
    </List>

    <H2 id="certify">Certify a widget</H2>
    <P>
      <Needs role="Can manage on the widget" /> Certifying marks a published version of a widget as reviewed and ready for
      wide use. Open the widget in Widget Studio and click <UI>Certify</UI> in the bar under the tabs; it applies to the
      latest published version, and clicking <UI>Certified</UI> takes it back. The widget then shows a{' '}
      <UI>Certified</UI> badge, and appears when people filter the Widget Library for <UI>Certified</UI> widgets.
    </P>
    <List>
      <li>Certification belongs to one version. Each new version starts uncertified, because it is a review of that code.</li>
      <li>
        It is a signal to people, not a permission, unless an Administrator turns on{' '}
        <UI>Shared views may only contain certified widgets</UI> in <GuideLink to="settings">Settings</GuideLink>. Then a
        view shared with anyone besides its owner can only be published while every widget on it is certified.
      </li>
    </List>

    <H2 id="archive">Archive, restore or delete a view</H2>
    <Steps>
      <Step title="Archive it">
        <Needs role="Can manage" /> Archiving takes the view out of everyone&rsquo;s sidebar and stops its link opening.
        Nothing is deleted and every version is kept. Closing your own shared view with the <UI>×</UI> in the sidebar
        archives it, after you confirm.
      </Step>
      <Step title="Restore or delete it">
        Archived views you manage are listed under <UI>Archived</UI> at the bottom of the sidebar. <UI>Restore</UI> brings
        one back exactly as it was. <UI>Delete permanently</UI> removes every version for good.
      </Step>
    </Steps>
    <Callout kind="warn" title="Delete permanently cannot be undone">
      A view shared with anyone besides you must be archived before it can be deleted, so people can notice it gone
      first. A private view is deleted straight away when you close it, after you confirm.
    </Callout>

    <H2 id="dev-and-test">Where did Dev and Test go?</H2>
    <P>
      Earlier releases had a <UI>Workspace</UI> switcher with Dev, Test and Prod inside one app, and work was promoted from one
      to the next. Drafts replace that. During the upgrade:
    </P>
    <List>
      <li>Everything that was in Prod became the published version.</li>
      <li>Newer work in Dev (or in Test, if it wasn&rsquo;t in Dev) became its draft, ready for its managers to review and publish.</li>
      <li>Work that only ever existed in Dev or Test became a draft that has never been published.</li>
      <li>Old links that named a workspace still open.</li>
      <li>Widget Studio work that was never saved before the upgrade isn&rsquo;t restored when the studio next opens.</li>
    </List>
    <Details summary="Separate deployments still exist">
      <P>
        A company may still run a development app, a stage app and a production app, each its own Databricks App with its
        own database. The browser tab title (for example <em>Command Center - Dev</em>) names that deployment. To move
        work between deployed apps, use <GuideLink to="migration">Data Migration</GuideLink>.
      </P>
    </Details>

    <H2 id="where-next">Where next</H2>
    <Cards cols={3}>
      <Card title="Sharing & permissions" to="sharing">Who sees the published version.</Card>
      <Card title="Widget Studio" to="widget-studio">Build, save and publish a widget.</Card>
      <Card title="Moving data to another app" to="migration">Move everything between deployed apps.</Card>
    </Cards>
  </>
);

export const section: GuideSection = {
  id: 'publishing',
  group: 'build',
  title: 'Drafts & publishing',
  summary: 'Save drafts, publish versions, revert, and certify.',
  icon: Upload,
  keywords: 'draft publish published version history revert discard certify archive restore delete dev test prod workspace promote promotion release',
  Body,
};
