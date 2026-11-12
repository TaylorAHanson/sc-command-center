/* eslint-disable react-refresh/only-export-components -- a section exports its data (`section`) beside its body */
import { Settings } from 'lucide-react';
import type { GuideSection } from '../types';
import {
  Callout, Card, Cards, Code, Details, GuideLink, H2, Lead, List, Needs, OpenLink, P, Shot, Step, Steps, Table, UI,
} from '../kit';

const Snippet = ({ children }: { children: string }) => (
  <pre className="my-3 overflow-x-auto rounded-lg bg-gray-100 p-3 font-mono text-[13px] leading-relaxed text-gray-800">{children}</pre>
);

const VAULT_KEY_YAML = `# databricks.yml: two additions to the app's existing lists
resources:
  apps:
    sc-command-center:
      resources:
        # ...the postgres resource stays as it is
        - name: token-vault-key
          secret:
            scope: command-center
            key: token-vault-key
            permission: READ
      config:
        env:
          # ...the other variables stay as they are
          - name: TOKEN_VAULT_KEY
            valueFrom: token-vault-key`;

const SchedulingSetup = () => {
  // The redirect URL has to match this app's address exactly, so the guide shows
  // the one this browser is using rather than a placeholder.
  const callbackUrl = `${window.location.origin}/api/oauth/callback`;
  const cliJson = JSON.stringify({
    name: 'command-center-scheduling',
    redirect_urls: [callbackUrl],
    confidential: false,
    scopes: ['openid', 'email', 'offline_access', 'sql'],
    token_access_policy: { refresh_token_ttl_in_minutes: 43200 },
  });
  return (
    <>
      <H2 id="scheduling">Set up scheduling</H2>
      <P>
        <Needs role="Administrator" /> Scheduled work runs as the person who scheduled it, with their own access to data, never as the app. Each person
        connects their account once, and the app keeps that connection, encrypted, so it can act for them while they are away. Until the steps below
        are done, scheduling stays off and the <UI>Setup</UI> card lists it as not set up.
      </P>
      <Steps>
        <Step title="Create an OAuth app connection">
          A Databricks <strong>account</strong> admin opens the account console and goes to <UI>Settings</UI> → <UI>App connections</UI> →{' '}
          <UI>Add connection</UI>. It needs:
          <List>
            <li>
              Redirect URL <Code>{callbackUrl}</Code>, exactly. The <UI>Setup</UI> card shows the address it expects.
            </li>
            <li>Access scope <UI>SQL</UI>. Signing in and staying signed in come with it.</li>
            <li>
              <UI>Generate a client secret</UI> left off. The app is a public client and proves each sign-in with PKCE instead.
            </li>
            <li>
              Refresh token TTL <Code>43200</Code> minutes, which is 30 days.
            </li>
          </List>
        </Step>
        <Step title="Paste the client id">
          Copy the <UI>Client ID</UI> the new connection shows. In Settings, paste it into <UI>Scheduling</UI> → <UI>OAuth client id</UI> and click{' '}
          <UI>Save</UI>. If the TTL is not 30 days, set <UI>Connection lifetime (days)</UI> to match, so reminders to reconnect arrive before a
          connection runs out.
        </Step>
        <Step title="Give the app a vault key of its own (recommended)">
          Without one, the app derives the key that encrypts connections from its own credentials, and rotating those makes everyone connect again.
          Whoever deploys the app generates a key and stores it in a secret scope:
          <Snippet>{`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
databricks secrets create-scope command-center
databricks secrets put-secret command-center token-vault-key --string-value <the key>`}</Snippet>
          Then they give it to the app as <Code>TOKEN_VAULT_KEY</Code> through a secret resource, and deploy:
          <Snippet>{VAULT_KEY_YAML}</Snippet>
          Connections made before the key was set keep working.
        </Step>
      </Steps>
      <P>
        Click <UI>Check again</UI> on the <UI>Setup</UI> card. <UI>Scheduling</UI> reads ready once the client id is saved. A connection lasts as long
        as the TTL allows; after that, or if someone&rsquo;s access is revoked, they are asked to connect again. Moving data to another app never
        copies connections or schedules. Once it is ready, people schedule from widgets: see <GuideLink to="schedules">Scheduled reports</GuideLink>.
      </P>
      <P>
        When a connection is a week from running out, and again a day before, its owner gets an email asking them to connect again, as long as
        email is set up and they have a schedule running. If it runs out anyway, their schedules wait and start again by themselves once they
        reconnect. Two more settings under <UI>Scheduling</UI> keep schedules in check:
      </P>
      <Table
        head={['Setting', 'Starts at', 'Allowed', 'What it does']}
        rows={[
          [
            <UI key="a">Failures in a row before a schedule pauses</UI>,
            '3',
            '1 to 20',
            'A schedule that fails this many runs in a row pauses and emails its owner. Runs waiting for a reconnect, and problems with the app’s own setup, don’t count.',
          ],
          [
            <UI key="b">Most schedules per person</UI>,
            '25',
            '1 to 500',
            'Creating one more is refused. Lowering it doesn’t stop schedules that already exist.',
          ],
        ]}
      />
      <Details summary="Creating the connection from the command line">
        <P>An account admin can run this instead of using the account console:</P>
        <Snippet>{`databricks account custom-app-integration create --json '${cliJson}'`}</Snippet>
        <P>The <Code>client_id</Code> it prints is the one to paste into Settings.</P>
      </Details>
      <Details summary="A custom domain, or running the app locally">
        <P>
          The redirect URL follows the address the browser used. If people reach the app at an address other than the one registered, set{' '}
          <Code>OAUTH_REDIRECT_URI</Code> in the app&rsquo;s environment to the registered one. One connection can serve several copies of the app,
          such as development and production, if each copy&rsquo;s redirect URL is added to it. Locally, through the development server, set{' '}
          <Code>OAUTH_REDIRECT_URI</Code> to <Code>http://localhost:5174/api/oauth/callback</Code> and add that URL to the connection.
        </P>
      </Details>
      <Details summary="Schedules on a developer's machine">
        <P>
          A local run with <Code>DEV_MODE=true</Code> and <Code>APP_ENVIRONMENT=local</Code> runs every schedule as the service principal the local
          server already uses, so schedules can be tried without an OAuth connection, and the <UI>Setup</UI> card shows scheduling in dev mode.
          Both settings are needed. A deployed app never does this: it runs each schedule as its owner, or not at all.
        </P>
      </Details>
    </>
  );
};

const Body = () => (
  <>
    <Lead>
      Administrators choose which models power the AI features, set limits, and switch off what the assistant may reach, all from one page and
      without a redeploy.
    </Lead>

    <H2 id="change-settings">Change a setting</H2>
    <P>
      <Needs role="Administrator" /> Settings cover the whole app. Changes apply to new conversations and
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

    <H2 id="setup">See what is set up</H2>
    <P>
      Some features depend on setup that only your organisation&rsquo;s administrators can provide, such as an email account or a search feature
      switched on for the database. Each stays off until its setup is in place, and the rest of the app works without it.
    </P>
    <P>
      The <UI>Setup</UI> card at the top of Settings lists those features. A green tick means ready; an amber mark means not set up yet, with what
      is missing and the next step. <UI>Check again</UI> re-checks straight away, otherwise the card can lag by up to a minute. Under{' '}
      <UI>Background jobs</UI> it shows how often each timed job runs, when it last ran, and whether it failed. The card is hidden when there is
      nothing to show.
    </P>

    <SchedulingSetup />

    <H2 id="email">Set up email</H2>
    <P>
      <Needs role="Administrator" /> People can email a widget&rsquo;s numbers from its <UI>Send</UI> dialog. Email goes through your organisation&rsquo;s own
      Amazon SES account, always from one address you verify, and stays off until the steps below are done. The Setup card&rsquo;s <UI>Email</UI> row
      says which one is next.
    </P>
    <Steps>
      <Step title="Verify a sender identity in Amazon SES">
        In the AWS region you will send from, verify the address emails will come from, such as <Code>command-center@example.com</Code>, or its whole
        domain. Every email comes from that address; replies go to the person who sent it.
      </Step>
      <Step title="Request production access">
        A new SES account is in the sandbox and delivers only to addresses you have verified. Request production access for the same region.
      </Step>
      <Step title="Create an IAM user that can only send">
        Give it one permission, <Code>ses:SendEmail</Code>, on that identity alone (the address, or the domain if you verified the domain), then create an
        access key for it.
        <pre className="mt-2 overflow-x-auto rounded-lg bg-slate-900 p-3 text-xs leading-relaxed text-slate-100">{`{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "ses:SendEmail",
    "Resource": "arn:aws:ses:us-east-1:123456789012:identity/command-center@example.com"
  }]
}`}</pre>
      </Step>
      <Step title="Give the app the keys as secrets">
        Put the access key ID and secret access key in a Databricks secret scope. In your own target in <Code>databricks.yml</Code>, add them to the
        app as secret resources and name the region, then run <Code>databricks bundle deploy</Code> and <Code>databricks bundle run</Code>:
        <pre className="mt-2 overflow-x-auto rounded-lg bg-slate-900 p-3 text-xs leading-relaxed text-slate-100">{`targets:
  prod:
    resources:
      apps:
        sc-command-center:
          resources:
            - name: ses-access-key-id
              secret:
                scope: command-center
                key: aws-ses-access-key-id
                permission: READ
            - name: ses-secret-access-key
              secret:
                scope: command-center
                key: aws-ses-secret-access-key
                permission: READ
          config:
            env:
              - name: AWS_ACCESS_KEY_ID
                valueFrom: ses-access-key-id
              - name: AWS_SECRET_ACCESS_KEY
                valueFrom: ses-secret-access-key
              - name: AWS_REGION
                value: us-east-1`}</pre>
      </Step>
      <Step title="Enter the From address">
        In <UI>Settings</UI>, under <UI>Email</UI>, type the verified address into <UI>From address</UI> and click <UI>Save</UI>. The Setup
        card&rsquo;s <UI>Email</UI> row turns green.
      </Step>
    </Steps>
    <Callout kind="warn" title="AWS keys only ever go in secrets">
      Never type them into Settings, a widget or the code. The app reads them only from its environment, which is where the secret resources put them.
    </Callout>
    <Table
      head={['Setting', 'Starts at', 'What it does']}
      rows={[
        [<UI key="a">Allow email</UI>, 'On', 'Off stops all email at once and disables every Send button.'],
        [<UI key="b">From address</UI>, 'Empty', 'The verified address every email comes from. Email stays off until it is set.'],
        [
          <UI key="c">Domains email may go to</UI>,
          'Empty',
          <>Empty, each person may email only addresses in their own domain. Once you list domains, only those are allowed, so include your own. One per line; <Code>*.example.com</Code> covers subdomains.</>,
        ],
        [<UI key="d">Most recipients per email</UI>, '10', 'From 1 to 50, the most SES accepts.'],
        [<UI key="e">Most emails per person per day</UI>, '50', 'From 1 to 1,000, counted over the last 24 hours.'],
      ]}
    />
    <P>
      Each email is recorded with its sender, recipients, subject and outcome, never its body, and the send also appears in <UI>Action Logs</UI>.
    </P>
    <Details summary="Trying email on your own machine">
      <P>
        A local run (<Code>APP_ENVIRONMENT=local</Code>) without the AWS keys writes each email to <Code>backend.log</Code> instead of sending it, and the
        Setup card shows email as ready in log mode. A deployed app never does this: without the keys it says email isn&rsquo;t set up.
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
        'Shared views may only contain certified widgets. It starts off.',
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
          <UI key="e">Shared views may only contain certified widgets</UI>,
          'Nothing, because it starts off. When it is on, a view shared with anyone besides its owner can only be published while every widget on it is certified, and the Publish dialog names any that are not. Private views are never affected.',
          <>Leave it off on a development deployment, where little is certified yet. Turn it on where &ldquo;shared&rdquo; should mean &ldquo;reviewed&rdquo;. See <GuideLink to="publishing" anchor="certify">Certify a widget</GuideLink>.</>,
        ],
      ]}
    />
    <Callout kind="warn" title="Leave the Content Security Policy on">
      It is what stops widget code from sending data anywhere except this app, the approved CDNs and the Databricks Apps listed below. Report-only mode is for diagnosis, not for running.
    </Callout>
    <P>
      <strong><UI>Databricks Apps widgets may embed or call</UI></strong> is empty to start with. Add one app per line,
      either its host or its URL, such as <Code>my-app-1234567890.aws.databricksapps.com</Code>. Widgets may then show
      that app in a frame or fetch from it. To allow every app in a workspace, add{' '}
      <Code>*-&lt;workspace-id&gt;.&lt;region&gt;.databricksapps.com</Code>, such as{' '}
      <Code>*-1234567890.aws.databricksapps.com</Code>. Widgets can show those apps in a frame, but can fetch only from an app
      listed by its own host. Saving a widget that names any other app is refused. No other wildcard is accepted, because
      every Databricks customer&apos;s apps share <Code>databricksapps.com</Code>.
    </P>
    <P>
      <strong><UI>MCP servers agents can use</UI></strong> lists the servers every agent gets: the assistant uses each
      one, and Agent Studio lists their tools. It starts with SQL and Genie One. Add one per line, either a built-in
      server by name, such as <Code>system.ai.atlassian</Code> for Jira and Confluence, or a path in this workspace,
      such as <Code>/api/2.0/mcp/functions/main/sales</Code>. A pasted URL on this workspace is reduced to its path.
      Anything on another host is refused, because each server is called with the signed-in person&apos;s own access.
      Some servers, Atlassian among them, also need each person to sign in once under <UI>AI Gateway → MCPs</UI>;
      until they do, Agent Studio tells them so.
    </P>

    <H2 id="privacy">Retention and what the assistant sees</H2>
    <List>
      <li>
        <strong><UI>Delete conversations after (days)</UI></strong> deletes chats untouched for that long, with their attached files, for every user. <Code>0</Code>, the starting value, keeps them
        indefinitely. People can always delete their own from the chat drawer.
      </li>
      <li>
        <strong><UI>Delete activity events after (days)</UI></strong> deletes events on the{' '}
        <GuideLink to="access" anchor="activity">Activity</GuideLink> tab once they are that old. It starts at <Code>365</Code>;{' '}
        <Code>0</Code> keeps them indefinitely. Widget actions in Action logs are kept either way.
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
        [<UI key="b">Tool call timeout (seconds)</UI>, '90', '5 to 600', 'A SQL query or MCP call runs longer than that and the agent is told it timed out. MCP calls always get at least 30, which a Genie space needs.'],
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
    <P>
      Anyone can build an agent, so the safeguard is in how agents with Python tools are shared:
    </P>
    <List>
      <li>Give <UI>Can manage</UI> on an agent with Python tools only to people who have completed your organisation&rsquo;s secure-development training.</li>
      <li>Read a new Python tool before its agent is shared widely or with everyone in this app.</li>
    </List>
    <P>
      Administrators can find every agent, and who it is shared with, under <UI>Content</UI> in the Admin Panel. See{' '}
      <GuideLink to="access" anchor="content">Administrators &amp; access</GuideLink>.
    </P>

    <H2 id="where-next">Where next</H2>
    <Cards cols={3}>
      <Card title="Administrators & access" to="access">Decide who can open this page and the rest of the Admin Panel.</Card>
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
  keywords: 'setup background jobs not set up model genie sql retention csp content security policy certified limit timeout tokens row limit ai gateway endpoint mcp servers jira atlassian confluence email ses amazon aws secret from address recipients domains scheduling schedule oauth client id app connection redirect url refresh token connect reconnect token vault key',
  Body,
};
