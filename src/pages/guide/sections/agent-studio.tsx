/* eslint-disable react-refresh/only-export-components -- a section exports its data (`section`) beside its body */
import { Sparkles } from 'lucide-react';
import type { GuideSection } from '../types';
import {
  Lead, H2, H3, P, List, Steps, Step, Callout, Needs, Details, Shot, UI, Kbd, Table,
  GuideLink, OpenLink, Ext, Cards, Card,
} from '../kit';

const Body = () => (
  <>
    <Lead>
      An agent is an assistant with its own instructions, tools and model. You describe the one you want, an
      authoring assistant drafts it, and you review, test and save it. <Needs role="Editor on a domain" />
    </Lead>
    <P>
      An agent is a saved bundle of four things: a <strong>prompt</strong> that sets its role and rules,
      optional <strong>skills</strong> (named blocks of extra guidance), the <strong>tools</strong> it may use,
      and optional small <strong>Python tools</strong> you write for it. Once saved, it appears in the agent
      picker of the <GuideLink to="assistant">assistant</GuideLink> for everyone it is shared with. Building one
      needs Editor access in at least one domain; see <GuideLink to="roles">Roles and permissions</GuideLink>.
    </P>

    <H2 id="first-agent">Build your first agent</H2>
    <Steps>
      <Step title="Open the studio">
        <P>
          Click <UI>Agent Studio</UI> in the sidebar, or <OpenLink page="agent-studio">open it here</OpenLink>. The
          chat is on the left and the agent's tabs are on the right: <UI>Prompt</UI>, <UI>Skills</UI>,{' '}
          <UI>Python tools</UI>, <UI>Try it</UI>, <UI>Review</UI> and <UI>Settings</UI>.
        </P>
        <Shot
          name="agent-overview"
          alt="Agent Studio with the authoring chat on the left and the agent's tabs on the right"
          caption="A new agent, before anything is drafted."
          legend={[
            'The authoring chat. Describe the agent here.',
            'New agent, Open and Save.',
            'The agent\'s tabs.',
            'The Prompt tab, with the agent\'s instructions.',
          ]}
        />
      </Step>
      <Step title="Describe the agent">
        <P>
          Type what it should do and what data it should reach, then press <Kbd>Enter</Kbd>. For example: "Build
          an agent that answers supply-chain questions from the orders table." While it works the chat shows
          Designing agent….
        </P>
      </Step>
      <Step title="Review the draft">
        <P>
          The draft fills the tabs. Read the <UI>Prompt</UI>, then open <UI>Review</UI> to see which tools it
          suggests and what it could not find. Ask the chat for changes; it refines the draft rather than
          starting again.
        </P>
      </Step>
      <Step title="Choose its tools">
        <P>
          Open <UI>Settings</UI> and tick the tools the agent should have, under <UI>Tools (AI Gateway MCP)</UI>.
          Start with <UI>SQL</UI> or <UI>Genie</UI>; the full picker is described{' '}
          <GuideLink to="agent-studio" anchor="tools">below</GuideLink>.
        </P>
      </Step>
      <Step title="Try it">
        <P>
          Open <UI>Try it</UI> and ask the agent a real question. It runs your current draft, unsaved edits
          included, with tools limited to what you can reach. Nothing is saved from this chat. <UI>Clear</UI>{' '}
          empties it.
        </P>
        <Shot
          name="agent-try-it"
          alt="The Try it tab for a new unsaved draft"
          caption="Try it, with a draft that has not been saved yet."
          legend={['The Try it tab.']}
        />
      </Step>
      <Step title="Name it, share it and save">
        <P>
          Back in <UI>Settings</UI>, give it an <UI>Agent Name</UI> (required), a <UI>Description</UI> and a{' '}
          <UI>Sharing</UI> choice, then click <UI>Save</UI>. The button reads Saved when it is done.
        </P>
      </Step>
      <Step title="Use it">
        <P>
          Open the assistant, pick the agent from its picker and ask a question. To make a view open with the
          agent, see{' '}
          <GuideLink to="agent-studio" anchor="use-and-pin">Use and pin an agent</GuideLink>.
        </P>
      </Step>
    </Steps>

    <H2 id="settings">Name, model and sharing</H2>
    <P>
      The agent's name and description live on the <UI>Settings</UI> tab, and the name also sits above the tabs.
      Click it to jump to <UI>Settings</UI>.
    </P>
    <Table
      head={['Setting', 'What it does']}
      rows={[
        [<UI key="n">Agent Name</UI>, 'Required to save. Shown in the assistant\'s agent picker.'],
        [<UI key="d">Description</UI>, 'A line about what the agent is for. Shown beside the name in the Open menu.'],
        [<UI key="m">Model</UI>, 'A searchable list of the models in your workspace. Leave it blank to follow the deployment default an admin sets under Settings.'],
        [<UI key="s">Sharing</UI>, 'Who can use the agent. See below.'],
      ]}
    />
    <Table
      head={['Sharing', 'Who can use it', 'Who can save it']}
      rows={[
        [<UI key="p">Personal</UI>, 'Only you.', 'Anyone who can open Agent Studio. No domain role is needed.'],
        [<UI key="dm">Domain</UI>, 'Anyone with access to the domain you pick. A domain picker appears.', 'Editors of that domain.'],
        [<UI key="g">Global</UI>, 'Every user of the app.', 'Global admins only. The option is greyed out for everyone else.'],
      ]}
    />
    <List>
      <li><UI>Unsaved changes</UI> appears beside the name while you have edits that are not saved. <UI>New agent</UI> and <UI>Open</UI> ask before they throw those edits away.</li>
      <li><UI>Open</UI> lists every agent you can reach. Agents other people shared with you carry a <UI>Shared</UI> badge and the author's name.</li>
      <li>The <UI>New conversation</UI> icon above the chat clears the conversation but keeps the agent you are editing. <UI>New agent</UI> starts over.</li>
      <li>If someone else saved the agent while you were editing it, saving is refused with a message to reload first.</li>
      <li><UI>Delete agent</UI>, at the bottom of <UI>Settings</UI>, removes the agent with its skills and Python tools for you and everyone it is shared with. It asks first.</li>
    </List>

    <Shot
      name="agent-model-visibility"
      alt="The Settings tab showing the Model and Sharing fields"
      caption="Model and sharing on the Settings tab."
      legend={[
        'Model. Blank follows the deployment default.',
        'Sharing: Personal, Domain or Global.',
        'The domain picker, shown when Sharing is Domain.',
      ]}
    />

    <H2 id="authoring-assistant">Draft and review with the authoring assistant</H2>
    <P>
      The chat on the left is the authoring assistant. It reads your request and the current draft, then writes
      or revises the prompt, skills, tool choices and Python tools. Everything it proposes lands in the tabs on
      the right, where you can edit it by hand.
    </P>
    <H3 id="research">It researches your data first</H3>
    <P>
      So that the prompt describes your data accurately, the assistant can look at it while it drafts. It
      confirms that tables and columns exist, runs read-only SQL to learn things like which status values are
      really used, and can ask Genie what a business term means in your workspace. Both run as you, so it sees
      only what you may see. These are tools for writing the agent. They are not added to the agent; its own
      tools are the ones you pick.
    </P>
    <H3 id="review">The Review tab</H3>
    <Table
      head={['Section', 'What it tells you']}
      rows={[
        [<UI key="a">Suggested tools</UI>, 'The tools it thinks the agent needs, and why.'],
        [<UI key="b">Missing capabilities</UI>, 'Things you asked for that no available tool provides.'],
        [<UI key="c">Open questions</UI>, 'Points in your request it could not settle by itself.'],
        [<UI key="d">Schema checks</UI>, 'The queries it ran against your tables, marked OK or FAILED, with the columns found.'],
        [<UI key="e">Python tool safety</UI>, 'Its notes on any Python tool it wrote.'],
      ]}
    />
    <Shot
      name="agent-review"
      alt="The Review tab before the assistant has drafted anything"
      caption="The Review tab is empty until the assistant has designed or refined an agent."
      legend={[
        'The Review tab.',
        'The note shown until there is a review.',
        'The message box for the authoring assistant.',
      ]}
    />
    <P>
      When you edit the draft after a review, the tab reads <UI>Review • stale</UI>. Ask the assistant to refine
      the agent to refresh it.
    </P>
    <Details summary="When a draft does not arrive">
      <P>
        A long research turn can take minutes. The send button turns into <UI>Stop</UI> while the assistant
        works. If its reply describes an agent
        but the draft was cut off or unreadable, a note in the chat says so and the tabs stay as they were. An
        admin can raise the Agent Studio response length limit in{' '}
        <GuideLink to="settings">Settings</GuideLink> when drafts keep getting cut off.
      </P>
    </Details>

    <H2 id="tools">Choose tools</H2>
    <P>
      The tool list on <UI>Settings</UI> shows what you can reach as yourself in the workspace the app runs in.
      Every agent also has a tool for looking up how the Command Center itself works; it is always attached and
      is not listed.
    </P>
    <H3 id="source-chips">Source chips</H3>
    <P>
      The chips above the list show or hide one kind of tool each, with a count. Only <UI>SQL</UI> and{' '}
      <UI>Genie</UI> start switched on, because the other kinds can number in the hundreds. Click a chip to
      turn it on. Your choice is remembered in this browser.
    </P>
    <Table
      head={['Chip', 'What is in it']}
      rows={[
        [<UI key="1">SQL</UI>, 'Running SQL on the app\'s warehouse. Starts on.'],
        [<UI key="2">Genie</UI>, 'The general Genie tools. Starts on.'],
        [<UI key="3">Genie spaces</UI>, 'One tool per Genie space you can open, listed under the space\'s own name with a Genie space tag. Starts off.'],
        [<UI key="4">UC functions</UI>, 'Unity Catalog functions you can reach. Starts off.'],
        [<UI key="5">Vector search</UI>, 'Vector search indexes you can reach. Starts off.'],
        [<UI key="6">External</UI>, 'External MCP connections you can reach. Starts off.'],
        [<UI key="7">AI Gateway</UI>, 'AI Gateway services. Starts off. Appears only when an admin has set one up for this app.'],
        [<UI key="8">Custom apps</UI>, 'Custom MCP apps. Starts off. Appears only when an admin has set one up for this app.'],
        [<UI key="9">Other</UI>, 'Anything that fits none of the above. Starts off.'],
        [<UI key="10">Internal</UI>, 'Tools the app drives itself, such as Genie\'s poll tool. Shown for reference; they cannot be attached. Starts off.'],
      ]}
    />
    <Shot
      name="agent-tools"
      alt="The tool list on the Settings tab with source chips, a filter box and Refresh"
      caption="The tool list. Counts are for one example workspace; yours will differ."
      legend={[
        'Filter tools by name or description.',
        'The source chips. SQL and Genie are on; the others are off.',
        'Refresh asks Databricks for the list again.',
      ]}
    />
    <List>
      <li>A chip only appears when it has at least one tool for you, so a kind can be missing entirely.</li>
      <li>A tool you have ticked stays in the list whatever the chips and the filter say, so you never save an agent with tools you cannot see.</li>
      <li>When tools are hidden by a chip, a line under the list says how many.</li>
      <li><UI>Filter tools by name or description…</UI> narrows the list; the counter beside the heading shows how many you have selected.</li>
      <li>If a tool you ticked earlier no longer shows up for you, an amber line names it under the list as selected but not currently discoverable.</li>
    </List>
    <H3 id="what-you-see">What you see, and Refresh</H3>
    <P>
      The list comes from your own access. A colleague with different permissions sees a different list, and you
      may find a kind empty. Genie spaces, functions and indexes in a different Databricks workspace are not
      listed.
    </P>
    <P>
      The list is kept for about five minutes. If you have just been given access to a new Genie space, click{' '}
      <UI>Refresh</UI> beside the heading to ask again. Listing functions can start the SQL warehouse, so a
      refresh may take longer the first time.
    </P>
    <Shot
      name="agent-tools-genie"
      alt="The Genie spaces chip turned on, with spaces listed under their own names"
      caption="With Genie spaces on, each space shows under its real name."
      legend={[
        'The Genie spaces chip, turned on.',
        'A space, listed under its own name with a Genie space tag.',
      ]}
    />
    <Details summary="Genie spaces and Internal tools">
      <P>
        A Genie space is listed under its real title. Each space has a second, hidden tool for polling its
        answer, which the app drives itself. Turn on <UI>Internal</UI> and it appears greyed out, named like{' '}
        <em>Space name · poll response</em>, so that it does not look like a second copy of the space. You do
        not need it: the app waits for Genie's answer on its own.
      </P>
      <Shot
        name="agent-tools-internal"
        alt="The Internal chip turned on, showing a greyed-out poll response tool under each Genie space"
        caption="With Internal on, each space's poll tool appears greyed out."
        legend={[
          'The Internal chip, turned on.',
          'A space you can attach.',
          'Its poll tool, greyed out and not selectable.',
        ]}
      />
    </Details>
    <Callout kind="admin" title="Switches that override an agent">
      <P>
        An admin can switch Genie or SQL off for the whole app under Admin Panel → Settings. A tool that is off
        stays off even if an agent lists it, and Agent Studio's research stops using it too. See{' '}
        <GuideLink to="settings">Settings and models</GuideLink>.
      </P>
    </Callout>
    <P>
      To learn about the tools themselves, see the Databricks docs for{' '}
      <Ext href="https://docs.databricks.com/aws/en/genie/">Genie</Ext> and{' '}
      <Ext href="https://docs.databricks.com/aws/en/generative-ai/mcp/managed-mcp">managed MCP servers</Ext>.
    </P>

    <H2 id="python-tools">Python tools and skills</H2>
    <P>
      <UI>Skills</UI> are named markdown blocks of guidance, each with a name, a one-line description and its own
      text. Add one with <UI>Add</UI>, or ask the assistant to write it. The agent can load a skill when it
      needs it.
    </P>
    <P>
      A <UI>Python tool</UI> is a single function the agent can call. Use one for a calculation or a rule that
      SQL and Genie do not cover. Give it a name and a one-line description, then write the code in the editor;
      the assistant can draft one and test it before it proposes it.
    </P>
    <Callout kind="warn" title="Python tools run on the server">
      <P>
        A tool runs in a restricted process with the app's credentials removed and limits on time and memory.
        That stops common accidents, but it is a validation sandbox, not a lock, and it does not replace
        reading the code. Keep tools pure and deterministic, never put credentials or tokens in the code, and
        pass data in as arguments. Read a new Python tool before you share its agent with a domain or everyone.
        Admins decide who gets Editor access, which is what allows authoring; the guidance is in{' '}
        <GuideLink to="settings">Settings and models</GuideLink>.
      </P>
    </Callout>

    <H2 id="use-and-pin">Use and pin an agent</H2>
    <P>
      Anyone an agent is shared with picks it in the <GuideLink to="assistant">assistant</GuideLink>'s agent
      picker. To make a view open with a particular agent, pin it from the
      assistant panel or under <UI>Settings → Assistant</UI> on the view; the steps and the warnings the panel
      shows are in <GuideLink to="assistant">The assistant</GuideLink> and{' '}
      <GuideLink to="views">Views</GuideLink>. Pinning needs permission to change the view, and a pin is a
      starting point, not a lock.
    </P>
    <Callout kind="note" title="Agents have no versions or promotion">
      <P>
        Agent Studio shows only the latest saved agent. It has no history, restore or Promote button. An agent
        belongs to the workspace (Dev, Test or Prod) you saved it in. When you promote a view that pins an agent,
        the promotion warns you if the target workspace does not have it; save the agent again there, or pin
        another one. See <GuideLink to="promotion">Promoting work</GuideLink>.
      </P>
    </Callout>
    <P>
      Admins can copy every agent between apps with data migration. See{' '}
      <GuideLink to="migration">Moving data to another app</GuideLink>.
    </P>

    <H2 id="where-next">Where next</H2>
    <Cards cols={3}>
      <Card title="The assistant" to="assistant">Pick an agent and pin one to a view.</Card>
      <Card title="Settings and models" to="settings">Models, limits and switches that apply to every agent.</Card>
      <Card title="Roles and permissions" to="roles">Who can build and share agents.</Card>
    </Cards>
    <P>
      <OpenLink page="agent-studio">Open Agent Studio</OpenLink>
    </P>
  </>
);

export const section: GuideSection = {
  id: 'agent-studio',
  group: 'build',
  title: 'Agent Studio',
  summary: 'Build an assistant with its own instructions, model and tools.',
  icon: Sparkles,
  keywords: 'create agent assistant prompt skills tools genie sql python tool sandbox sharing personal domain global pin model mcp',
  Body,
};
