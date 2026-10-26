/* eslint-disable react-refresh/only-export-components -- a section exports its data (`section`) beside its body */
import { LifeBuoy } from 'lucide-react';
import type { GuideSection } from '../types';
import { Card, Cards, GuideLink, H2, Lead, OpenLink, P, Table, UI } from '../kit';

const head = ['What you see', 'Why', 'What to do'];

const Body = () => (
  <>
    <Lead>
      Find the symptom, read why it happens, and follow the link to the page that explains the fix. Some fixes need an admin; those say so.
    </Lead>

    <H2 id="access-problems">Access and workspaces</H2>
    <Table
      head={head}
      rows={[
        [
          'No Admin Panel in the sidebar.',
          'It shows only for Global admins and people with the Admin level on a domain.',
          <>Ask a Global admin for access. See <GuideLink to="roles" anchor="levels">Roles &amp; permissions</GuideLink>.</>,
        ],
        [
          'You are in a group that was given access, but you still cannot edit.',
          'The name in the mapping must match the Databricks group exactly, capitals included. A change can also take a few minutes to apply.',
          <>An admin compares the name with the Groups page and fixes it. See <GuideLink to="access" anchor="exact-match">Names must match exactly</GuideLink>.</>,
        ],
        [
          <>A mapping row says <UI>not a domain</UI>.</>,
          'Its domain was renamed or deleted, so it grants nothing.',
          <>An admin edits the mapping or adds the domain back. See <GuideLink to="access" anchor="change-mappings">Change or remove a mapping</GuideLink>.</>,
        ],
        [
          <><UI>Dev</UI> and <UI>Test</UI> are greyed out.</>,
          'Those workspaces need Editor or Admin on a domain.',
          <>Ask for Editor on the domain you work in. See <GuideLink to="promotion" anchor="workspaces">Dev, Test and Prod</GuideLink>.</>,
        ],
        [
          'A link opens Prod with a note that it needs Editor or Admin on a domain.',
          'The link was copied from Dev or Test, and you cannot open those.',
          <>Ask for the Prod link, or for Editor access. See <GuideLink to="promotion" anchor="workspaces">Dev, Test and Prod</GuideLink>.</>,
        ],
        [
          <><UI>Create Global View</UI> says you cannot edit any domain, or &ldquo;Couldn&rsquo;t load domains&rdquo;.</>,
          'Global views are filed under a domain you can edit, and the list could not be read.',
          <>Choose <UI>Retry</UI>. If it stays empty, you need Editor on a domain. See <GuideLink to="roles">Roles &amp; permissions</GuideLink>.</>,
        ],
        [
          'A widget opens but its data is empty or refused.',
          'Data runs as you, so Unity Catalog decides what you can read. This app does not grant it.',
          <>Ask the data owner for access in Databricks. See <GuideLink to="widgets">Widgets</GuideLink>.</>,
        ],
      ]}
    />

    <H2 id="promotion-problems">Promoting work</H2>
    <Table
      head={head}
      rows={[
        [
          <><UI>Promote</UI> is greyed out in Widget Studio. The tooltip says to publish first.</>,
          'Only a published widget can be promoted.',
          <>Click <UI>Publish</UI>, then promote. See <GuideLink to="promotion" anchor="promote-widget">Promote a widget</GuideLink>.</>,
        ],
        [
          'The new version is not what Test or Prod shows.',
          'Promotion copies the last saved version, and each workspace numbers its own versions.',
          <>Save first, then promote, and compare content rather than numbers. See <GuideLink to="promotion" anchor="versions">Versions</GuideLink>.</>,
        ],
        [
          'A promoted view is missing widgets, or shows the wrong version of one.',
          'Widgets are separate from views in each workspace, and a pinned version number means nothing across workspaces.',
          <>Promote the widgets first, or leave <UI>Promote them too</UI> ticked in the dialog. See <GuideLink to="promotion" anchor="promote-view">Promote a view</GuideLink>.</>,
        ],
        [
          'The assistant in Test or Prod cannot open a pinned agent.',
          'Agents are not promoted with a view.',
          <>Recreate the agent in that workspace, or pin another. See <GuideLink to="agent-studio">Agent Studio</GuideLink>.</>,
        ],
        [
          'Saving a global view is refused because widgets are not certified.',
          'An admin turned on the certified-only setting.',
          <>Certify the widgets in Prod, or ask an admin about the setting. See <GuideLink to="promotion" anchor="certify">Certify a widget</GuideLink>.</>,
        ],
      ]}
    />

    <H2 id="widget-problems">Widgets and Widget Studio</H2>
    <Table
      head={head}
      rows={[
        [
          'Saving a widget is refused.',
          'Its code uses something not allowed, such as eval or innerHTML, or an address other than this app, the approved CDNs and the Databricks Apps an admin listed. The message names what tripped it.',
          <>Ask the agent for the jsDelivr copy of a library, or to remove the offending code. See <GuideLink to="widget-studio">Widget Studio</GuideLink>.</>,
        ],
        [
          'Saving is refused for a widget whose SQL changes data.',
          'A widget that writes data must be marked Executable, so every change is recorded in Action Logs.',
          <>Switch on <UI>Is Executable Action</UI>. See <GuideLink to="action-logs">Action Logs</GuideLink>.</>,
        ],
        [
          <>A widget shows <UI>Render Failed</UI>.</>,
          'Its code crashed while drawing. Widget Studio tries to repair it up to three times.',
          <>Click <UI>Try Again</UI>, or describe what you see to the agent. See <GuideLink to="widget-studio">Widget Studio</GuideLink>.</>,
        ],
        [
          'A widget stopped loading a script or sending data.',
          'The Content Security Policy blocks anything except this app, the approved CDNs and the Databricks Apps an admin listed.',
          <>Fix the widget. An admin may switch the policy to report-only briefly, to find the cause. See <GuideLink to="settings" anchor="reach">Settings &amp; models</GuideLink>.</>,
        ],
        [
          'A widget says it shows only part of the data.',
          'Its result went past the row limit.',
          <>An admin can raise <UI>Most rows one widget query can return</UI>. See <GuideLink to="settings" anchor="limits">Limits</GuideLink>.</>,
        ],
        [
          'A tile or button does nothing, or looks muted.',
          'Its link has not been set, or the tab it went to was deleted.',
          <>Open the card&rsquo;s gear and choose a tab or web address. See <GuideLink to="views">Views</GuideLink>.</>,
        ],
        [
          'Widget Studio gives up on a big widget.',
          'The request ran out of time.',
          <>An admin can raise <UI>Widget generation timeout (seconds)</UI>. See <GuideLink to="settings" anchor="limits">Limits</GuideLink>.</>,
        ],
        [
          'An agent draft in Agent Studio fails or ends mid-way.',
          'The draft is one long object, and a low response limit cuts it off.',
          <>An admin can raise <UI>Agent Studio response length limit (tokens)</UI>. See <GuideLink to="settings" anchor="limits">Limits</GuideLink>.</>,
        ],
      ]}
    />

    <H2 id="assistant-problems">The assistant</H2>
    <Table
      head={head}
      rows={[
        [
          'The assistant says it has no way to run SQL or ask Genie.',
          'An admin switched those tools off for the whole app, so they are not offered.',
          <>Ask an admin. See <GuideLink to="settings" anchor="reach">Control what the assistant may reach</GuideLink>.</>,
        ],
        [
          'It cannot say what is on your screen.',
          'An admin turned off sharing a summary of the dashboard.',
          <>Ask an admin, or paste the detail into your question. See <GuideLink to="settings" anchor="privacy">Retention and what the assistant sees</GuideLink>.</>,
        ],
        [
          'It reports a permission error on a table.',
          'Tools run as you, so the error describes your access, not the assistant\u2019s.',
          <>Request access in Databricks. See <GuideLink to="assistant">The assistant</GuideLink>.</>,
        ],
        [
          'A Genie answer takes long and then times out.',
          'Genie is polled only for a set time.',
          <>Ask an admin to raise <UI>Genie query timeout (seconds)</UI>. See <GuideLink to="settings" anchor="limits">Limits</GuideLink>.</>,
        ],
        [
          'An attached file will not read.',
          'The usual causes are a scanned PDF with no text layer, a password-protected file, or an unsupported format. Files are limited to 25 MB each and five per conversation.',
          <>Export a text version, or remove the password. See <GuideLink to="assistant">The assistant</GuideLink>.</>,
        ],
        [
          <>An image in an answer says &ldquo;image from&hellip; not loaded&rdquo;.</>,
          'Images load only from this app, so a manipulated answer cannot send data to another site.',
          <>Nothing is broken. If you wanted the data, ask for a chart or table instead. See <GuideLink to="assistant">The assistant</GuideLink>.</>,
        ],
        [
          'Old conversations are gone.',
          'Only the 50 most recent per person are kept, and an admin may also delete conversations after a number of days.',
          <>Ask an admin what retention is set. See <GuideLink to="settings" anchor="privacy">Retention and what the assistant sees</GuideLink>.</>,
        ],
      ]}
    />

    <H2 id="admin-problems">Admin tasks</H2>
    <Table
      head={head}
      rows={[
        [
          'A button that acts on data does nothing, and its confirmation stays open.',
          'The action could not be recorded in Action Logs, and nothing runs without a record.',
          <>Try again. If it keeps failing, tell an admin. See <GuideLink to="action-logs">Action Logs</GuideLink>.</>,
        ],
        [
          'A Replace import is refused because it would lock you out.',
          'The file\u2019s role mappings would not leave you a Global admin.',
          <>Add your group as a Global admin in the source app and export again, or use Merge. See <GuideLink to="migration" anchor="safety">Safety checks</GuideLink>.</>,
        ],
        [
          'An import says the snapshot is too large.',
          'Files over 512 MB are refused by default.',
          <>Export fewer parts, such as leaving out conversations. See <GuideLink to="migration" anchor="contents">What a snapshot contains</GuideLink>.</>,
        ],
      ]}
    />

    <H2 id="still-stuck">Still stuck?</H2>
    <P>
      Ask the assistant. It is the chat button at the bottom of the sidebar and it knows how this app works, so describe what you did and what you
      saw. If something used to work, check <OpenLink page="release-notes">Release Notes</OpenLink> for a recent change or a fix. For anything that needs a setting or a
      permission, name the page above to the admin who can change it.
    </P>
    <Cards cols={3}>
      <Card title="Roles & permissions" to="roles">Who can do what.</Card>
      <Card title="Settings & models" to="settings">Limits and switches an admin can change.</Card>
      <Card title="Promoting work" to="promotion">Dev, Test and Prod.</Card>
    </Cards>
  </>
);

export const section: GuideSection = {
  id: 'troubleshooting',
  group: 'reference',
  title: 'Troubleshooting',
  summary: 'Answers to the things people most often get stuck on.',
  icon: LifeBuoy,
  keywords: 'error problem fix refused greyed out missing cannot why not working stuck help',
  Body,
};
