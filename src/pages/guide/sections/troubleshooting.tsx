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

    <H2 id="access-problems">Access and sharing</H2>
    <Table
      head={head}
      rows={[
        [
          'No Admin Panel in the sidebar.',
          'It shows only for Administrators.',
          <>Ask an Administrator if you need something there. See <GuideLink to="access" anchor="administrators">Administrators &amp; access</GuideLink>.</>,
        ],
        [
          'A link says the view isn\u2019t there.',
          'It isn\u2019t shared with you, or it has been archived. The app answers the same way as for something that doesn\u2019t exist.',
          <>Ask whoever sent it to share it with you. See <GuideLink to="access" anchor="ask">Ask for access</GuideLink>.</>,
        ],
        [
          'Something was shared with you, but you can\u2019t see it.',
          'It has never been published, and people with Can use only see published versions.',
          <>Ask its owner to publish it. See <GuideLink to="publishing">Drafts &amp; publishing</GuideLink>.</>,
        ],
        [
          'It was shared with a group you are in, but it doesn\u2019t work for you.',
          'The group name must match the Databricks group exactly, capitals included, and group membership is remembered for a few minutes.',
          <>Compare the name with the workspace&rsquo;s Groups page, and reload after a few minutes. See <GuideLink to="sharing" anchor="who">Who you can share with</GuideLink>.</>,
        ],
        [
          'You can open something but not change it.',
          'You have Can use. Editing, publishing and sharing need Can manage.',
          <>Ask its owner for Can manage, or clone a widget to make your own. See <GuideLink to="sharing" anchor="levels">The two levels</GuideLink>.</>,
        ],
        [
          'A colleague opens your view, but the assistant can\u2019t use its agent.',
          'Using a view doesn\u2019t give use of the agent pinned to it, so they get the default assistant.',
          <>Share the agent with the same people, and publish it. See <GuideLink to="sharing" anchor="rules">How access is worked out</GuideLink>.</>,
        ],
        [
          <>The assistant says &ldquo;That agent isn&rsquo;t available to you&rdquo;.</>,
          'The agent you are chatting with is not published, or is no longer shared with you.',
          <>Pick another agent in the assistant, or ask its owner to share and publish it. See <GuideLink to="agent-studio">Agent Studio</GuideLink>.</>,
        ],
        [
          'A widget opens but its data is empty or refused.',
          'Data runs as you, so Unity Catalog decides what you can read. This app does not grant it.',
          <>Ask the data owner for access in Databricks. See <GuideLink to="widgets">Widgets</GuideLink>.</>,
        ],
      ]}
    />

    <H2 id="publishing-problems">Publishing</H2>
    <Table
      head={head}
      rows={[
        [
          'You saved, but other people still see the old version.',
          'Saving only changes the draft.',
          <>Click <UI>Publish</UI> (on a view, the last button in the header). See <GuideLink to="publishing" anchor="publish">Publish</GuideLink>.</>,
        ],
        [
          <>There is no <UI>Publish</UI> button.</>,
          'The draft matches the published version, so there is nothing to publish and the button is hidden. Or you can only use it, not manage it.',
          <>Make a change first; the chip beside the name then reads <UI>Unpublished changes</UI> and <UI>Publish</UI> appears. If you can only use it, ask whoever manages it.</>,
        ],
        [
          <>The <UI>Draft</UI> / <UI>Published</UI> switch, <UI>Version history…</UI> or <UI>Discard draft…</UI> is missing.</>,
          'The switch and Discard draft appear only when there are unpublished changes, and a view\u2019s Version history only once it has been published. All three are for people who can manage it.',
          <>On a view, look in the <UI>⋯</UI> menu for <UI>Version history…</UI> and <UI>Discard draft…</UI>. See <GuideLink to="views" anchor="header">The view header</GuideLink>.</>,
        ],
        [
          <>A card on a view says &ldquo;Not published yet&rdquo;.</>,
          'The widget on it has never been published.',
          <>Whoever manages the widget publishes it, or publish it with the view from the Publish dialog. See <GuideLink to="publishing" anchor="publish-a-view">Publishing a view</GuideLink>.</>,
        ],
        [
          'People using a view don\u2019t see your latest widget changes.',
          'A view shows each widget at its latest published version.',
          <>Publish the widget, or let the Publish dialog publish it with the view. See <GuideLink to="publishing" anchor="publish-a-view">Publishing a view</GuideLink>.</>,
        ],
        [
          'The Publish dialog lists widgets that are not certified, and the view won\u2019t publish.',
          'An Administrator turned on Shared views may only contain certified widgets, and this view is shared with someone besides you.',
          <>Ask whoever manages each widget to certify it, or ask an Administrator about the setting. See <GuideLink to="publishing" anchor="certify">Certify a widget</GuideLink>.</>,
        ],
        [
          <>Discarding a draft is refused.</>,
          'It has never been published, so there is no published version to go back to.',
          <>Delete it instead, if you no longer want it. See <GuideLink to="publishing" anchor="history">History, Revert and Discard draft</GuideLink>.</>,
        ],
        [
          'Deleting a view asks you to archive it first.',
          'It is shared with other people, so it is archived first, where they can notice it is gone.',
          <>Archive it, then delete it from <UI>Archived</UI>. See <GuideLink to="publishing" anchor="archive">Archive, restore or delete a view</GuideLink>.</>,
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
          'The Content Security Policy blocks anything except this app, the approved CDNs and the Databricks Apps an admin listed. An app approved only through its whole workspace can be framed but not fetched from.',
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
          'The file would not leave you an Administrator.',
          <>Make your group an Administrator in the source app and export again, or use Merge. See <GuideLink to="migration" anchor="safety">Safety checks</GuideLink>.</>,
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
      <Card title="Sharing & permissions" to="sharing">Who can do what.</Card>
      <Card title="Settings & models" to="settings">Limits and switches an admin can change.</Card>
      <Card title="Drafts & publishing" to="publishing">How changes reach people.</Card>
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
