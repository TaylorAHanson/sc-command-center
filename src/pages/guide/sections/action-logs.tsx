/* eslint-disable react-refresh/only-export-components -- a section exports its data (`section`) beside its body */
import { ScrollText } from 'lucide-react';
import type { GuideSection } from '../types';
import {
  Lead, H2, P, List, Steps, Step, Callout, Needs, Details, Shot, UI, Code as C, Table,
  GuideLink, OpenLink, Cards, Card,
} from '../kit';

const Body = () => (
  <>
    <Lead>
      Action logs are the audit trail of the Command Center. Use them to see who pressed an action button in an
      executable widget, when, and what was on their screen at the time. <Needs role="Admin Panel access" />
    </Lead>

    <H2 id="open-the-logs">Open the logs</H2>
    <Steps>
      <Step>
        Open the <OpenLink page="admin">Admin Panel</OpenLink> from the sidebar and click{' '}
        <UI>Action Logs</UI>, the last tab. The page is titled <UI>Action Logs (Telemetry)</UI>.
      </Step>
      <Step>
        Check the <UI>Workspace</UI> switcher in the sidebar. The logs are kept per workspace (Dev, Test or
        Prod), and the Admin Panel says which one it is showing.
      </Step>
      <Step>
        Type in <UI>Search logs...</UI> to narrow the list, and click a row to read its detail.
      </Step>
    </Steps>
    <Shot
      name="admin-action-logs"
      alt="The Action Logs tab of the Admin Panel"
      caption="The Action Logs tab."
      legend={[
        'Search logs.',
        'The columns: Timestamp, Widget, Action, User, Domain, User Explanation and Action ID.',
        'Open a row to read its full detail.',
      ]}
    />
    <Callout kind="admin" title="Who can see it">
      <P>
        Anyone who can open the Admin Panel can read the logs: global admins, and people with Admin on at least
        one domain. The list is not narrowed to your domains, so it shows every action in the workspace. See{' '}
        <GuideLink to="roles">Roles and permissions</GuideLink>.
      </P>
    </Callout>

    <H2 id="what-is-recorded">What is recorded</H2>
    <P>
      Two kinds of event write a row. Nothing else does: views, promotions and role changes are not in this log.
    </P>
    <Table
      head={['Event', 'What the row says']}
      rows={[
        [
          <strong key="a">A button press in an executable widget</strong>,
          'The widget, the action name the widget gave it, who pressed it, when, and the view the widget was on.',
        ],
        [
          <strong key="b">A data migration</strong>,
          <>The widget column reads <UI key="m">Data migration</UI> and the action is <C key="e">export_snapshot</C> or <C key="i">import_snapshot</C>. The explanation says which workspace and which parts of the data. See <GuideLink key="l" to="migration">Moving data to another app</GuideLink>.</>,
        ],
      ]}
    />
    <P>
      The widget row is written first, and only then does the action run. If the app cannot write the row, it
      shows "Could not record this action in the audit log, so it was not run" and the action does not happen.
      There is no confirmation dialog: the log entry is the record.
    </P>

    <H2 id="read-a-row">Read a row</H2>
    <Table
      head={['Column', 'What it shows']}
      rows={[
        [<UI key="t">Timestamp</UI>, 'When the action was logged, in your local time. The newest entries come first.'],
        [<UI key="w">Widget</UI>, 'The widget the action came from.'],
        [<UI key="a">Action</UI>, 'The action name the widget used. Blank for older entries.'],
        [<UI key="u">User</UI>, 'Who did it. The app works this out from the signed-in user, never from the request, so it cannot be typed in by the widget. Blank for entries logged before names were recorded.'],
        [<UI key="d">Domain</UI>, 'The widget\'s current domain. Blank for data migrations, and for a widget that has since been removed.'],
        [<UI key="e">User Explanation</UI>, 'A sentence about the event. Data migrations fill it in. For widget actions it is blank, because people are no longer asked to explain a click.'],
        [<UI key="i">Action ID</UI>, 'The number of the log row.'],
      ]}
    />
    <P>
      Click a row to open it. The detail shows two more things.
    </P>
    <List>
      <li><UI>Request ID</UI>: a unique handle for this one action. It reads "Not recorded" on older entries.</li>
      <li>
        <UI>Dashboard Context</UI>: a snapshot of what the person was looking at. It holds the view's name and
        id, the tab, and every widget on that tab with its type and settings. This is the "what they saw" half
        of the cause-and-effect pair.
      </li>
    </List>
    <Details summary="Search, and how far back the list goes">
      <P>
        <UI>Search logs...</UI> matches the widget name, action, user, explanation, domain and request ID. It
        searches only the entries already loaded, which are the 100 most recent in the workspace. There are no
        date filters, paging or export buttons. A data migration snapshot includes activity history by default,
        which is the way to take a full copy of the log.
      </P>
    </Details>

    <H2 id="request-id">Join an action to the SQL it ran</H2>
    <P>
      The log records the intent: this person pressed this button on this screen. Databricks records the
      effect. The <UI>Request ID</UI> links the two. When an executable widget writes data, the app adds that ID
      to the front of the SQL statement as a comment (<C>cc-action: &lt;id&gt;</C>). Search for the ID in
      Databricks query history, or in the table's history, to find the exact statement that action ran.
    </P>
    <P>
      The log row does not store the SQL text itself. The statement runs as the signed-in user, so Unity
      Catalog still decides whether the write was allowed.
    </P>

    <H2 id="why-executable-matters">Why Is Executable Action matters</H2>
    <P>
      A widget only writes to this log if its author turned on <UI>Is Executable Action</UI> in{' '}
      <GuideLink to="widget-studio" anchor="executable">Widget Studio</GuideLink>. Widgets without it have no
      logged actions. If a widget's SQL changes data, the setting is required and saving is refused without it, so
      every change a widget makes appears here with the person who made it.
    </P>
    <Callout kind="note" title="Why the Command Center keeps this">
      Pairing "see data" with "take action" on one screen gives rows that are cause and effect: the user saw
      this, then did that. That record is the telemetry the product's AI maturity plan builds on.
    </Callout>

    <H2 id="where-next">Where next</H2>
    <Cards>
      <Card title="Widget Studio" to="widget-studio" anchor="executable">Turn on Is Executable Action for a widget.</Card>
      <Card title="Moving data to another app" to="migration">Exports and imports are logged here too.</Card>
    </Cards>
  </>
);

export const section: GuideSection = {
  id: 'action-logs',
  group: 'admin',
  title: 'Action logs',
  summary: 'See who changed what, and what people did with widgets.',
  icon: ScrollText,
  keywords: 'audit trail telemetry log history who did what executable action request id',
  Body,
};
