/* eslint-disable react-refresh/only-export-components -- a section exports its data (`section`) beside its body */
import { Share2 } from 'lucide-react';
import type { GuideSection } from '../types';
import {
  Callout, Card, Cards, Details, Ext, GuideLink, H2, Lead, List, Needs, P, Step, Steps, Table, UI,
} from '../kit';

const Body = () => (
  <>
    <Lead>
      Views, widgets and agents are shared the way a Databricks dashboard is. Each one has its own list of who can use it
      and who can manage it. Read this to share something you built, or to find out why you can or cannot open something.
    </Lead>

    <H2 id="levels">The two levels</H2>
    <Table
      head={['Level', 'What it allows']}
      rows={[
        [<UI key="u">Can use</UI>, 'See the published version in your sidebar or the Widget Library, open it, place a published widget on your own views, and chat with a published agent.'],
        [<UI key="m">Can manage</UI>, 'Everything Can use allows, plus see and edit the draft, publish it, discard it, revert to an older version, change who it is shared with, certify a widget, and archive, restore or delete it.'],
      ]}
    />
    <P>
      Whoever creates something is its <UI>owner</UI> and can manage it from the start. Nothing is shared with anyone else
      until the owner, or someone else who can manage it, shares it.
    </P>

    <H2 id="who">Who you can share with</H2>
    <List>
      <li><strong>A person</strong>, by their Databricks username. Capitals don&rsquo;t matter for people.</li>
      <li><strong>A group</strong>, by its Databricks group name, which must match exactly, capitals included.</li>
      <li><strong>Everyone in this app</strong>, which covers every person who can sign in to it.</li>
    </List>
    <P>
      Groups are managed in Databricks, not here. See <Ext href="https://docs.databricks.com/aws/en/admin/users-groups/groups">Manage groups</Ext> in
      the Databricks documentation. The app looks up your groups when you sign in and remembers the answer for a few
      minutes, so after you are added to a group, allow a few minutes and reload.
    </P>

    <H2 id="share">Share something</H2>
    <P>
      <Needs role="Can manage" /> The share dialog is the same for a view, a widget and an agent. Anyone who can use one
      can open <UI>Share</UI> too, to see who has access (and copy a view&rsquo;s link), but only people who can manage it
      can change the list.
    </P>
    <Steps>
      <Step title="Open the share dialog">
        On a view, click <UI>Share</UI> in the view header. For a widget, click <UI>Share</UI> in Widget Studio, or hover
        it in the Widget Library and click the share icon. For an agent,
        click <UI>Share</UI> in Agent Studio.
      </Step>
      <Step title="Add a person or group">
        Type in the box at the top. Suggestions are the names this app has already seen, and groups you belong to are marked{' '}
        <UI>Your group</UI>. A name the app has never seen is still accepted, with a reminder that it must match the
        Databricks user or group name exactly.
      </Step>
      <Step title="Choose the level and click Add">
        Pick <UI>Can use</UI> or <UI>Can manage</UI>, then <UI>Add</UI>. The entry appears under <UI>People with access</UI>.
      </Step>
      <Step title="Or open it to everyone">
        Under <UI>General access</UI>, choose <UI>Everyone in this app can use</UI> instead of <UI>Only people with access</UI>.
      </Step>
    </Steps>
    <P>
      Every change saves as soon as you make it. <UI>Done</UI> closes the dialog, and <UI>Copy link</UI> copies a link you
      can send. Under <UI>People with access</UI>, change an entry&rsquo;s level with its picker, or remove it. Your own entry
      says <UI>(you)</UI> and the owner&rsquo;s says <UI>Owner</UI>.
    </P>
    <Callout kind="tip" title="Publish before you expect anyone to see it">
      People with <UI>Can use</UI> only ever see the published version. If you share something that has never been
      published, the dialog reminds you that they will see it once you publish. See{' '}
      <GuideLink to="publishing">Drafts &amp; publishing</GuideLink>.
    </Callout>

    <H2 id="rules">How access is worked out</H2>
    <List>
      <li><strong>The highest level wins.</strong> If you have Can use as yourself and Can manage through a group, you can manage it.</li>
      <li><strong>A view carries its widgets.</strong> Anyone who can use a published view sees the published widgets on it, without each widget being shared with them separately. Those widgets show on the view, but the Widget Library doesn&rsquo;t offer them.</li>
      <li><strong>A view does not carry its agent.</strong> Someone who can use a view but not its pinned agent gets the default assistant on it. Share the agent with the same people, and publish it, so they can chat with it.</li>
      <li><strong>Something always keeps a manager.</strong> You can&rsquo;t remove the last person or group with Can manage; only an Administrator can.</li>
      <li><strong>Links open only for people something is shared with.</strong> Anyone else is told it isn&rsquo;t there, exactly as if it didn&rsquo;t exist.</li>
      <li><strong>Domains don&rsquo;t grant anything.</strong> A domain is a label for filtering the Widget Library, not a permission.</li>
      <li><strong>Data is still yours.</strong> A widget or agent reads data as the person using it, so Unity Catalog decides what each person sees. Sharing a widget never grants access to a table.</li>
    </List>

    <H2 id="administrators">Administrators</H2>
    <P>
      <UI>Administrators</UI> can manage every view, widget and agent in the app, whether or not it is shared with them, and
      are the only people who see the Admin Panel. Their sidebar still lists only the views they own or that are shared
      with them; they find the rest under <UI>Admin Panel → Content</UI>, and can open any view by its link. They are
      listed in the Admin Panel; see <GuideLink to="access" anchor="administrators">Administrators &amp; access</GuideLink>.
    </P>

    <H2 id="who-can">Who can do what</H2>
    <Table
      head={['Action', 'Anyone', 'Can use', 'Can manage', 'Administrator']}
      rows={[
        ['Build a new widget or agent, or create a view', 'Yes', 'Yes', 'Yes', 'Yes'],
        ['See and open the published version', 'No', 'Yes', 'Yes', 'Yes'],
        ['See who a view is shared with, and copy its link', 'No', 'Yes', 'Yes', 'Yes'],
        ['Save a copy of an agent as your own', 'No', 'Yes', 'Yes', 'Yes'],
        ['Place a published widget on your own view', 'No', 'Yes', 'Yes', 'Yes'],
        ['See and edit the draft; publish, discard, revert', 'No', 'No', 'Yes', 'Yes'],
        ['Change who it is shared with', 'No', 'No', 'Yes', 'Yes'],
        ['Certify a widget version', 'No', 'No', 'Yes', 'Yes'],
        ['Archive, restore or delete it', 'No', 'No', 'Yes', 'Yes'],
        ['Open the Admin Panel', 'No', 'No', 'No', 'Yes'],
      ]}
    />
    <Details summary="What happened to Viewer, Editor and Admin on a domain">
      <P>
        Earlier releases gave access through domains: a Databricks group was mapped to a domain as Viewer, Editor or Admin.
        When the app moved to sharing, those mappings were turned into access lists once. Viewer became Can use, and Editor
        and Admin became Can manage, on every widget filed under that domain, every view that used to be global, and every
        agent that belonged to that domain. Owners kept Can manage, people who had added someone&rsquo;s personal view to
        their sidebar got Can use on it, and agents that were global became shared with everyone in this app. Everyone who
        could open something before can still open it.
      </P>
      <P>
        An Admin mapping on the global domain (Global, All or App) made that group an Administrator. A Viewer or Editor
        mapping on it covers only items filed under that exact name, which is all it ever did.
      </P>
    </Details>

    <H2 id="where-next">Where next</H2>
    <Cards cols={2}>
      <Card title="Drafts & publishing" to="publishing">How your changes reach the people you shared with.</Card>
      <Card title="Administrators & access" to="access">Ask for access, and manage who is an Administrator.</Card>
    </Cards>
  </>
);

export const section: GuideSection = {
  id: 'sharing',
  group: 'build',
  title: 'Sharing & permissions',
  summary: 'Share views, widgets and agents, and who may do what.',
  icon: Share2,
  keywords: 'share sharing permission access can use can manage owner everyone group user who can viewer editor admin role',
  Body,
};
