/* eslint-disable react-refresh/only-export-components -- a section exports its data (`section`) beside its body */
import { Rocket } from 'lucide-react';
import type { GuideSection } from '../types';
import { Callout, Card, Cards, GuideLink, H2, Kbd, Lead, P, Shot, Step, Steps, UI } from '../kit';

const Body = () => (
  <>
    <Lead>
      In about ten minutes you can build a view of your own, put a widget on it, ask the assistant about it and send
      the link to a colleague. You do not need editor access for any of it.
    </Lead>

    <H2 id="the-path">Five steps</H2>
    <Steps>
      <Step title="Create a view">
        <P>
          In the sidebar, under <UI>My Views</UI>, click <UI>New View</UI>. A blank view called "View 1" (or the next
          number) opens. To rename it, hover its name in the sidebar and click the pencil, type a name and press{' '}
          <Kbd>Enter</Kbd>.
        </P>
        <P>
          The view is saved in the workspace shown in the sidebar and is private to you until you share it.
        </P>
      </Step>

      <Step title="Add a widget from the Widget Library">
        <P>
          Click <UI>Widget Library (w)</UI> in the sidebar, or press <Kbd>W</Kbd> while you are not typing in a box.
          A panel opens over the bottom of the screen. Type in <UI>Search widgets…</UI> to narrow the list, then click a
          card. The widget lands on the tab you are looking at. You can also drag a card onto the view.
        </P>
        <Shot
          name="use-widget-library"
          alt="The Widget Library tray open along the bottom of the screen"
          legend={[
            'Search widgets.',
            'Grid or list view.',
            'Filters: Certified, and which widgets you may use.',
            'A widget card. Click it or drag it onto your view.',
          ]}
        />
        <P>
          Some widgets ask for a setting first, in a <UI>Widget settings</UI> dialog with an <UI>Add widget</UI> button.{' '}
          <Kbd>Esc</Kbd> closes the library.
        </P>
      </Step>

      <Step title="Arrange and resize it">
        <P>
          Hold the widget's header, the bar with the grip and the title, and drag it to a new place; other widgets move
          out of the way. To resize, drag the small handle in the bottom right corner.
        </P>
        <Shot
          name="use-widget-card"
          alt="A widget card with its header icons"
          legend={[
            'The grip. Drag the header to move the widget.',
            'Header buttons: version, copy link, help, full screen and remove.',
            'The resize handle in the bottom right corner.',
          ]}
        />
      </Step>

      <Step title="Ask the assistant about it">
        <P>
          Click the assistant button at the bottom right; it carries the name of the agent, "EDH Agent" unless your view uses another. In the message box, type a question such as "What does
          this table show?" and press <Kbd>Enter</Kbd>. The assistant can see the widgets on the tab you are on, and the
          note under the message box says how many.
        </P>
        <P>
          Answers are generated and can be wrong. Check anything you plan to act on.{' '}
          <GuideLink to="assistant" anchor="trust">More on what to trust</GuideLink>.
        </P>
      </Step>

      <Step title="Lock it and share it">
        <P>
          When the layout is right, click <UI>Lock</UI> in the top right so nothing moves by accident. Then click{' '}
          <UI>Share</UI>. The button briefly reads <UI>Copied!</UI> and the link to your view is on your clipboard.
          Paste it into a message.
        </P>
        <Shot
          name="use-view-header"
          alt="The view header with Settings, Lock and Share"
          legend={[
            'Settings: how the view opens, looks and filters.',
            'Lock: freezes the layout.',
            'Share: copies a link to the view.',
            'The + in the tab bar adds a tab.',
          ]}
        />
        <P>
          Whoever opens the link finds your view under <UI>Shared Views</UI> in their sidebar, read-only. They need to
          be signed in, and the link opens in the same workspace you copied it from.
        </P>
      </Step>
    </Steps>

    <Callout kind="note" title="Changing your mind">
      <UI>Unlock</UI> returns the button to its editable state. To remove a view you made, hover it in the sidebar and
      click its small X. That deletes it without asking, so share a link or copy it first if you might want it back.
    </Callout>

    <H2 id="where-next">Where next</H2>
    <Cards cols={3}>
      <Card to="views" title="Views and layouts">
        Add tabs, set filters and a look, and choose how a shared link opens.
      </Card>
      <Card to="widgets" title="Using widgets">
        Widget settings, versions, full screen and removing a widget.
      </Card>
      <Card to="assistant" title="The assistant">
        Attach files, keep conversations and choose an agent.
      </Card>
    </Cards>
    <P>
      Want something the library does not have? <GuideLink to="widget-studio">Widget Studio</GuideLink> builds a widget
      from a description, if you have editor access.
    </P>
  </>
);

export const section: GuideSection = {
  id: 'quickstart',
  group: 'start',
  title: 'Your first ten minutes',
  summary: 'Make a view, add a widget, ask the assistant and share it.',
  icon: Rocket,
  keywords: 'tutorial first view new view getting started walkthrough steps',
  Body,
};
