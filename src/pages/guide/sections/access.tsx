/* eslint-disable react-refresh/only-export-components -- a section exports its data (`section`) beside its body */
import { Users } from 'lucide-react';
import type { GuideSection } from '../types';
import {
  Callout, Card, Cards, Code, Details, GuideLink, H2, Lead, List, Needs, OpenLink, P, Shot, Step, Steps, UI,
} from '../kit';

const Body = () => (
  <>
    <Lead>
      Give people access by linking a Databricks group, or one person, to a domain at a permission level. Only Global
      admins can do this, and it needs no code or database work.
    </Lead>

    <H2 id="map-group">Map a group or user to a domain</H2>
    <P>
      <Needs role="Global admin" /> The domain must exist before you can map to it, so start there if it is new.
    </P>
    <Steps>
      <Step title="Open the Admin Panel">
        Click <UI>Admin Panel</UI> (shield icon) under <UI>Resources</UI> in the sidebar, or use{' '}
        <OpenLink page="admin">this link</OpenLink>. If you do not see it, you are not an Admin on any domain and not a Global admin.
        <Shot
          name="admin-overview"
          alt="The Admin Panel with its tab bar"
          caption="The Admin Panel. The text under the title says which tabs follow the selected workspace and which cover the whole app."
          legend={[
            'Admin Panel, at the bottom of the sidebar.',
            'The tabs. Role Mappings is the one you need here.',
            'Which tabs follow the selected workspace and which cover the whole app.',
          ]}
        />
      </Step>
      <Step title="Add the domain if it is new">
        Open <UI>Categories &amp; Domains</UI>. In the <UI>Domains</UI> card, type a <UI>Domain name</UI> and click <UI>Add Domain</UI>.
        A name that differs from an existing one only in capitals or spacing is refused, so <Code>Logistics</Code> and <Code>logistics</Code> cannot both exist.
        <Shot
          name="admin-domains"
          alt="Categories & Domains with the Add Domain form"
          caption="Categories & Domains. Add the domain here, then map it."
          legend={[
            'Category name and Add Category. Categories group widgets by function.',
            'The Categories card.',
            'Domain name and Add Domain. Type the domain and add it.',
          ]}
        />
      </Step>
      <Step title="Open Role Mappings">
        Under <UI>Create Domain Mapping</UI>, type the group or user in <UI>Databricks group or user</UI>.
        Copy the name from the workspace&rsquo;s Groups page rather than retyping it: it must match exactly, capitals included.
      </Step>
      <Step title="Choose the domain and the level">
        Pick the domain from <UI>Mapped Domain</UI>. The list is the domains from <UI>Categories &amp; Domains</UI>. Then pick a{' '}
        <UI>Role Type</UI>: <UI>Viewer</UI>, <UI>Editor</UI> or <UI>Admin</UI>. It starts on <UI>Editor</UI>.
        The levels are explained in <GuideLink to="roles" anchor="levels">Roles &amp; permissions</GuideLink>.
      </Step>
      <Step title="Click Add Mapping">
        The mapping appears in the table below. It applies to anyone whose group or username matches, the next time their
        permissions are read. Ask them to reload the page, and allow a few minutes.
        <Shot
          name="admin-role-mappings"
          alt="Role Mappings with the two forms and the mappings table"
          caption="Role Mappings. The top form makes Global admins, the one below it maps a group or user to a domain."
          legend={[
            'The Databricks group or user, typed exactly as it appears in Databricks.',
            'The domain it applies to.',
            'The role type: Editor or Admin.',
            'Add Mapping saves it.',
          ]}
        />
      </Step>
    </Steps>
    <Callout kind="note" title="Mappings apply to the whole app">
      There is no separate Dev, Test or Prod permission, so it does not matter which <UI>Workspace</UI> is selected when you add a mapping.
    </Callout>

    <H2 id="exact-match">Names must match exactly</H2>
    <P>
      The <UI>Databricks group or user</UI> field is plain text. It is not checked against Databricks when you save, because the app
      cannot list your workspace&rsquo;s groups on your behalf. A typo or a wrong capital saves without complaint and grants nothing.
    </P>
    <List>
      <li>Group names are compared with the groups the person belongs to in Databricks.</li>
      <li>To give one person access, type their username exactly as Databricks has it.</li>
      <li>If someone you mapped still has no access, compare the name with the Groups page, character for character.</li>
    </List>

    <H2 id="global-admins">Make someone a Global admin</H2>
    <P>
      <Needs role="Global admin" /> At the top of <UI>Role Mappings</UI>, <UI>Assign Global Administrator</UI> takes a{' '}
      <UI>Databricks group or user</UI>. Click <UI>Grant Global Admin</UI>. That adds a mapping of the <UI>Global</UI> domain at
      the <UI>Admin</UI> level, which bypasses every domain check. See{' '}
      <GuideLink to="roles" anchor="global-admin">Roles &amp; permissions</GuideLink> for what that allows.
    </P>
    <Callout kind="warn" title="Replace the starter admin mapping">
      A deployment with no Global admin starts with one mapping that makes every member of the Databricks group named <Code>users</Code> a
      Global admin, so that someone can get in and administer it. Look for it in the table and replace it with your real admin group.
    </Callout>
    <Details summary="Running the app locally">
      <P>
        When the app runs on your own machine with <Code>DEV_MODE=true</Code>, you are a Global admin without any mapping. This
        is for developers; a deployed app does not use it.
      </P>
    </Details>

    <H2 id="change-mappings">Change or remove a mapping</H2>
    <P>
      <Needs role="Global admin" /> Hover a row in the table to show its buttons. The pencil edits the row in place: change the
      group, domain or level, then click the tick to save or the cross to cancel. The trash can asks you to confirm, and then the group
      loses that access.
    </P>
    <Details summary="A row says “not a domain”">
      <P>
        The mapping&rsquo;s domain is no longer in <UI>Categories &amp; Domains</UI>, usually because it was renamed or deleted, so
        no widget or view can be filed under it and the mapping grants nothing. Add the domain back, or edit the mapping to choose one that exists.
        Mappings to <UI>Global</UI>, <UI>All</UI> or <UI>App</UI> are never flagged: those names mean every domain.
      </P>
      <P>
        When you add a mapping to a name that is not a domain, you get &ldquo;is not a domain. Add it under Categories &amp; Domains
        first&rdquo;. If you only change the level of an old mapping, the app does not make you fix its domain first.
      </P>
    </Details>

    <H2 id="blocked">When someone says they cannot get in</H2>
    <Steps>
      <Step>Check that a mapping exists for a Databricks group they belong to, or for their username, and that the name matches exactly.</Step>
      <Step>Check the domain and level: a Viewer cannot edit, and Dev and Test need Editor or Admin on some domain.</Step>
      <Step>Ask them to reload, and allow a few minutes after any change.</Step>
      <Step>
        If they can open a widget but its data is empty or refused, that is Unity Catalog, not this app. Data access is granted in Databricks.
      </Step>
    </Steps>
    <P>
      More symptoms and fixes are on <GuideLink to="troubleshooting">Troubleshooting</GuideLink>.
    </P>

    <H2 id="where-next">Where next</H2>
    <Cards cols={2}>
      <Card title="Roles & permissions" to="roles">What each level, and Global admin, can do.</Card>
      <Card title="Settings & models" to="settings">Choose models and limit what the assistant can reach.</Card>
    </Cards>
  </>
);

export const section: GuideSection = {
  id: 'access',
  group: 'admin',
  title: 'Managing access',
  summary: 'Map Databricks groups to domains and make global admins.',
  icon: Users,
  keywords: 'role mapping group sign in permission grant global administrator domain add user',
  Body,
};
