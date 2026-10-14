/* eslint-disable react-refresh/only-export-components -- a section exports its data (`section`) beside its body */
import { Shield } from 'lucide-react';
import type { GuideSection } from '../types';
import {
  Callout, Card, Cards, Details, Ext, GuideLink, H2, Lead, List, P, Table, UI,
} from '../kit';

const Body = () => (
  <>
    <Lead>
      Who can see, change and promote things is decided by domains and three permission levels, which come from
      Databricks groups. Read this to find out why you can or cannot do something, or before you grant anyone access.
    </Lead>

    <H2 id="domains">What a domain is</H2>
    <P>
      A <UI>domain</UI> is a business area, such as Finance or Supply Chain. Global views, widgets and saved agents are
      each filed under one. If you have no role in a domain, you do not see its global views or widgets, and you cannot
      place them on a view. A widget that holds sensitive figures belongs in a domain only the right people can reach.
    </P>
    <P>
      Domains are not the same as categories. Categories only group widgets by function in Widget Studio and the Widget
      Library. Domains decide who gets in. Both are managed under <UI>Categories &amp; Domains</UI> in the Admin Panel (see{' '}
      <GuideLink to="access">Managing access</GuideLink>).
    </P>

    <H2 id="groups">How Databricks groups become permissions</H2>
    <P>
      The Command Center keeps no user list of its own. When you sign in, it reads your Databricks username and the
      groups and roles you belong to. A <UI>role mapping</UI> links one of those names to a domain at a permission level.
      Your permissions are every mapping that matches your username or any of your groups.
    </P>
    <List>
      <li>One person can match several mappings. <strong>The highest level wins</strong> for each domain: Viewer plus Editor on the same domain gives Editor.</li>
      <li>Being a Viewer on one domain never limits what you can do in another where you are an Editor.</li>
      <li>A name must match exactly, capitals included. A mapping that names a group you are not in does nothing.</li>
      <li>The app looks up your groups when you sign in and remembers the answer for a few minutes. After you are added to a group or a mapping, reload the page, and allow a few minutes.</li>
    </List>
    <P>
      Groups are managed in Databricks, not here. See <Ext href="https://docs.databricks.com/aws/en/admin/users-groups/groups">Manage groups</Ext> in
      the Databricks documentation.
    </P>

    <H2 id="levels">The three levels</H2>
    <Table
      head={['Level', 'What you can do in that domain']}
      rows={[
        [<UI key="v">Viewer</UI>, 'See the domain\u2019s global views and widgets and use them. You cannot create or change them.'],
        [<UI key="e">Editor</UI>, 'Everything a Viewer can, plus create and edit the domain\u2019s widgets and agents, change the settings of its global views, and promote, roll back and certify widgets. An Editor on any domain can also open the Dev and Test workspaces and the two studios.'],
        [<UI key="a">Admin</UI>, 'Everything an Editor can, plus the Admin Panel appears in your sidebar, where global views are promoted, removed and restored. Admin on a domain does not let you change who has access: that needs Global admin.'],
        [<UI key="g">Global admin</UI>, 'Every domain at full control, and the only level that can map roles, change settings and move data. See below.'],
      ]}
    />
    <Callout kind="note" title="Dev and Test need Editor or Admin">
      You need Editor or Admin on at least one domain to open the <UI>Dev</UI> and <UI>Test</UI> workspaces. Without it, those
      buttons stay disabled and you stay on Prod. See <GuideLink to="promotion" anchor="workspaces">Promoting work</GuideLink>.
    </Callout>

    <H2 id="global-admin">Global admin</H2>
    <P>
      A Global admin has unrestricted access: they bypass every domain check, can see every domain, and are the only people
      who can map roles, create domains and categories, change <GuideLink to="settings">Settings</GuideLink> and use{' '}
      <GuideLink to="migration">Data Migration</GuideLink>. Someone is a Global admin when a mapping gives their group or username
      the <UI>Admin</UI> level on the <UI>Global</UI> domain. <GuideLink to="access" anchor="global-admins">Managing access</GuideLink> shows how.
    </P>
    <Callout kind="warn" title="Keep Global admin small">
      Global admin sees all data the app can show and can change who else has access. Map a small group, not a company-wide one.
    </Callout>

    <H2 id="who-can">Who can do what</H2>
    <P>This covers the common actions. &ldquo;Yes&rdquo; means that level can do it; Global admin can do all of them.</P>
    <Table
      head={['Action', 'Viewer', 'Editor', 'Admin', 'Global admin']}
      rows={[
        ['See the domain\u2019s global views and widgets', 'Yes', 'Yes', 'Yes', 'Yes, every domain'],
        ['Open the Dev and Test workspaces', 'No', 'Yes', 'Yes', 'Yes'],
        ['Create and edit widgets in Widget Studio', 'No', 'Yes', 'Yes', 'Yes'],
        ['Save an agent for a domain in Agent Studio', 'No', 'Yes', 'Yes', 'Yes'],
        ['Save an agent for everyone (global visibility)', 'No', 'No', 'No', 'Yes'],
        ['Promote, roll back or certify a widget', 'No', 'Yes', 'Yes', 'Yes'],
        ['Change a global view\u2019s settings (name, look, assistant)', 'No', 'Yes', 'Yes', 'Yes'],
        ['Add, move or remove widgets and tabs on a global view', 'No', 'No', 'No', 'Yes'],
        ['Promote, remove, restore or delete a global view', 'No', 'No', 'Yes', 'Yes'],
        ['Map roles to domains; add or change categories and domains', 'No', 'No', 'No', 'Yes'],
        ['Change Settings; use Data Migration', 'No', 'No', 'No', 'Yes'],
      ]}
    />
    <Details summary="Notes on the table">
      <List>
        <li>
          <strong>Global views are read-only on the canvas</strong> for everyone but Global admins; the page title says
          <em> (Read-Only)</em>. You can still hover a global view in the sidebar and copy it to your own views to edit.
        </li>
        <li>
          <strong>Promoting and removing global views</strong> happens on screens in the Admin Panel, and the Admin Panel only
          appears for Admins and Global admins. Promoting a widget does not need it: the <UI>Promote</UI> button in Widget Studio works for an Editor.
        </li>
        <li>
          <strong>Role Mappings and Categories &amp; Domains</strong> tabs show for Admins too, but saving a change is refused unless you are a Global
          admin. The <UI>Settings</UI> and <UI>Data Migration</UI> tabs only appear for Global admins.
        </li>
        <li>
          <strong>Deleting a widget</strong> is not a role question: its author can delete it, and anyone can delete a widget that has no
          recorded person as its author.
        </li>
        <li>
          <strong>Promoting a view with &ldquo;Promote them too&rdquo;</strong> also copies the widgets it uses, which needs Editor on each
          widget&rsquo;s domain.
        </li>
        <li>
          <strong>What a person&rsquo;s queries return</strong> is still decided by Unity Catalog, as that person. A role here never
          grants access to a table.
        </li>
      </List>
    </Details>

    <H2 id="app-wide">What applies to the whole app</H2>
    <P>
      Permissions are the same in Dev, Test and Prod. An Editor is an Editor in all three, and it makes no difference which{' '}
      <UI>Workspace</UI> was selected when a mapping was added. The Admin Panel says which parts follow the workspace you are on:
    </P>
    <Table
      head={['Applies to the whole app', 'Follows the selected workspace']}
      rows={[
        ['Role mappings, and so every permission', 'Categories and domains'],
        ['Settings (models, limits, switches)', 'Action logs'],
        ['Widget and view promotion, which lists all three workspaces', 'The widgets, views and agents themselves'],
      ]}
    />
    <P>
      Because the list of domains follows the workspace but mappings do not, a domain only has to exist in one workspace
      to be offered when you map a role.
    </P>

    <H2 id="where-next">Where next</H2>
    <Cards cols={2}>
      <Card title="Managing access" to="access">Map a Databricks group to a domain, step by step.</Card>
      <Card title="Promoting work" to="promotion">How Dev, Test and Prod fit with these permissions.</Card>
    </Cards>
  </>
);

export const section: GuideSection = {
  id: 'roles',
  group: 'admin',
  title: 'Roles & permissions',
  summary: 'Domains, permission levels, and who may do what.',
  icon: Shield,
  keywords: 'viewer editor admin permission access domain scim group rbac who can',
  Body,
};
