/* eslint-disable react-refresh/only-export-components -- a section exports its data (`section`) beside its body */
import { CalendarClock } from 'lucide-react';
import type { GuideSection } from '../types';
import { Callout, Card, Cards, GuideLink, H2, Lead, List, OpenLink, P, Step, Steps, Table, UI } from '../kit';

const Body = () => (
  <>
    <Lead>
      A widget with a <UI>Schedule</UI> button can email its results on a timetable you choose: every weekday morning, the first of each month, or
      every hour. Scheduled reports run as you, with your access to data, while you are away.
    </Lead>

    <H2 id="schedule-a-report">Schedule a report</H2>
    <P>
      Press <UI>Schedule</UI> on a widget. The dialog opens filled in by the widget, and nothing is saved until you press <UI>Save schedule</UI>.
    </P>
    <Steps>
      <Step title="Name it and choose when it runs">
        Pick <UI>Hourly</UI>, <UI>Daily</UI>, <UI>Weekly</UI> or <UI>Monthly</UI>. Weekly lets you pick the days (<UI>Weekdays</UI> picks Monday to
        Friday); Monthly lets you pick days of the month, and a day past a short month&rsquo;s end runs on its last day. Choose the time and the time
        zone, which starts as your browser&rsquo;s. The line underneath reads it back, such as &ldquo;Every weekday at 08:00
        (America/Los_Angeles)&rdquo;.
      </Step>
      <Step title="Choose who gets it">
        <UI>Recipients</UI> starts with your own address unless the widget suggests others. Press <UI>Enter</UI> or type a comma after each address.
        The same limits as the <GuideLink to="widgets" anchor="email">Send dialog</GuideLink> apply.
      </Step>
      <Step title="Write the email">
        Set the <UI>Subject</UI> and an optional <UI>Message</UI> (Markdown works). Under <UI>Send</UI>, choose <UI>Every time</UI>,{' '}
        <UI>Only when the query returns rows</UI> or <UI>Only when the query returns no rows</UI>, and tick <UI>Attach the results as a CSV file</UI>{' '}
        if you want them attached.
      </Step>
      <Step title="Save, and connect if asked">
        Press <UI>Save schedule</UI>. The save is recorded in <UI>Action Logs</UI>. If your account isn&rsquo;t connected yet, the schedule is
        created and waits, and the dialog offers <UI>Connect your account</UI>; see <GuideLink to="schedules" anchor="connect">below</GuideLink>.
      </Step>
    </Steps>
    <P>
      <UI>The query it runs</UI>, at the bottom of the dialog, is the statement the widget ran when you saved. The schedule keeps that exact
      statement, so changing the widget&rsquo;s filters later doesn&rsquo;t change it. To schedule something different, change the widget and
      schedule it again.
    </P>
    <Callout kind="tip" title="Run a statement instead">
      On an executable widget the dialog also offers <UI>Run the statement</UI> instead of <UI>Email the results</UI>. The statement then runs on
      the timetable, nobody is emailed, and each run is recorded in <UI>Action Logs</UI>.
    </Callout>

    <H2 id="connect">Connect your account</H2>
    <P>
      Because a schedule runs as you, you connect your Databricks account to the app once. <UI>Connect your account</UI> signs you in to Databricks
      and brings you back where you were, with a message saying whether it worked. The connection lasts as long as your administrators&rsquo;
      setup allows (30 days by default), and reconnecting renews it. Manage it from the card at the top of{' '}
      <OpenLink page="schedules">My schedules</OpenLink>: <UI>Reconnect</UI>, or <UI>Disconnect</UI>, which stops your schedules until you connect
      again without deleting them.
    </P>
    <P>
      When you have active schedules and your connection ends within a week, or needs reconnecting, a yellow banner across the top of the app
      says so. Its link opens My schedules; closing it hides it for the rest of your browser session.
    </P>
    <Callout kind="note" title="If connecting fails">
      The message says why. The most common: you were signed in to Databricks as a different user. Sign in as yourself and connect again. If it
      says Databricks didn&rsquo;t grant lasting access or didn&rsquo;t say who signed in, ask an administrator to check the app connection.
    </Callout>

    <H2 id="my-schedules">My schedules</H2>
    <P>
      <UI>Resources</UI> → <UI>My schedules</UI> in the sidebar lists your schedules: what each does, how often, how many recipients, its status,
      and its last and next run. For each one:
    </P>
    <List>
      <li><UI>Run now</UI> runs it once outside its timetable. It starts within about 30 seconds.</li>
      <li><UI>Pause</UI> stops it until you press <UI>Resume</UI>.</li>
      <li><UI>Edit</UI> opens the same dialog. The query and what it does can&rsquo;t change.</li>
      <li><UI>Delete</UI> removes it, after asking.</li>
      <li>The arrow beside it shows its last 20 runs: when, how it started, the result, rows, recipients emailed, and any error.</li>
    </List>
    <Table
      head={['Status', 'What it means']}
      rows={[
        [<UI key="a">Active</UI>, 'Runs on its timetable.'],
        [<UI key="p">Paused</UI>, 'You paused it. Resume to run it again.'],
        [<UI key="f">Paused after failures</UI>, 'Several runs in a row failed. Fix the cause, often the query or your access, then Resume.'],
        [<UI key="r">Needs reconnect</UI>, 'Waiting for you to connect your account again.'],
      ]}
    />
    <P>
      Administrators can tick <UI>Everyone&rsquo;s schedules</UI> to see everybody&rsquo;s, with each one&rsquo;s owner.
    </P>

    <Callout kind="note" title="Why Schedule might be unavailable">
      <List>
        <li>
          <UI>Scheduling isn&rsquo;t set up in this app yet</UI>: your administrators haven&rsquo;t finished{' '}
          <GuideLink to="settings" anchor="scheduling">setting it up</GuideLink>. Ask them.
        </li>
        <li><UI>Email isn&rsquo;t set up in this app yet</UI>: an emailed report needs email set up too.</li>
        <li>Run on a developer&rsquo;s own machine, schedules run as the app itself and there&rsquo;s no account to connect.</li>
      </List>
    </Callout>

    <H2 id="where-next">Where next</H2>
    <Cards cols={3}>
      <Card to="widgets" title="Using widgets">Email a widget&rsquo;s numbers once, right now.</Card>
      <Card to="widget-studio" title="Widget Studio">Add a Schedule button to a widget.</Card>
      <Card to="action-logs" title="Action Logs">Where saved schedules and statement runs are recorded.</Card>
    </Cards>
  </>
);

export const section: GuideSection = {
  id: 'schedules',
  group: 'use',
  title: 'Scheduled reports',
  summary: 'Email a widget’s results on a timetable, and manage your schedules.',
  icon: CalendarClock,
  keywords: 'schedule scheduled report recurring timetable hourly daily weekly monthly every weekday email recipients csv my schedules run now pause resume connect reconnect disconnect account oauth expires banner',
  Body,
};
