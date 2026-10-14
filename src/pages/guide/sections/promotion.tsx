/* eslint-disable react-refresh/only-export-components -- a section exports its data (`section`) beside its body */
import { Layers } from 'lucide-react';
import type { GuideSection } from '../types';
import {
  Callout, Card, Cards, Details, GuideLink, H2, H3, Lead, List, Needs, OpenLink, P, Shot, Step, Steps, UI,
} from '../kit';

const Body = () => (
  <>
    <Lead>
      Build in Dev, check in Test, then promote to Prod so everyone gets it. Editors promote widgets from Widget Studio;
      Admins promote and retire global views from the Admin Panel.
    </Lead>

    <H2 id="workspaces">Dev, Test and Prod</H2>
    <P>
      Every Command Center app has three <UI>workspaces</UI>: <UI>Dev</UI>, <UI>Test</UI> and <UI>Prod</UI>. Each holds its own widgets,
      views and agents, so work in progress never reaches the people who rely on Prod. Switch with <UI>Workspace</UI> at the top of
      the sidebar. The app reopens on the one you chose last.
    </P>
    <Shot
      name="use-workspace-switcher"
      narrow
      alt="The Workspace switcher showing Dev, Test and Prod"
      caption="The Workspace switcher in the sidebar."
      legend={['The Workspace switcher, shown with Dev, Test and Prod each selected in turn. The chosen workspace is highlighted.']}
    />
    <List>
      <li>
        <strong>Dev and Test need Editor or Admin on a domain.</strong> Without it, those buttons stay disabled and you remain on Prod.
        See <GuideLink to="roles">Roles &amp; permissions</GuideLink>.
      </li>
      <li>
        <strong>A copied link opens the workspace it was copied in.</strong> Send Test links to testers and Prod links to users. Someone without
        access who opens a Dev or Test link sees Prod, and a note says why.
      </li>
      <li>
        <strong>Categories and domains</strong> follow the workspace you are in. Role mappings and settings cover the whole app.
      </li>
    </List>
    <Details summary="Workspace versus the deployed app">
      <P>
        A workspace is not the same as which Command Center was deployed. A company may run a Dev app, a Test app and a Prod app, each its own
        Databricks App with its own database. The browser tab title (for example <em>Command Center - Dev</em>) names
        that deployment, not your workspace.
      </P>
      <P>
        Every deployed app still has all three workspaces. A Dev app is a real development deploy that uses them to try the whole lifecycle. In production, the
        three workspaces are for the people using that app. To move work between deployed apps, use <GuideLink to="migration">Data Migration</GuideLink>.
      </P>
    </Details>

    <H2 id="promote-widget">Promote a widget</H2>
    <P>
      <Needs role="Editor or Admin on the widget's domain" /> Promotion copies the widget&rsquo;s last <em>saved</em> version, and a widget must be published before it can be promoted.
    </P>
    <Steps>
      <Step title="Publish or save the widget in Dev">
        In <GuideLink to="widget-studio">Widget Studio</GuideLink>, click <UI>Publish</UI> for a new widget, or <UI>Save</UI> for one you are editing. Unsaved edits are not promoted.
      </Step>
      <Step title="Open the Promotion panel">
        Click <UI>Promote</UI> (the rocket icon) in the header. The panel shows Dev, Test and Prod, which version each holds, and when it was saved or promoted.
        <Shot
          name="studio-promote"
          alt="The Promotion panel in Widget Studio"
          caption="The Promotion panel, beside the widget you are editing."
          legend={[
            'Promote opens the panel.',
            'Promote to Test copies Dev\u2019s latest saved version into Test.',
            'Promote to Prod copies Test\u2019s version into Prod.',
          ]}
        />
      </Step>
      <Step title="Promote to Test">
        Click <UI>Promote to Test</UI> and confirm. Open the Test workspace and try the widget on a view.
      </Step>
      <Step title="Promote to Prod">
        When Test looks right, click <UI>Promote to Prod</UI>. It copies Test&rsquo;s version, not Dev&rsquo;s.
      </Step>
      <Step title="Certify it in Prod (optional)">
        In the Prod entry, click <UI>Certify</UI>. See <GuideLink to="promotion" anchor="certify">Certify</GuideLink> below.
      </Step>
    </Steps>
    <Details summary="Promote from the Admin Panel instead">
      <P>
        <UI>Admin Panel &rarr; Widget Promotion</UI> does the same for every widget at once. Each row has a version menu under <UI>Dev</UI>,{' '}
        <UI>Test</UI> and <UI>Prod</UI>. Choose a higher version in an environment to promote it there; you are asked to confirm in a{' '}
        <UI>Promote Widget</UI> dialog. Choose a lower one to roll back. <UI>Certify</UI> sits under the Prod menu. If you are not an Editor on the
        widget&rsquo;s domain, you see the versions but get no menus or buttons.
      </P>
      <Shot
        name="admin-widget-promotion"
        alt="Widget Promotion table with a version menu per workspace"
        caption="Admin Panel, Widget Promotion."
        legend={[
          'Backfill missing makes thumbnails for widgets that lack one. The badge counts them.',
          'Regenerate all remakes every thumbnail.',
          'The version in each workspace. Pick a version, or None.',
          'Preview and History, to the right.',
        ]}
      />
    </Details>

    <H2 id="versions">Versions and rollbacks</H2>
    <P>
      Every save in a workspace adds a version, and old versions are kept as an audit trail you can go back to. Each workspace numbers
      its own versions: Dev v8 can arrive in Test as v3. Compare what a version contains, never its number across workspaces.
    </P>
    <P>
      A view can pin a placed widget to one version. That is why promoting a view checks versions (see below).
    </P>

    <H3 id="roll-back">Roll back a widget</H3>
    <P>
      <Needs role="Editor or Admin" /> If a promoted widget misbehaves, open its Promotion panel and pick an older version from that
      workspace&rsquo;s <UI>Roll back to&hellip;</UI> menu. Confirm, and that exact version becomes current again straight away; newer versions are set aside. Nothing changes in the
      other workspaces.
    </P>

    <H2 id="certify">Certify a widget</H2>
    <P>
      <Needs role="Editor or Admin" /> In Prod, <UI>Certify</UI> marks the current version as reviewed and enterprise-ready (the dialog says <em>Enterprise Ready</em>). The
      widget then shows a <UI>Certified</UI> badge and shows when you filter for <UI>Certified</UI> widgets.
    </P>
    <List>
      <li>Certification belongs to one version. When you promote a newer version to Prod, certify that one too.</li>
      <li>It is a signal to people, not a permission, unless an admin turns on <UI>Global views may only contain certified widgets</UI> in <GuideLink to="settings">Settings</GuideLink>. Then a global view can only hold certified widgets, and saving one with others is refused.</li>
    </List>

    <H2 id="promote-view">Promote a view</H2>
    <P>
      <Needs role="Admin (the Admin Panel)" /> Global views are promoted from <OpenLink page="admin">Admin Panel</OpenLink> &rarr; <UI>View Promotion</UI>. A view always
      moves with all of its tabs.
    </P>
    <Steps>
      <Step title="Find the view">
        Open <UI>View Promotion</UI>. Each row shows the domain, when it last changed, the author, and a version menu for Dev, Test and Prod. Use the search box and the domain filter to narrow the list.
      </Step>
      <Step title="Pick a higher version in the target workspace">
        For example, choose Dev&rsquo;s latest in the <UI>Test</UI> menu. A <UI>Promote View</UI> dialog opens and checks what the target already has.
        <Shot
          name="admin-view-promotion"
          alt="The View Promotion table"
          caption="Admin Panel, View Promotion."
          legend={[
            'Create Global View.',
            'Archived lists retired views.',
            'Search views by name.',
            'The table: a column each for Dev, Test and Prod, then Preview, History and Remove.',
          ]}
        />
      </Step>
      <Step title="Read the check, then confirm">
        Resolve or accept anything the check lists (below), then confirm. To go back, pick an older version in the same menu.
      </Step>
    </Steps>
    <Details summary="What the check warns about">
      <P>
        A view and the widgets and agents it uses are separate things in each workspace, so the target may not have them. The dialog lists:
      </P>
      <List>
        <li>
          <strong>Widgets the target does not have.</strong> They will not show there. Leave <UI>Promote them too</UI> ticked to copy each at its
          current version (you need Editor on each widget&rsquo;s domain). Untick it and the view shows without them.
        </li>
        <li><strong>Widgets pinned to a version that differs there.</strong> Either the target has no such version, so the card shows its current one, or that version number is a different widget there.</li>
        <li><strong>Pinned agents the target does not have.</strong> The assistant there cannot open them. Agents cannot be promoted, so recreate the agent in the target workspace or pin another one.</li>
        <li><strong>Widgets that are not certified there,</strong> when global views must hold certified widgets. Saving the view in that workspace is refused until they are certified.</li>
      </List>
      <P>If the check itself cannot run, the dialog says so and still lets you promote.</P>
    </Details>
    <P>
      <UI>Create Global View</UI>, at the top of the screen, makes a new global view in the workspace you are on. It asks for a{' '}
      <UI>View Name</UI> and a <UI>Domain</UI>, and lists only domains you can edit.
    </P>

    <H2 id="retire-view">Remove, restore or delete a global view</H2>
    <P>
      <Needs role="Editor or Admin on the view's domain" /> Retiring a global view takes two steps, so a slip can be undone.
    </P>
    <Steps>
      <Step title="Remove it">
        Click <UI>Remove</UI> on the view&rsquo;s row and confirm. It disappears from everyone&rsquo;s <UI>Global Views</UI> in Dev, Test and Prod. Nothing is deleted and every version is kept.
      </Step>
      <Step title="Restore or delete it">
        Click <UI>Archived</UI> at the top of the screen. <UI>Restore</UI> brings the view back exactly as it was. <UI>Delete permanently</UI> removes every version for good.
      </Step>
    </Steps>
    <Callout kind="warn" title="Delete permanently cannot be undone">
      A global view must be archived before it can be deleted. Personal views are closed from the sidebar instead, which deletes them.
    </Callout>

    <H2 id="where-next">Where next</H2>
    <Cards cols={3}>
      <Card title="Roles & permissions" to="roles">Who can promote, roll back and certify.</Card>
      <Card title="Widget Studio" to="widget-studio">Build and save the widget you will promote.</Card>
      <Card title="Moving data to another app" to="migration">Move everything between deployed apps.</Card>
    </Cards>
  </>
);

export const section: GuideSection = {
  id: 'promotion',
  group: 'admin',
  title: 'Promoting work',
  summary: 'Move widgets and views from Dev to Test to Prod.',
  icon: Layers,
  keywords: 'dev test prod workspace version rollback certify archive restore delete view widget environment release',
  Body,
};
