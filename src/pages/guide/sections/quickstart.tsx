/* eslint-disable react-refresh/only-export-components -- a section exports its data (`section`) beside its body */
import { Rocket } from 'lucide-react';
import type { GuideSection } from '../types';
import { Callout, Card, Cards, GuideLink, H2, Kbd, Lead, P, Shot, Step, Steps, UI } from '../kit';

const Body = () => (
  <>
    <Lead>
      In about ten minutes you can build a view of your own, put a widget on it, ask the assistant about it and send
      the link to a colleague. Anyone can do all of it.
    </Lead>

    <H2 id="the-path">Five steps</H2>
    <Steps>
      <Step title="Create a view">
        <P>
          In the sidebar, under <UI>My views</UI>, click <UI>New View</UI>. A blank view called "View 1" (or the next
          number) opens. To rename it, hover its name in the sidebar and click the pencil, type a name and press{' '}
          <Kbd>Enter</Kbd>.
        </P>
        <P>
          The view is a draft that only you can see until you share and publish it.
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

      <Step title="Lock, publish and share it">
        <P>
          When the layout is right, open the <UI>⋯</UI> menu in the top right and choose <UI>Lock layout</UI> so
          nothing moves by accident. Click <UI>Publish</UI>, the last button in the header, so there is a version for
          other people to see. Then click <UI>Share</UI>, add your colleague as <UI>Can use</UI>, and click{' '}
          <UI>Copy link</UI>. Paste it into a message.
        </P>
        <Shot
          name="use-view-header"
          alt="The view header with the state chip, the ⋯ menu, Share and Publish"
          legend={[
            'The state chip beside the name: Not published yet, Published or Unpublished changes.',
            'The ⋯ menu: layout, Add a tab…, View settings…, Lock layout and version history.',
            'Share: choose who can use or manage the view, and copy its link.',
            'Publish: makes your draft what everyone sees.',
            'The + in the tab bar adds a tab.',
          ]}
        />
        <P>
          The view appears under <UI>Shared with me</UI> in their sidebar, read-only, showing the version you
          published. The link opens only for people you shared the view with. When you change the view later,
          publish again for them to see it. See <GuideLink to="sharing">Sharing &amp; permissions</GuideLink>.
        </P>
      </Step>
    </Steps>

    <Callout kind="note" title="Changing your mind">
      <UI>Unlock layout</UI> in the same menu lets you change the layout again. To put a view away, hover it under <UI>My views</UI> and
      click its <UI>×</UI>. You are asked first. A view only you can open is deleted; a shared one is archived, leaving
      everyone&rsquo;s sidebar to wait under <UI>Archived</UI>, where you can restore it. See{' '}
      <GuideLink to="publishing" anchor="archive">Archive, restore or delete a view</GuideLink>.
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
      from a description, and anyone can use it.
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
