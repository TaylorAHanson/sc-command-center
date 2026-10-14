/* eslint-disable react-refresh/only-export-components -- a section exports its data (`section`) beside its body */
import { Bot } from 'lucide-react';
import type { GuideSection } from '../types';
import { Callout, Card, Cards, Details, GuideLink, H2, H3, Kbd, Lead, List, P, Shot, Step, Steps, Table, UI } from '../kit';

const Body = () => (
  <>
    <Lead>
      The assistant answers questions about the view you are on, your data and the Command Center itself. It runs with
      your own Databricks permissions, so it shows what you are allowed to see and nothing more.
    </Lead>

    <Callout kind="warn" title="Check what it tells you">
      Answers come from an AI model. They can be wrong, and they can be wrong with confidence. Check anything you plan
      to act on against its source. Your conversations are saved to your history and may be kept by your administrator.
      The notice under the message box says both.{' '}
      <GuideLink to="assistant" anchor="trust">What to trust</GuideLink>
    </Callout>

    <H2 id="ask-a-question">Ask a question</H2>
    <Steps>
      <Step>
        Click the assistant button at the bottom right. It is named after the agent you are talking to, "EDH Agent" by
        default. The panel opens down the right side.
      </Step>
      <Step>
        Type in the box that says <UI>Ask about your dashboard…</UI> and press <Kbd>Enter</Kbd>. Press{' '}
        <Kbd>Shift</Kbd>+<Kbd>Enter</Kbd> for a new line. The box grows as you type.
      </Step>
      <Step>
        Watch it work. A <UI>Thinking…</UI> note shows its reasoning as it goes and becomes <UI>Thoughts</UI> when it
        finishes; click it to read it. Under an answer, <UI>Tools used</UI> lists the tools it ran.
      </Step>
    </Steps>
    <Shot
      name="use-assistant-panel"
      alt="The assistant panel with the agent picker, header buttons and message box"
      narrow
      legend={[
        'The agent picker.',
        'Pin: make the view open with this agent.',
        'Past conversations.',
        'New conversation. The button beside it collapses the panel.',
        'Attach a file.',
      ]}
    />
    <P>
      The note under the message box says how many widgets the assistant can see on your tab ("Sees 3 widgets on this
      tab"). That is what lets you ask "what does this table show?" without describing it. Drag the left edge of the
      panel to make it wider or narrower, and use the collapse button in the header to close it. Your conversation
      survives closing the panel.
    </P>
    <Shot
      name="use-assistant-answer"
      alt="An answer in the assistant panel with its tools used"
      caption="An answer, with the tools it used listed beneath."
    />
    <Details summary="What the assistant can do">
      <List>
        <li>Explain the widgets on your tab and answer questions about the Command Center itself.</li>
        <li>
          Query your data with the tools it has: running SQL and asking Genie spaces, as you. Unity Catalog decides
          which tables and Genie spaces it can reach, so two people asking the same question can correctly get
          different answers.
        </li>
        <li>Read files you attach, and draw charts from data it has just retrieved.</li>
        <li>
          Use extra tools that an author gave a particular agent in{' '}
          <GuideLink to="agent-studio">Agent Studio</GuideLink>.
        </li>
      </List>
      <P>
        A permission error from a tool describes your access, not the assistant's. You never need to give it a password
        or token.
      </P>
    </Details>

    <H2 id="stop-an-answer">Stop an answer</H2>
    <P>
      While the assistant works, the send button turns into a red <UI>Stop</UI> button. Click it to end the turn: no
      more tools run, and what was already written stays, marked <em>Stopped</em>. Pressing <Kbd>Enter</Kbd> never
      stops it, so you can type your next question while it works. Reloading the page or opening another conversation
      does not stop it either. The answer is saved and waiting when you return.
    </P>

    <H2 id="attach-files">Attach files</H2>
    <Steps>
      <Step>
        Click the paperclip, drag a file onto the panel, or paste a screenshot or copied image into the message box with{' '}
        <Kbd>Ctrl</Kbd>+<Kbd>V</Kbd> (<Kbd>Cmd</Kbd>+<Kbd>V</Kbd> on a Mac). A pasted image is named "Pasted image" with
        the time. If the clipboard also holds text, as cells copied from Excel do, the text is pasted instead.
      </Step>
      <Step>
        Wait for the chip above the message box to change from reading the file to describing it, such as "5,000 rows x
        6 columns". The X on the chip removes the file.
      </Step>
      <Step>Ask your question. The file stays available for the rest of that conversation.</Step>
    </Steps>
    <Table
      head={['Limit', 'Value']}
      rows={[
        ['File types', 'Spreadsheets and CSVs, PDFs, Word documents, JSON, text and images (PNG, JPG, WEBP, GIF).'],
        ['Size', 'Up to 25 MB each.'],
        ['Number', 'Five per conversation.'],
        ['Who sees them', 'Only you. Deleting the conversation deletes its files.'],
      ]}
    />
    <Details summary="How the assistant reads a file">
      <List>
        <li>
          A spreadsheet or CSV: it sees the sheets, columns, row counts and a few sample rows, then queries the file. Totals
          and counts come from every row, not a sample, however large the file.
        </li>
        <li>A document: it finds the passages that bear on your question and cites the page.</li>
        <li>An image or a short PDF: it reads it directly, so charts, screenshots and scanned pages work.</li>
        <li>
          If a file will not read, the chip says so. The usual causes are a scanned PDF with no text, a password-protected
          file, or a type not listed above.
        </li>
      </List>
    </Details>

    <H2 id="charts">Get a chart</H2>
    <P>
      When a picture explains an answer better, such as a trend, a comparison or a breakdown, the assistant draws a chart
      in the conversation from the data it just retrieved. If it does not offer one, ask: "chart that by month". The
      menu on a chart saves it as PNG or SVG. Agents built in Agent Studio can chart the same way. Charts use only data
      already in the answer.
    </P>
    <P>
      Pictures in answers show only when they come from this app. One from another site appears as a small "image from
      … not loaded" placeholder, so an answer cannot pass your data to that site just by displaying an image.
    </P>

    <H2 id="agents">Choose an agent</H2>
    <P>
      The picker at the top of the panel, labelled <UI>Active agent</UI> when you hover it, sets which agent answers.{' '}
      <UI>EDH Agent (default)</UI> is the built-in one. Agents other people or you saved in{' '}
      <GuideLink to="agent-studio">Agent Studio</GuideLink> are listed below it with where they come from, such as "shared
      by" the person who made them. Pick one to talk to it. Hover the picker to see how many widgets it can see on your
      tab. Choosing a different agent starts a new conversation and leaves the old one in your history.
    </P>
    <P>
      An agent is a saved set of instructions and tools. Authoring and sharing them is in{' '}
      <GuideLink to="agent-studio">Agent Studio</GuideLink>, which needs editor access.
    </P>
    <H3 id="pin-an-agent">Make a view open with an agent</H3>
    <P>
      The pin beside the picker makes the view open with the agent now selected. It is there for anyone who may change
      the view's settings, and not on a view that opens on its own.
    </P>
    <Steps>
      <Step>Pick the agent in the picker.</Step>
      <Step>
        Click the pin. On a view with one tab it pins at once. With several tabs a menu asks{' '}
        <UI>This tab</UI> or <UI>Every tab of</UI> the view. A tab's own pin wins on that tab.
      </Step>
      <Step>Click a ticked choice, or the pinned pin, to unpin.</Step>
    </Steps>
    <P>
      <UI>Settings → Assistant</UI> sets the same pin, and has <UI>No agent</UI> to remove the assistant from the view.
      A pin is a starting point, not a lock: anyone can still switch agents while they are on the view. See{' '}
      <GuideLink to="views" anchor="settings-assistant">View settings</GuideLink>.
    </P>
    <Details summary="The notes the panel can show">
      <Table
        head={['Note at the top of the panel', 'What it means']}
        rows={[
          [<em>The agent</em>, 'is pinned to this view. You are on a different agent now, but the view opens with its pinned one.'],
          ['Pinned to this tab / this view.', 'Shown on a view with several tabs, when you are on the pinned agent.'],
          ['This agent is private, so others on this view still get the EDH Agent.', 'You pinned an agent only you can open. Everyone else sees the default.'],
          ['This view is pinned to an agent you can\u2019t open, so it stays on the one above.', 'Someone pinned an agent you do not have access to.'],
        ]}
      />
    </Details>

    <H2 id="conversations">Keep, reopen and delete conversations</H2>
    <P>
      Conversations are saved as you go. Reload the browser or come back tomorrow and the last one reopens where you left
      off. Nobody else sees your conversations in the app.
    </P>
    <Shot
      name="use-assistant-history"
      alt="The list of past conversations opened from the clock icon"
      caption="Past conversations, with Rename and Delete on hover."
    />
    <List>
      <li>
        <UI>Past conversations</UI> (the clock icon) lists your recent ones with how long ago and how many messages.
        Click one to reopen it.
      </li>
      <li>
        Hover a row for the pencil (<UI>Rename</UI>) and the bin (<UI>Delete conversation</UI>). In rename, press{' '}
        <Kbd>Enter</Kbd> to save or <Kbd>Esc</Kbd> to cancel. Deleting takes the conversation and its files at once.
      </li>
      <li>
        <UI>New conversation</UI> (the speech-bubble icon) starts a fresh one and keeps the current one in the list.
      </li>
      <li>
        <UI>Delete all my conversations</UI> at the bottom of the list removes every conversation you own with its
        files. It asks once, and it cannot be undone.
      </li>
      <li>The 50 most recent are kept; older ones are removed automatically.</li>
    </List>
    <P>
      Your administrator may also set a retention period. When they do, any conversation left untouched that long is
      deleted for everyone, files included.
    </P>

    <H2 id="trust">What to trust, and what limits it</H2>
    <Callout kind="warn" title="Generated answers need checking">
      The model writes the words; your data supplies the figures. Where the assistant ran a tool, it says so, and those
      figures came from your data. Anything else is the model's own prose, so check it before you act on it.
    </Callout>
    <List>
      <li>Two people can get different answers to the same question, because each is limited to their own access.</li>
      <li>
        The model that writes the reply runs as the app, not as you, because per-person access to models proved
        unreliable. It reads no data of yours on that path; every tool call still runs as you.
      </li>
      <li>
        If a question is about something it cannot reach, it should say so. Ask it what it can do with the access it has.
      </li>
    </List>
    <Callout kind="admin" title="What administrators can narrow">
      An administrator can switch off, for the whole deployment: asking Genie, running SQL, sending images and PDFs
      directly to the model, and telling the assistant what is on your screen. If the assistant says it cannot do
      something, one of these is usually why. With the last one off it cannot answer "what am I looking at". See{' '}
      <GuideLink to="settings">Admin settings</GuideLink>.
    </Callout>

    <H2 id="where-next">Where next</H2>
    <Cards cols={3}>
      <Card to="agent-studio" title="Agent Studio">Build an agent with its own instructions and tools.</Card>
      <Card to="views" anchor="settings-assistant" title="Pin an agent to a view">Choose the agent a view opens with.</Card>
      <Card to="troubleshooting" title="Troubleshooting">When the assistant will not answer or a file will not read.</Card>
    </Cards>
  </>
);

export const section: GuideSection = {
  id: 'assistant',
  group: 'use',
  title: 'The assistant',
  summary: 'Ask questions of your data and the app, attach files, keep conversations.',
  icon: Bot,
  keywords: 'chat ai agent genie sql attach files upload paperclip conversations history pin stop chart trust retention',
  Body,
};
