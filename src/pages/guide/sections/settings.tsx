/* eslint-disable react-refresh/only-export-components -- a section exports its data (`section`) beside its body */
import { Settings } from 'lucide-react';
import type { GuideSection } from '../types';
import {
  Callout, Card, Cards, Code, Details, GuideLink, H2, Lead, List, Needs, OpenLink, P, Shot, Step, Steps, Table, UI,
} from '../kit';

const Body = () => (
  <>
    <Lead>
      Global admins choose which models power the AI features, set limits, and switch off what the assistant may reach, all from one page and
      without a redeploy.
    </Lead>

    <H2 id="change-settings">Change a setting</H2>
    <P>
      <Needs role="Global admin" /> Settings cover the whole app, whichever <UI>Workspace</UI> is selected. Changes apply to new conversations and
      generations, not to ones already running.
    </P>
    <Steps>
      <Step title="Open Settings">
        Go to <OpenLink page="admin">Admin Panel</OpenLink> and choose the <UI>Settings</UI> tab.
        <Shot
          name="admin-settings"
          alt="The Settings page with cards for Models, What the assistant may reach, and limits"
          caption="Settings. Each card groups related fields; a label above each field says where its value comes from."
          legend={[
            'The four model pickers. The label on the right says "Set here" or "Built-in default"; the line under each shows what Reset returns it to.',
            'A switch that removes a whole kind of tool from the assistant, here Genie.',
          ]}
        />
      </Step>
      <Step title="Edit the fields you want">
        Change a model name, a number or a switch. Switches read <UI>Allowed</UI> or <UI>Blocked</UI>.
      </Step>
      <Step title="Save">
        Click <UI>Save</UI>. The button shows how many changes it holds, and reads <UI>Saved</UI> when nothing is pending. A value outside a field&rsquo;s range is refused with a message.
      </Step>
    </Steps>
    <Details summary="Where a value comes from">
      <P>The label above each field tells you:</P>
      <List>
        <li><UI>Set here</UI>: an admin chose it on this page.</li>
        <li><UI>From the deployment configuration</UI>: the app was deployed with a value, and nobody has overridden it.</li>
        <li><UI>Built-in default</UI>: nothing has been set anywhere.</li>
      </List>
      <P>
        A value set here wins over the deployment configuration, which wins over the built-in default. Model fields have a{' '}
        <UI>Reset to</UI> link that puts back the value from the deployment. <UI>Reload</UI>, at the top, discards your unsaved edits and shows what the server holds.
      </P>
    </Details>

    <H2 id="models">Choose the models</H2>
    <P>
      Each model field suggests the chat models your Databricks workspace offers. You can also type a name that is not listed.
    </P>
    <Table
      head={['Setting', 'What it powers']}
      rows={[
        [<UI key="a">Chat agent model</UI>, 'The assistant panel. An agent saved in Agent Studio can pin its own model, which wins for that agent only.'],
        [<UI key="b">Widget generation model</UI>, 'Writes widget code in Widget Studio. Prefer a model with a large output budget, because long widgets suffer most from a small one.'],
        [
          <UI key="c">Widget helper model</UI>,
          <>
            Widget Studio&rsquo;s quick jobs: summarising a long conversation so it stays affordable, and deciding whether a big request is worth a question first. Your own request always
            goes to the generation model exactly as you wrote it. It starts as <Code>system.ai.gpt-6-luna</Code>. If your workspace does not serve it, the generation model is used instead.
            Enter that model&rsquo;s name here to use it on purpose.
          </>,
        ],
        [<UI key="d">Agent authoring model</UI>, 'Drafts and reviews agents in Agent Studio.'],
      ]}
    />
    <Details summary="Two kinds of model name">
      <P>
        Names beginning <Code>system.ai.</Code> are called through the AI Gateway. Plain endpoint names go straight to a serving endpoint. Both work: the app
        picks the route from the name, so you never choose one. Parameters a model refuses are dropped automatically.
      </P>
      <P>
        <UI>Model parameter overrides</UI> sits in the same card. Leave it empty unless a specific model needs an extra parameter. It takes JSON per model, and{' '}
        <Code>null</Code> stops a parameter being sent.
      </P>
    </Details>
    <P>
      Which tools an agent may use is chosen per agent, in <GuideLink to="agent-studio">Agent Studio</GuideLink>.
    </P>

    <H2 id="reach">Control what the assistant may reach</H2>
    <P>
      The <UI>What the assistant may reach</UI> card switches capabilities off for the whole deployment. A tool that is off is not offered to the assistant at all, so it
      does not try to use it or explain a refusal. An agent saved in Agent Studio cannot turn one back on by listing it.
    </P>
    <Shot
      name="admin-settings-reach"
      alt="The What the assistant may reach and Retention and context cards"
      caption="What the assistant may reach, and Retention and context."
      legend={[
        'Allow the assistant to query Genie.',
        'Allow the assistant to run SQL.',
        'Global views may only contain certified widgets. It starts off.',
        'Delete conversations after (days). 0 keeps them indefinitely.',
      ]}
    />
    <Table
      head={['Switch', 'What stops when it is off', 'Turn it off when']}
      rows={[
        [
          <UI key="a">Allow the assistant to query Genie</UI>,
          'Every Genie tool in the assistant, and Genie research in Widget Studio and Agent Studio.',
          'Genie spaces can see data the assistant must not read. Unity Catalog policies that limit other callers cannot tell Genie apart, so this switch is the control that works.',
        ],
        [
          <UI key="b">Allow the assistant to run SQL</UI>,
          'The SQL and Unity Catalog tools, and SQL research in the studios. Widgets themselves keep working.',
          'The assistant should answer questions about the app, not touch data.',
        ],
        [
          <UI key="c">Send images and PDFs to the model directly</UI>,
          'Uploading raw images and PDFs to the model. Attachments are read only by text extraction, so scanned documents and screenshots stop working.',
          'No raw file may leave for the model.',
        ],
        [
          <UI key="d">Enforce the Content Security Policy</UI>,
          'Blocking. The policy becomes report-only: violations are logged in the browser console instead of blocked.',
          'Only to diagnose a widget that has stopped rendering. Turn it back on afterwards.',
        ],
        [
          <UI key="e">Global views may only contain certified widgets</UI>,
          'Nothing, because it starts off. When it is on, a view shared with everyone can only hold certified widgets, and saving one with others is refused.',
          <>Leave it off in Dev and Test, where nothing is certified yet. Turn it on where &ldquo;shared with everyone&rdquo; should mean &ldquo;reviewed&rdquo;. See <GuideLink to="promotion" anchor="certify">Certify a widget</GuideLink>.</>,
        ],
      ]}
    />
    <Callout kind="warn" title="Leave the Content Security Policy on">
      It is what stops widget code from sending data anywhere except this app, the approved CDNs and the Databricks Apps listed below. Report-only mode is for diagnosis, not for running.
    </Callout>
    <P>
      <strong><UI>Databricks Apps widgets may embed or call</UI></strong> is empty to start with. Add one app per line,
      either its host or its URL, such as <Code>my-app-1234567890.aws.databricksapps.com</Code>. Widgets may then show
      that app in a frame or fetch from it. Saving a widget that names any other app is refused. Wildcards aren&apos;t
      accepted, because every Databricks customer&apos;s apps share <Code>databricksapps.com</Code>.
    </P>

    <H2 id="privacy">Retention and what the assistant sees</H2>
    <List>
      <li>
        <strong><UI>Delete conversations after (days)</UI></strong> deletes chats untouched for that long, with their attached files, for every user. <Code>0</Code>, the starting value, keeps them
        indefinitely. People can always delete their own from the chat drawer.
      </li>
      <li>
        <strong><UI>Tell the assistant what is on screen</UI></strong> controls whether each question carries a summary of the current dashboard: widget names, titles and
        configuration. Off, the assistant sees only the question. Choose that where widget configuration is itself sensitive.
      </li>
    </List>

    <H2 id="limits">Limits</H2>
    <P>
      Each is a ceiling, so raising it costs nothing until something needs the room.
    </P>
    <Shot
      name="admin-settings-limits"
      alt="The Chat agent limits, Studio limits and Other limits cards"
      caption="The limits, near the bottom of Settings."
      legend={[
        'Chat agent limits.',
        'Studio limits.',
        'Most rows one widget query can return, under Other limits.',
        'Save. It is disabled until you change something.',
      ]}
    />
    <Table
      head={['Setting', 'Starts at', 'Allowed', 'Raise it if…']}
      rows={[
        [<UI key="a">Response length limit (tokens)</UI>, '16,000', '256 to 128,000', 'Long chat answers are cut off. Models that allow less are clamped to their own limit.'],
        [<UI key="b">Tool call timeout (seconds)</UI>, '90', '5 to 600', 'A SQL query or MCP call runs longer than that and the agent is told it timed out.'],
        [<UI key="c">Genie query timeout (seconds)</UI>, '150', '10 to 900', 'You use large warehouses. Genie is polled until this runs out.'],
        [<UI key="d">Widget response length limit (tokens)</UI>, '16,000', '1,000 to 128,000', 'You want fewer round trips. A cut-off reply is continued automatically anyway.'],
        [<UI key="e">Widget generation timeout (seconds)</UI>, '300', '30 to 1,800', 'Large widgets give up before they finish.'],
        [<UI key="f">Agent Studio response length limit (tokens)</UI>, '16,000', '1,000 to 128,000', 'An agent draft fails to parse. A low ceiling cuts the draft off mid-way.'],
        [<UI key="g">Tool calls per turn</UI>, '8', '1 to 30', 'Answers that need several queries stop short. Lower it to cap the cost of one question.'],
        [<UI key="h">Most rows one widget query can return</UI>, '1,000,000', '1,000 to 10,000,000', 'A widget that works on the whole result says it is showing only part of the data.'],
      ]}
    />
    <P>
      A deployment can start with different values, so check the label above a field before you assume. Tool calls per turn and the row limit are under <UI>Other limits</UI> at the bottom of the page.
    </P>

    <H2 id="python-tools">Who should author Python tools</H2>
    <P>
      A Python tool written in <GuideLink to="agent-studio">Agent Studio</GuideLink> runs on the server whenever its agent decides to call it. It runs in a restricted subprocess with the
      app&rsquo;s credentials removed and limits on time and memory. That prevents the common accidents, but it is a validation sandbox, not a jail, and it does not replace review.
    </P>
    <List>
      <li>Give the Editor rights that allow Python tool authoring only to people who have completed your organisation&rsquo;s secure-development training.</li>
      <li>Read a new Python tool before its agent is given domain or global visibility.</li>
    </List>
    <P>
      Editor rights are given in <GuideLink to="access">Managing access</GuideLink>.
    </P>

    <H2 id="where-next">Where next</H2>
    <Cards cols={3}>
      <Card title="Managing access" to="access">Decide who can open this page and others.</Card>
      <Card title="Agent Studio" to="agent-studio">Choose the model and tools for one agent.</Card>
      <Card title="Moving data to another app" to="migration">Carry settings to another deployment.</Card>
    </Cards>
  </>
);

export const section: GuideSection = {
  id: 'settings',
  group: 'admin',
  title: 'Settings & models',
  summary: 'Choose models, limits and what the assistant may reach.',
  icon: Settings,
  keywords: 'model genie sql retention csp content security policy certified limit timeout tokens row limit ai gateway endpoint',
  Body,
};
