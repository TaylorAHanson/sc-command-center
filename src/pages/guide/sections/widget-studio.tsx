/* eslint-disable react-refresh/only-export-components -- a section exports its data (`section`) beside its body */
import { Code } from 'lucide-react';
import type { GuideSection } from '../types';
import {
  Lead, H2, H3, P, List, Steps, Step, Callout, Needs, Details, Shot, UI, Kbd, Code as C, Table,
  GuideLink, OpenLink, Cards, Card,
} from '../kit';

const Body = () => (
  <>
    <Lead>
      Build a widget by describing it in plain language. The studio's agent writes the code, shows it running
      beside the chat, and fixes what breaks. You don't need to know React for simple and moderately complex
      widgets. <Needs role="Editor on a domain" />
    </Lead>

    <H2 id="first-widget">Build your first widget</H2>
    <Steps>
      <Step title="Open the studio">
        <P>
          Click <UI>Widget Studio</UI> in the sidebar. To change a widget that already exists, use its edit
          button in the Widget Library instead; the studio opens with that widget loaded. Both need Editor
          access in at least one domain (see <GuideLink to="roles">Roles and permissions</GuideLink>).
        </P>
        <Shot
          name="studio-overview"
          alt="Widget Studio with the chat on the left and a live preview on the right"
          caption="Chat on the left, the widget on the right. This one has an existing widget loaded."
          legend={[
            'The chat with the agent. Type your request here.',
            'The Card / Page switch: what you are building.',
            'The three tabs: Live Preview, TSX Editor and Configuration.',
            'Widget actions: History, Reload, Promote, the ⋯ menu, Save and close.',
          ]}
        />
      </Step>
      <Step title="Name it and pick a domain">
        <P>
          Open the <UI>Configuration</UI> tab and fill in <UI>Widget Name</UI>, <UI>Description</UI>,{' '}
          <UI>Category</UI> and <UI>Domain</UI>. The domain decides who can see the widget, so pick the one
          whose people should see its data. The agent can suggest these from your request, but it never
          overwrites a field you have typed in or chosen yourself.
        </P>
      </Step>
      <Step title="Point it at an API, if it uses one">
        <P>
          For data in Databricks tables, skip this step: name the table in your request and the agent writes the
          SQL into the widget, running it first to check it (see{' '}
          <GuideLink to="widget-studio" anchor="looks-at-data">It looks at your data first</GuideLink>). Only a
          widget that calls an API needs a <UI>Data Source</UI> on <UI>Configuration</UI>: choose <UI>API</UI>{' '}
          or <UI>DATABRICKS API</UI>, enter the address, then click <UI>Test &amp; Extract Schema</UI> so the
          agent is given the fields and a few sample rows.
        </P>
      </Step>
      <Step title="Describe the widget to the agent">
        <P>
          Type what you want in the message box and press <Kbd>Enter</Kbd>. For example: "A bar chart of
          shipments by region, with a dropdown to filter by month." Name the table if you know it. A big
          request can take a few minutes; the chat shows the seconds elapsed and, for large builds, a
          checklist of steps.
        </P>
      </Step>
      <Step title="Preview it and ask for changes">
        <P>
          <UI>Live Preview</UI> runs the widget with your data. If something is off, describe the change in
          the chat ("make the total bold and move it above the chart"), or click <UI>Send screenshot to agent</UI>{' '}
          under the preview first. Check the <UI>Problems</UI> bar at the bottom: <UI>Fix with agent</UI> asks
          the agent to fix everything listed. <UI>TSX Editor</UI> shows the code if you want to edit it by hand.
        </P>
      </Step>
      <Step title="Save">
        <P>
          Click <UI>Publish</UI> (the first time) or <UI>Save</UI> (after that). Saving needs Editor access on
          the widget's domain. The widget is saved to the workspace chosen in the sidebar (Dev, Test or Prod)
          and appears in that workspace's Widget Library straight away. You stay in the studio. Click the{' '}
          <UI>X</UI> when you have finished with the widget.
        </P>
      </Step>
      <Step title="Promote it">
        <P>
          Author in Dev, then click the rocket button (<UI>Promote</UI>) to copy the saved widget to Test and
          then Prod. The button stays disabled until the widget has been saved once.
        </P>
        <Shot
          name="studio-promote"
          alt="The Promotion panel showing Dev, Test and Prod versions with Promote buttons"
          caption="The Promotion panel. It copies the last saved version, not unsaved edits in the editor."
          legend={[
            'Promote opens the Dev → Test → Prod panel for this widget.',
            'Promote to Test copies Dev\'s latest saved version into Test.',
            'Promote to Prod copies Test\'s current version into Prod.',
          ]}
        />
        <P>
          Rolling back and certifying are in the same panel; the rules are in{' '}
          <GuideLink to="promotion">Promoting work</GuideLink>.
        </P>
      </Step>
    </Steps>

    <H2 id="configure">Configure the widget</H2>
    <P>
      Everything about the widget itself, apart from its code, is on the <UI>Configuration</UI> tab.
    </P>
    <Table
      head={['Field', 'What it does']}
      rows={[
        [<UI key="n">Widget Name</UI>, 'The title on the card and in the Widget Library. Required to save.'],
        [<UI key="d">Description</UI>, 'What the widget is for. Required to save. The assistant reads it when it answers questions about a view.'],
        [<UI key="h">Help Text (Optional)</UI>, 'Instructions on how to use the widget. Markdown is supported.'],
        [<UI key="c">Category</UI>, 'The widget\'s category, from the list an admin keeps under Categories & Domains. Required to save.'],
        [<UI key="dm">Domain</UI>, 'Who can see and edit the widget (see Roles and permissions). Required to save.'],
        [<UI key="w">Default Width (cols)</UI>, 'How wide the card is when first placed, from 1 to 12 grid columns.'],
        [<UI key="ht">Default Height (rows)</UI>, 'How tall the card is when first placed, from 1 to 12 grid rows.'],
        [<UI key="o">Open in New Tab Link</UI>, 'If set, a button in the widget\'s header opens this address in a new tab.'],
      ]}
    />
    <Shot
      name="studio-config"
      alt="The Configuration tab of Widget Studio"
      caption="The Configuration tab, scrolled to the data source and the options below it."
      legend={[
        'Category and Domain.',
        'Data Source: NONE, API or DATABRICKS API.',
        'Is Executable Action.',
        'Configuration Mode.',
      ]}
    />

    <H3 id="data-source">Data source</H3>
    <List>
      <li><UI>NONE</UI>: the widget has its own content or no data.</li>
      <li><UI>API</UI>: an address the widget calls. It is called from your browser, the same way the widget will call it, so if the API blocks requests from this app you find out when you test it.</li>
      <li><UI>DATABRICKS API</UI>: a Databricks REST path, for example a serving endpoint.</li>
    </List>
    <P>
      <UI>Test &amp; Extract Schema</UI> shows the schema and a few sample rows. The agent is given both when it
      writes your widget. Tests run with your own permissions.
    </P>
    <P>
      There is no SQL data source. A widget that reads tables carries its SQL in its code, and the agent runs
      that SQL itself, as you, to check it. A widget saved with a SQL data source before this keeps it: the
      query shows read-only on <UI>Configuration</UI> and every placed copy keeps working. Ask the agent to
      change it and the query moves into the code; <UI>Remove legacy SQL</UI> then clears the old one.
    </P>
    <Details summary="How many rows a widget gets">
      <P>
        How many rows a query returns changes how the widget gets built, so the agent counts them when it is
        unsure. Searching, sorting and paging can happen in the browser or in the query, and both work at any
        row count. What decides is how much data the browser would have to download, roughly 10 MB.
      </P>
      <List>
        <li>Under that, the widget fetches everything once and works locally, which is fastest.</li>
        <li>Over it, all of that is pushed into SQL so the widget only ever holds the page you are looking at.</li>
        <li>A table whose size isn't known is assumed to be large.</li>
      </List>
      <P>
        By default a query returns its first 500 rows. A widget that works on the whole result asks for every
        row, however many there are, up to the <UI>Most rows one widget query can return</UI> setting in{' '}
        <OpenLink page="admin">Admin Panel</OpenLink> → <UI>Settings</UI>; it says so when it is showing only
        part of the data. A widget that asks for a fixed number of rows instead is flagged in the studio,
        because it goes wrong once the data grows past that number.
      </P>
    </Details>

    <H3 id="executable">Is Executable Action and the audit trail</H3>
    <P>
      Turn on <UI>Is Executable Action</UI> if the widget submits forms, triggers pipelines or executes server
      actions. Each time someone presses one of its action buttons, the app writes a row to the{' '}
      <GuideLink to="action-logs">action logs</GuideLink> first and only then runs the action. That row is the
      audit trail, and it is also the telemetry the Command Center collects about what people do after they see
      data.
    </P>
    <Callout kind="warn" title="Turn it on for widgets that change data">
      A widget that changes data (INSERT, UPDATE, DELETE, MERGE) does so through its action buttons, which
      record each change in the action logs along with who made it, so turn this on for it.{' '}
      <UI>Problems</UI> flags a write that skips the action buttons, and a widget whose legacy SQL data source
      changes data can't be saved without this setting.
    </Callout>

    <H3 id="runtime-parameters">Configuration Mode and runtime parameters</H3>
    <P>
      <UI>Configuration Mode</UI> decides whether people can set parameters on a placed card.
    </P>
    <List>
      <li><UI>None</UI>: no custom settings.</li>
      <li><UI>Allowed</UI>: people set parameters from the card's gear.</li>
      <li><UI>Required</UI>: people must fill them in before the widget renders. <UI>Widget settings</UI> opens when the widget is dropped.</li>
    </List>
    <P>
      Ask the agent for "a configurable threshold, catalog, label or choice" and it adds the field, reads it
      through <C>props.data</C>, and selects <UI>Allowed</UI> or <UI>Required</UI> for you. To add fields by
      hand, click <UI>Add Field</UI> under <UI>Configuration Schema</UI> and set its key, label and type
      (<UI>Text / String</UI>, <UI>Number</UI>, <UI>Choice (Select)</UI>, <UI>Large Text (Textarea)</UI> or{' '}
      <UI>Link</UI>). Fields can also carry a default, a <UI>Required</UI> tick, a placeholder and help text.
    </P>
    <Details summary="Where parameter values live, and Dev, Test and Prod">
      <P>
        Parameter values belong to the placed card in the current <UI>Workspace</UI>. For values that differ in
        Dev, Test and Prod, ask the studio to make them <UI>Required</UI> without a default. Drop the promoted
        widget in each workspace and fill in <UI>Widget settings</UI> there; use its gear later to change them.
      </P>
      <P>
        Promoting a whole view copies its existing card settings, so open each promoted card's gear when those
        values must differ in the target workspace.
      </P>
    </Details>

    <H2 id="agent">Work with the agent</H2>
    <P>
      The chat is your main tool. The agent reads your request, the current code, your data source and
      anything you attach, then edits the widget. Asking for a change never erases the rest of the widget.
    </P>

    <H3 id="thinking-questions">Thinking and clarifying questions</H3>
    <P>
      While the agent works, expand <UI>Thinking</UI> to see how it read your request, the steps it planned and
      anything it decided to skip. Once the turn finishes the same box is labelled <UI>Thoughts</UI>.
    </P>
    <P>
      On a large or vague request it may come back with up to three questions instead of code. Answer the ones
      that matter, or press <UI>Build it anyway</UI> and it will pick sensible defaults. Two minutes of
      questions is cheaper than ten minutes spent building the wrong widget. Turn this off in{' '}
      <GuideLink to="widget-studio" anchor="agent-settings">Agent settings</GuideLink>.
    </P>

    <H3 id="looks-at-data">It looks at your data first</H3>
    <P>
      Before it writes anything, the agent can look at your data. It runs read-only SQL on the app's warehouse
      and can ask Genie, both as you, so it sees only what you are allowed to see. Name the table you mean
      (<C>main.supply.shipments</C>) and it checks the real column names and values rather than guessing.
    </P>
    <List>
      <li>Each query it ran appears under <UI>Thinking</UI>.</li>
      <li>It never changes data, and what it learns shapes the code rather than being pasted in as fixed numbers.</li>
      <li>Each step of a multi-step build can do the same, and the agent runs any SQL it writes once before handing the code back.</li>
    </List>

    <H3 id="watches-preview">It watches the preview and fixes its own mistakes</H3>
    <P>
      The studio watches the preview run: every request the widget makes and how many rows came back, anything it
      logs as an error, and errors it throws. When code the agent just wrote fails as it runs, such as a query
      rejected as invalid or a crash while handling the data, the agent is sent what happened and fixes it on its
      own, up to twice.
    </P>
    <P>
      It leaves alone failures that code can't fix: a permission error, a server error, or a widget's legacy SQL
      data source itself failing. For that last one it tells you, and you can ask it to replace the query.
    </P>

    <H3 id="problems">Problems and Fix with agent</H3>
    <P>
      <UI>Problems</UI> is the bar under the preview and the code. It counts rule errors, warnings and what
      happened when the widget last ran. Click it to open the list.
    </P>
    <Shot
      name="studio-problems"
      alt="The Problems bar expanded, listing three warnings"
      caption="The Problems bar, opened."
      legend={[
        'The bar: errors, warnings and how the last run went.',
        'Fix with agent sends everything listed to the agent.',
        'The list: each check with its line number and rule, then the last run in the preview.',
      ]}
    />
    <List>
      <li>Under <UI>Checks</UI>: an import widgets can't use, a script from a CDN that isn't allowed, a write that skips the audit trail, text too light to read, a class the app's stylesheet doesn't have (so it does nothing), or a font that isn't bundled.</li>
      <li>Under <UI>Last run in the preview</UI>: the requests the widget made and any errors.</li>
      <li>The agent is given both lists with every request.</li>
      <li>Rule errors in code the agent wrote are fixed automatically. Warnings are left for you to decide.</li>
    </List>
    <P>
      The bar is hidden on the <UI>Configuration</UI> tab. Open <UI>Live Preview</UI> for the runtime part of the list.
    </P>

    <H3 id="show-it">Show it a screenshot or a file</H3>
    <P>
      The paperclip beside the message box attaches spreadsheets, documents and images for the agent to read,
      such as a sample export or a design someone sent you. You can also paste a screenshot or copied image
      straight into the message box. Below the preview, <UI>Send screenshot to agent</UI> attaches a picture of
      the widget exactly as it looks right now, at the size you have dragged it to.
    </P>
    <P>
      Neither one sends by itself. The file waits on your next message, so "this column is too narrow and the
      total is in the wrong place" arrives alongside the thing it is describing. Grabbing a second screenshot
      replaces the first.
    </P>

    <H3 id="agent-settings">Agent settings</H3>
    <P>
      The sliders icon above the chat opens <UI>Agent settings</UI>. Both options are remembered in your
      browser, so they are yours rather than everyone's.
    </P>
    <List>
      <li>
        <UI>Conduct review after change</UI> (off by default): once new code compiles and has run in the
        preview, the agent reads it back as a reviewer and fixes what it finds. It costs an extra turn, which is
        why you have to ask for it.
      </li>
      <li>
        <UI>Ask before large builds</UI> (on by default): the clarifying questions described above. Turn it off
        if you would rather it always guessed and got straight to work.
      </li>
    </List>
    <Details summary="What a review checks and what the chips mean">
      <P>
        The reviewer gets a screenshot of how the widget rendered and what happened when it ran. It checks
        whether the widget does everything you asked, handles loading, empty and error states, holds up squashed
        narrow and stretched wide, and uses text colors dark enough to read. It fixes what it finds.
      </P>
      <P>
        It then steps back and answers a different question under <UI>Worth considering</UI>: is this widget
        actually good at its job, and what are the two or three changes that would most improve it. Those are
        suggestions only. It never builds them unasked, so you can leave the setting on without the widget
        growing behind your back.
      </P>
      <P>
        Each suggestion appears as a chip under <UI>Do next</UI>, along with an amber chip for anything it found
        but didn't fix. Clicking a chip writes that instruction into the message box for you to edit or send, so
        you never have to retype a suggestion to act on it.
      </P>
    </Details>
    <Shot
      name="studio-agent-settings"
      alt="The Agent settings menu with two checkboxes"
      caption="Agent settings, opened from the sliders icon."
      narrow
      legend={[
        'The sliders icon above the chat.',
        'Conduct review after change.',
        'Ask before large builds.',
      ]}
    />

    <H2 id="cards-pages">Cards and pages</H2>
    <P>
      The <UI>Card</UI> / <UI>Page</UI> switch above the preview says what you are building.
    </P>
    <List>
      <li>A <strong>card</strong> sits on a tab with other widgets.</li>
      <li>A <strong>page</strong> fills a whole tab of a view and brings its own background and layout, for a landing page or hub. Attach a picture of the page you want and the agent works from it.</li>
    </List>
    <P>
      If your first request asks for a landing page, hub or full-screen page, the studio starts it as a page and
      says so. You can switch either way at any time. Pages are marked <UI>PAGE</UI> in the Widget Library; drag
      one onto a page tab.
    </P>
    <Shot
      name="studio-card-page"
      alt="The Card and Page switch and the width buttons above a page preview"
      caption="A page being previewed."
      legend={[
        'The Card / Page switch.',
        'The preview widths for a page: Laptop, Wide and Narrow.',
      ]}
    />
    <Details summary="Previewing a page">
      <List>
        <li>A page previews under a stand-in header and tabs at <UI>Laptop</UI>, <UI>Wide</UI> or <UI>Narrow</UI> width, scaled to fit.</li>
        <li>Classes like <C>md:</C> and <C>lg:</C> follow your browser window rather than that frame, so narrow the window to check a small-screen layout.</li>
        <li>Its buttons say what they would do in a view instead of doing it.</li>
        <li>Cards that name a part of the view, such as a persona, open the tab with that name when the view has one, so name your tabs to match.</li>
      </List>
    </Details>

    <H2 id="steer-the-view">Widgets that steer the view</H2>
    <P>
      A widget can open the view's other tabs, and open the assistant with an agent chosen and a question typed
      in. Ask for "tiles that go to each tab" or "an Ask about this button". It never sends the question for
      you: you read it and press <UI>Send</UI>. It can't open other views.
    </P>
    <H3 id="named-links">Named links</H3>
    <P>
      A widget whose tiles or buttons go somewhere specific, like a hub page's <em>Sales</em> and{' '}
      <em>Operations</em> tiles, has named <strong>links</strong>, and you decide where each one goes. The studio
      adds the links when it builds such a widget, or you can add a settings field of type <UI>Link</UI> yourself.
    </P>
    <Steps>
      <Step>Place the widget on your view and open its gear.</Step>
      <Step>
        For each link, choose one of the view's tabs, <UI>Not set</UI>, or <UI>Web address…</UI> (http or https).
      </Step>
    </Steps>
    <List>
      <li>The choice belongs to this card, so the same widget can go to different tabs on different views.</li>
      <li>Renaming a tab keeps its links. Deleting it leaves them going nowhere, and the gear says so.</li>
      <li>A web address opens in a new browser tab.</li>
      <li>A tile whose link isn't set yet looks muted and does nothing.</li>
    </List>

    <H2 id="may-contain">What a widget may contain</H2>
    <P>
      Saving is refused if the code uses <C>eval</C>, <C>new Function</C>, <C>document.write</C>,{' '}
      <C>innerHTML</C> or <C>dangerouslySetInnerHTML</C>, or if it references any address other than this app's
      own <C>/api/...</C> paths, the approved CDNs, and any Databricks App an admin has approved.
    </P>
    <Table
      head={['Approved CDNs']}
      rows={[
        [<C key="1">cdn.jsdelivr.net</C>],
        [<C key="2">code.highcharts.com</C>],
        [<C key="3">unpkg.com</C>],
        [<C key="4">cdnjs.cloudflare.com</C>],
      ]}
    />
    <P>
      To embed or call another Databricks App, a global admin adds its host, or its whole workspace, to{' '}
      <UI>Databricks Apps widgets may embed or call</UI> in{' '}
      <GuideLink to="settings" anchor="reach">Settings</GuideLink>. An app approved through its workspace can be shown
      in an iframe; fetching data from it needs the app listed by its own host. Libraries still load only from the CDNs above. The browser
      enforces the same rules independently, so an off-list script won&apos;t load even if it reached the database
      another way. If a save is refused, the message names what tripped it. The usual cause is a library pulled
      from a CDN that isn&apos;t on the list: ask the agent for the jsDelivr copy instead.
    </P>
    <Details summary="Writing or editing the code yourself">
      <List>
        <li>Make the component scale with its card (full width and height), and use dark text: widgets render on white.</li>
        <li>Only the standard Tailwind CSS classes the app ships are available. Arbitrary values such as <C>w-[150px]</C> do nothing, so use an inline <C>style</C> for exact sizes and colors. <UI>Problems</UI> flags a class that doesn't exist.</li>
        <li>Write brand colors as <C>brand-blue</C>, <C>brand-navy</C> and <C>brand-light</C> so a view's theme can recolor them.</li>
        <li>Any write to data has to go through the action wrapper so it is logged; <UI>Problems</UI> flags a write that skips it.</li>
      </List>
    </Details>

    <H2 id="save-history-promote">Save, history, promote and stop</H2>
    <H3 id="save-publish">Save and publish</H3>
    <P>
      <UI>Save</UI> (or <UI>Publish</UI>, the first time) writes your code to the workspace selected in the
      sidebar (Dev, Test or Prod) and increments the version. It is immediately available in that workspace's
      Widget Library, and the result shows under the buttons. Saving leaves you in the studio, so you can keep
      working and save as often as you like. The <UI>X</UI> closes the studio when you have finished.
    </P>
    <P>
      Every control for the widget sits on the right, above the preview: <UI>History</UI>, <UI>Reload</UI>,{' '}
      <UI>Promote</UI>, the <UI>⋯</UI> menu (<UI>Import from file…</UI>, <UI>Export to file</UI>,{' '}
      <UI>Reset studio</UI>), then <UI>Save</UI> and close. Only the agent's own settings sit above the chat.
      <UI>Reload</UI> recompiles and remounts the widget so anything it loads on start runs again.{' '}
      <UI>Reset studio</UI> asks first, then clears the studio for a new widget; a snapshot of the code is kept
      in <UI>History</UI>.
    </P>
    <Shot
      name="studio-more-menu"
      alt="The more menu open, showing Import from file, Export to file and Reset studio"
      caption="The ⋯ menu."
      legend={[
        'The ⋯ menu.',
        'Import from file… opens a widget file as a new widget.',
        'Export to file downloads the widget.',
        'Reset studio.',
      ]}
    />
    <P>
      <UI>Export to file</UI> downloads the widget's code and every setting as a <C>.widget.json</C> file, so
      you can share it or move it between apps. <UI>Import from file…</UI> loads such a file into the studio as a
      new widget; review it, then <UI>Publish</UI> to save it.
    </P>

    <H3 id="history">History</H3>
    <P>
      <UI>History</UI> lists earlier code you can go back to, in two groups.
    </P>
    <List>
      <li><UI>This session</UI>: a snapshot is taken automatically before the agent, an import or a reset changes your code, and as you type.</li>
      <li><UI>Published versions</UI>: every version you have saved, with who saved it and when.</li>
    </List>
    <P>
      <UI>Restore</UI> loads that code into the editor and nothing else. Your settings stay as they are and
      nothing is published until you save.
    </P>
    <Shot
      name="studio-history"
      alt="The History panel with a published version listed"
      caption="The History panel."
      legend={[
        'History opens the panel.',
        'This session: automatic snapshots from this visit.',
        'Published versions, each with Restore.',
      ]}
    />

    <H3 id="promote">Promote</H3>
    <P>
      <UI>Promote</UI> copies the last saved version from Dev to Test, then Test to Prod. Unsaved edits are not
      included, so save first. Each workspace numbers its own versions. See{' '}
      <GuideLink to="promotion">Promoting work</GuideLink> for rollback, certification and who may promote.
    </P>

    <H3 id="stop">Stop the agent</H3>
    <P>
      While the agent works, the send button turns into a red <UI>Stop</UI> button, and pressing <Kbd>Enter</Kbd>{' '}
      does nothing, so you can type your next request without interrupting it. <UI>Stop</UI> ends the turn at
      once: steps that already finished stay in the editor, each with an entry in <UI>History</UI>, and nothing
      else is applied.
    </P>
    <P>
      On a multi-step build, <UI>Stop after this step</UI> lets the step in progress finish first.
    </P>

    <H2 id="where-next">Where next</H2>
    <Cards cols={3}>
      <Card title="Promote your widget" to="promotion">Move it from Dev to Test and Prod.</Card>
      <Card title="Action logs" to="action-logs">See what the audit trail records for executable widgets.</Card>
      <Card title="Build an agent" to="agent-studio">Give the assistant its own instructions and tools.</Card>
    </Cards>
    <P>
      <OpenLink page="studio">Open Widget Studio</OpenLink>
    </P>
  </>
);

export const section: GuideSection = {
  id: 'widget-studio',
  group: 'build',
  title: 'Widget Studio',
  summary: 'Build a widget by describing it, then save and promote it.',
  icon: Code,
  keywords: 'create widget build generate code tsx data source sql legacy query api preview agent page card configuration executable action',
  Body,
};
