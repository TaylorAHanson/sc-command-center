/* eslint-disable react-refresh/only-export-components -- a section exports its data (`section`) beside its body */
import { ArrowRightLeft } from 'lucide-react';
import type { GuideSection } from '../types';
import {
  Callout, Card, Cards, Code, Details, GuideLink, H2, Lead, List, Needs, OpenLink, P, Step, Steps, Table, UI,
} from '../kit';

const Body = () => (
  <>
    <Lead>
      Each deployed Command Center has its own database, so work built in one does not appear in another. Download a snapshot from the app that has it, then
      import the file into the other.
    </Lead>
    <P>
      <Needs role="Administrator" /> This is for moving everything between <em>deployed apps</em>, for example from a development app to a stage app. Inside one app,
      changes reach people by publishing; see <GuideLink to="publishing">Drafts &amp; publishing</GuideLink>.
    </P>

    <H2 id="export">Download a snapshot</H2>
    <Steps>
      <Step title="Open Data Migration in the source app">
        Go to <OpenLink page="admin">Admin Panel</OpenLink> and choose <UI>Data Migration</UI>.
      </Step>
      <Step title="Choose what to take">
        Under <UI>1. Export a snapshot</UI>, tick the parts to include. Each shows its row count and size.
      </Step>
      <Step title="Download">
        Click <UI>Download snapshot</UI>. You get a compressed file (<Code>.json.gz</Code>).
      </Step>
    </Steps>
    <Callout kind="warn" title="Treat the file like a database backup">
      It holds every row of what you picked, so anyone who has it can read it. Store and share it the way you would a backup. If you tick conversations, the file contains everyone&rsquo;s chats and attachments.
    </Callout>

    <H2 id="import">Preview and import it</H2>
    <Steps>
      <Step title="Open Data Migration in the other app">
        Under <UI>2. Import a snapshot into this app</UI>, choose the file.
      </Step>
      <Step title="Choose Merge or Replace">
        Under <UI>How</UI>, pick <UI>Merge</UI> or <UI>Replace</UI> (explained below). Under <UI>What</UI>, tick only the parts you want to bring in.
      </Step>
      <Step title="Click Preview">
        The app runs the whole import and then undoes it. The report lists, per table, what is in the file, what would be added, what is already there and, for Replace, what would be deleted.
        Columns this app does not have are listed as left out.
      </Step>
      <Step title="Click Import">
        <UI>Import</UI> stays disabled until you have previewed the same file and options. Confirm the dialog, which restates the row counts. A successful import says <UI>Imported.</UI>
      </Step>
    </Steps>

    <H2 id="merge-replace">Merge or Replace</H2>
    <Table
      head={['', 'Merge', 'Replace']}
      rows={[
        [<strong key="a">What it does</strong>, 'Adds what this app is missing. Nothing here is changed or deleted.', 'Makes the chosen parts of this app an exact copy of the snapshot. This app\u2019s own rows in them are deleted.'],
        [<strong key="b">Run it twice</strong>, 'The second run adds nothing.', 'You get the same copy again.'],
        [<strong key="c">Use it to</strong>, 'Bring in new work without touching what the other app already has.', 'Make a stage app a copy of a development app that is the source of truth.'],
        [<strong key="d">Undo</strong>, 'Nothing to undo: nothing existing was altered.', 'Only by importing a snapshot of this app taken beforehand.'],
      ]}
    />
    <Callout kind="warn" title="Take a snapshot of the target before you Replace">
      Replace deletes. If the file turns out wrong, the only way back is a snapshot of this app made before you imported.
    </Callout>

    <H2 id="contents">What a snapshot contains</H2>
    <Table
      head={['Part', 'What it holds', 'Included by default']}
      rows={[
        [<UI key="a">Widgets, views and agents</UI>, 'Every published version and unpublished draft of every widget, view and Agent Studio agent, plus whose sidebar holds which view.', 'Yes'],
        [<UI key="b">Sharing, administrators, categories and domains</UI>, 'Who can use and manage each item, who the Administrators are, and the taxonomy. Replacing these replaces the target\u2019s access control.', 'Yes'],
        [<UI key="c">Deployment settings</UI>, 'The page described in Settings & models. Merge keeps any value the target has already set.', 'Yes'],
        [<UI key="d">Activity history</UI>, 'Action Logs and the widget usage behind the creator leaderboard.', 'Yes'],
        [<UI key="e">Saved conversations and attached files</UI>, 'Everyone\u2019s assistant chats, including uploaded files. The largest and most sensitive part.', 'No'],
      ]}
    />
    <P>
      Deployment settings are described in <GuideLink to="settings">Settings &amp; models</GuideLink>. On a Merge, wherever
      both apps have an access entry for the same item and person, or a draft of the same item, the target keeps its own.
    </P>
    <Callout kind="note" title="Snapshots from before sharing">
      A snapshot downloaded before the app moved to sharing still imports. It holds domain role mappings instead of access
      lists, so the import turns them into access lists and Administrators the same way the upgrade did, and the preview
      says so. See <GuideLink to="access" anchor="migration-report">After the upgrade to sharing</GuideLink>.
    </Callout>

    <H2 id="safety">Safety checks</H2>
    <List>
      <li><strong>All or nothing.</strong> Everything imports in a single step. If anything fails, the app says nothing was changed and leaves the target as it was.</li>
      <li>
        <strong>Lockout protection.</strong> A Replace that would leave you no longer an Administrator is refused, with a message that says so. Make your group an Administrator in the source app and export again, or use Merge.
        See <GuideLink to="access" anchor="administrators">Administrators &amp; access</GuideLink>.
      </li>
      <li><strong>Recorded.</strong> Exports and imports appear in <GuideLink to="action-logs">Action Logs</GuideLink> with who did them and what moved.</li>
      <li><strong>Size.</strong> A file larger than 512 MB, compressed or expanded, is refused by default. Your platform team can raise the limit with the <Code>MIGRATION_MAX_MB</Code> setting.</li>
    </List>
    <Details summary="If the import is refused">
      <List>
        <li>&ldquo;Not a Command Center snapshot&rdquo;: the file was not made by Download snapshot, or was changed afterwards.</li>
        <li>&ldquo;Written by a newer version of the app&rdquo;: update the app you are importing into first.</li>
        <li>&ldquo;Snapshot is larger than&hellip; MB&rdquo;: take fewer parts, for example leave conversations out.</li>
      </List>
    </Details>

    <H2 id="where-next">Where next</H2>
    <Cards cols={3}>
      <Card title="Drafts & publishing" to="publishing">How changes reach people inside one app.</Card>
      <Card title="Action logs" to="action-logs">Find the record of an export or import.</Card>
      <Card title="Troubleshooting" to="troubleshooting">Common problems and fixes.</Card>
    </Cards>
  </>
);

export const section: GuideSection = {
  id: 'migration',
  group: 'admin',
  title: 'Moving data to another app',
  summary: 'Download a snapshot and import it into another deployment.',
  icon: ArrowRightLeft,
  keywords: 'snapshot export import merge replace backup migrate copy dev to test deployment data migration',
  Body,
};
