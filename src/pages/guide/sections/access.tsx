/* eslint-disable react-refresh/only-export-components -- a section exports its data (`section`) beside its body */
import { Users } from 'lucide-react';
import type { GuideSection } from '../types';
import {
  Callout, Card, Cards, Code, Details, GuideLink, H2, Lead, List, Needs, OpenLink, P, Step, Steps, UI,
} from '../kit';

const Body = () => (
  <>
    <Lead>
      How to get access to something you can&rsquo;t open, and how Administrators look after the whole app: who is an
      Administrator, and what to do with content nobody else can reach.
    </Lead>

    <H2 id="ask">Ask for access</H2>
    <P>
      Views, widgets and agents are shared one at a time by the people who manage them, so ask the owner, or anyone who can
      manage it, to share it with you or with a Databricks group you belong to. An Administrator can share anything.
    </P>
    <List>
      <li>
        <strong>A link that says the item isn&rsquo;t there</strong> may simply not be shared with you. The app answers the
        same way for both, so that a link never reveals what exists. Ask the person who sent it.
      </li>
      <li>
        <strong>Shared with you, but you still can&rsquo;t see it?</strong> It may never have been published. Ask its owner
        to publish it.
      </li>
      <li>
        <strong>Shared with a group you&rsquo;re in, but it doesn&rsquo;t work?</strong> The group name on the access list must
        match the Databricks group exactly, capitals included. After you are added to a group, allow a few minutes and reload.
      </li>
      <li>
        <strong>It opens, but its data is empty or refused?</strong> That is Unity Catalog, not this app. Data access is
        granted in Databricks.
      </li>
    </List>

    <H2 id="administrators">Administrators</H2>
    <P>
      <Needs role="Administrator" /> Administrators can manage every view, widget and agent in the app, and are the only people
      who see the <UI>Admin Panel</UI>. Open it from <UI>Resources</UI> at the bottom of the sidebar, or use{' '}
      <OpenLink page="admin">this link</OpenLink>. Its tabs are <UI>Content</UI>, <UI>Categories &amp; Domains</UI>,{' '}
      <UI>Administrators</UI>, <UI>Settings</UI>, <UI>Data Migration</UI> and <UI>Action Logs</UI>, and all of them cover the
      whole app.
    </P>
    <Steps>
      <Step title="Open Administrators">
        In the Admin Panel, open the <UI>Administrators</UI> tab. It lists every person and group who is an Administrator.
      </Step>
      <Step title="Add a person or group">
        Type a Databricks username or group name. Suggestions work as they do in the share dialog, and a name the app hasn&rsquo;t
        seen is accepted if it matches Databricks exactly.
      </Step>
      <Step title="Remove one">
        Remove an entry from the list. The last Administrator can&rsquo;t be removed, so add another first.
      </Step>
    </Steps>
    <Callout kind="warn" title="Keep the list small">
      Administrators can change anything in the app, including who else is an Administrator. Name a small group, not a
      company-wide one; <UI>Everyone in this app</UI> can&rsquo;t be made one. If nobody was an admin before the upgrade to
      sharing, the upgrade made the Databricks group named <Code>users</Code>, essentially everyone, an Administrator so
      that someone could get in. Replace it with your real admin group.
    </Callout>
    <Details summary="Running the app locally">
      <P>
        When the app runs on your own machine with <Code>DEV_MODE=true</Code>, you are an Administrator without being on the
        list. This is for developers; a deployed app does not use it.
      </P>
    </Details>

    <H2 id="content">Find and reassign content</H2>
    <P>
      <Needs role="Administrator" /> The <UI>Content</UI> tab lists every view, widget and agent in the app, whoever owns it,
      with its owner, whether it is published or has unpublished changes, and how widely it is shared. Use it to find
      something nobody else can reach any more, for example after its owner has left, and share it with someone who should
      manage it.
    </P>

    <H2 id="domains">Categories and domains</H2>
    <P>
      <Needs role="Administrator" /> Under <UI>Categories &amp; Domains</UI>, type a name and click <UI>Add Category</UI> or{' '}
      <UI>Add Domain</UI>. Categories group widgets by function, and domains label views, widgets and agents with a
      business area. Both are only for finding things; neither decides who gets in. A name that differs from an existing
      one only in capitals or spacing is refused.
    </P>

    <H2 id="migration-report">After the upgrade to sharing</H2>
    <P>
      When the app moved to sharing and drafts, it did two things once: it turned the old domain role mappings into access
      lists and Administrators, so that everyone who could open something could still open it, and it turned work from the
      old Dev and Test workspaces into drafts. A notice at the top of the Admin Panel reports how that went.{' '}
      <UI>View details</UI> lists who gained or lost access and anything it couldn&rsquo;t carry over. Check the{' '}
      <UI>Administrators</UI> list afterwards: whoever was a Global admin is now an Administrator.
    </P>
    <Callout kind="warn" title="If the notice says the move didn't finish">
      The move runs only once, and restarting the app does not run it again. Open <UI>View details</UI> and click{' '}
      <UI>Retry</UI> to run the part that failed. Anything already moved is left as it is.
    </Callout>
    <P>
      How each old mapping became access is described in{' '}
      <GuideLink to="sharing" anchor="who-can">Sharing &amp; permissions</GuideLink>, under &ldquo;What happened to Viewer,
      Editor and Admin on a domain&rdquo;.
    </P>

    <H2 id="where-next">Where next</H2>
    <Cards cols={2}>
      <Card title="Sharing & permissions" to="sharing">Can use, Can manage, and the share dialog.</Card>
      <Card title="Settings & models" to="settings">Choose models and limit what the assistant can reach.</Card>
    </Cards>
    <P>
      More symptoms and fixes are on <GuideLink to="troubleshooting">Troubleshooting</GuideLink>.
    </P>
  </>
);

export const section: GuideSection = {
  id: 'access',
  group: 'admin',
  title: 'Administrators & access',
  summary: 'Ask for access, manage Administrators, and find content.',
  icon: Users,
  keywords: 'access request administrator admin panel content owner group sign in permission domain category migration',
  Body,
};
