import React, { useState } from 'react';
import { Book, Shield, Layers, Code, PlayCircle, Settings, Users, LayoutGrid, MousePointerClick, Lock, Copy, PlusCircle, PanelTop, Bot, Paperclip, History, ArrowRightLeft, Square, BarChart3 } from 'lucide-react';
import clsx from 'clsx';

type Section = {
  id: string;
  category: 'User Guide' | 'Admin Guide';
  title: string;
  icon: React.ReactNode;
  content: React.ReactNode;
};

export const UserGuidePage: React.FC = () => {
  const [activeSection, setActiveSection] = useState<string>('overview');

  const sections: Section[] = [
    {
      id: 'overview',
      category: 'User Guide',
      title: 'Overview',
      icon: <Book className="w-4 h-4" />,
      content: (
        <div className="space-y-6">
          <h2 className="text-2xl font-bold text-gray-900">Overview</h2>
          <p className="text-gray-600">
            Welcome to the Enterprise Command Center. This application serves as a highly configurable dashboarding tool where you can select, arrange, and manage widgets on a grid. It allows you to build custom views tailored to your workflows, take actions, and easily share your layouts with others.
          </p>
          <p className="text-gray-600">
            Whether you're exploring enterprise data, monitoring supply chains, or checking system health, the Command Center gives you the tools to bring all the information you need into one unified pane of glass.
          </p>
        </div>
      ),
    },
    {
      id: 'views-layouts',
      category: 'User Guide',
      title: 'Views & Layouts',
      icon: <LayoutGrid className="w-4 h-4" />,
      content: (
        <div className="space-y-6">
          <h2 className="text-2xl font-bold text-gray-900">Views & Layouts</h2>
          <p className="text-gray-600">
            Your workspace is organized into "Views": pages of widgets that you can customize, each with one or more tabs.
          </p>
          
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-6">
            <div className="bg-white p-5 border rounded-lg shadow-sm">
              <div className="font-semibold text-gray-900 flex items-center gap-2 mb-2">
                <PlusCircle className="w-4 h-4 text-blue-500" />
                Creating a View
              </div>
              <p className="text-sm text-gray-600">
                Click <strong>New View</strong> in the left sidebar to create a fresh, blank view. You can rename your view by clicking the pencil icon next to its name.
              </p>
            </div>

            <div className="bg-white p-5 border rounded-lg shadow-sm">
              <div className="font-semibold text-gray-900 flex items-center gap-2 mb-2">
                <PanelTop className="w-4 h-4 text-teal-500" />
                Tabs
              </div>
              <p className="text-sm text-gray-600">
                Click <strong>Add tab</strong> in the top-right corner to give a view a second tab; it asks what to call the new tab and the one you're on. Use the <strong>+</strong> in the tab bar for more. Double-click a tab (or select it and press <strong>F2</strong>) to rename it, drag it to reorder, or click its <strong>×</strong> to delete it; a tab with widgets asks first. The arrow keys move between tabs and Enter opens one. Widgets you add go on the tab you're looking at, and filters one widget sets apply on every tab of the view. Each tab is <strong>Cards on a grid</strong> or a <strong>Full page</strong>: one widget filling the whole tab, for a landing page or hub. Adding a tab asks which; the grid/page icon on the tab you're looking at switches it, and you drag a widget from the library onto a page to fill it. For tiles that open the other tabs, drag in <strong>Tab links</strong> and pick the tabs from its gear; renaming a tab keeps its link.
              </p>
              <p className="text-sm text-gray-600 mt-2">
                The view's <strong>Settings</strong> has four sections down its left side: <strong>Opening</strong>, <strong>Look</strong>, <strong>Filters</strong> and <strong>Assistant</strong>. A red dot marks a section with something to fix before you can save. <strong>Look</strong> also puts the tabs <strong>Across the top</strong> or <strong>Down the side</strong>, and <strong>Filters</strong> adds dropdowns above the widgets. Each filter has a label, the variable it sets, its options (one per line) and the one it starts on. Anyone who can see the view can use them; widgets that follow that variable update on every tab, and <strong>All</strong> clears it. Each person comes back to the choices they last made, in that browser.
              </p>
              <p className="text-sm text-gray-600 mt-2">
                <strong>Look</strong> in the same dialog styles the view: an accent and a dark color in place of Command Center's blue and navy (both dark enough for white text), a font, a background (a color, a gradient or an image) and how cards are drawn, down to leaving their titles off with <strong>No title</strong>. It is the same on every tab, covering the view's tabs, filters and background here and the whole page when the view opens on its own; a page tab takes only the colors and font. Type a description beside <strong>Suggest</strong> to have the choices filled in for you; nothing is saved until you press <strong>Save</strong>.
              </p>
            </div>

            <div className="bg-white p-5 border rounded-lg shadow-sm">
              <div className="font-semibold text-gray-900 flex items-center gap-2 mb-2">
                <Copy className="w-4 h-4 text-purple-500" />
                Copying Global Views
              </div>
              <p className="text-sm text-gray-600">
                Under "Global Views", you'll find pre-made templates. These are automatically filtered so you only see templates belonging to Domains you have Viewer access to. Hover over a global view and click the <strong>Copy</strong> icon to duplicate it into your own personal views so you can edit it.
              </p>
            </div>

            <div className="bg-white p-5 border rounded-lg shadow-sm">
              <div className="font-semibold text-gray-900 flex items-center gap-2 mb-2">
                <Lock className="w-4 h-4 text-orange-500" />
                Locking & Unlocking
              </div>
              <p className="text-sm text-gray-600">
                Once your layout is perfect, click the <strong>Lock</strong> button in the top-right corner. This prevents accidental drag-and-drops. Click <strong>Unlock</strong> when you need to make changes again.
              </p>
            </div>

            <div className="bg-white p-5 border rounded-lg shadow-sm">
              <div className="font-semibold text-gray-900 flex items-center gap-2 mb-2">
                <Book className="w-4 h-4 text-green-500" />
                Sharing Views
              </div>
              <p className="text-sm text-gray-600">
                Want to show someone your setup? Click the <strong>Share</strong> button in the top-right corner to copy a direct link to your current view, or copy the address from your browser. Anyone you send it to finds your view under <strong>Shared Views</strong>, read-only.
              </p>
              <p className="text-sm text-gray-600 mt-2">
                To share it as a page of its own, open <strong>Settings → Opening</strong> and choose <strong>On its own</strong>; the title, logo and browser tab icon to show appear below it. The link then opens just that view, read-only, under the title and logo you set, and <strong>Preview</strong> in the header shows it that way. <strong>Assistant</strong> in the same dialog picks the agent the view opens with, wherever it opens; <strong>No agent</strong> leaves the view without an assistant. Hover the <strong>?</strong> beside any field in the dialog to see what it does. Its editors get an <strong>Edit</strong> button there that brings it back into Command Center.
              </p>
            </div>
          </div>
        </div>
      ),
    },
    {
      id: 'using-widgets',
      category: 'User Guide',
      title: 'Using Widgets',
      icon: <MousePointerClick className="w-4 h-4" />,
      content: (
        <div className="space-y-6">
          <h2 className="text-2xl font-bold text-gray-900">Using Widgets</h2>
          <p className="text-gray-600">
            Widgets are the building blocks of your dashboard. They can display charts, text, forms, or actionable tools.
          </p>

          <div className="space-y-6 mt-6">
            <div>
              <h3 className="text-lg font-semibold text-gray-800 mb-2">The Widget Library</h3>
              <p className="text-gray-700">
                Open the Widget Library by clicking the <strong>Widget Library</strong> button in the sidebar (or press the <code>W</code> key). From here, you can browse or search for widgets available within your domain.
              </p>
            </div>

            <div className="bg-gray-50 border rounded-lg p-4 space-y-4">
              <div>
                <h4 className="font-semibold text-gray-900">Adding Widgets</h4>
                <p className="text-sm text-gray-600">
                  Simply drag a widget from the library and drop it onto your view, or click the "+" button on the widget to add it automatically.
                </p>
              </div>
              <div>
                <h4 className="font-semibold text-gray-900">Arranging (Drag & Drop)</h4>
                <p className="text-sm text-gray-600">
                  Click and hold the drag handle (the dotted grip icon usually at the top-left of a widget) to move it around your grid. Other widgets will automatically flow out of the way.
                </p>
              </div>
              <div>
                <h4 className="font-semibold text-gray-900">Resizing</h4>
                <p className="text-sm text-gray-600">
                  Hover over the bottom-right corner of any widget. Click and drag the resize handle to adjust its width and height to fit your layout.
                </p>
              </div>
            </div>
          </div>
        </div>
      ),
    },
    {
      id: 'assistant',
      category: 'User Guide',
      title: 'The Assistant',
      icon: <Bot className="w-4 h-4" />,
      content: (
        <div className="space-y-6">
          <h2 className="text-2xl font-bold text-gray-900">The Assistant</h2>
          <p className="text-gray-600">
            The panel on the right answers questions about the view you're on, your data, and the Command Center itself. It sees the widgets currently on screen, and every tool it runs uses <strong>your</strong> Databricks permissions — so results reflect your own access, and a permission error describes yours, not the assistant's.
          </p>

          <div className="bg-white p-5 border rounded-lg shadow-sm">
            <div className="font-semibold text-gray-900 flex items-center gap-2 mb-2">
              <Paperclip className="w-4 h-4 text-blue-500" />
              Attaching files
            </div>
            <p className="text-sm text-gray-600">
              Click the paperclip, or drag a file onto the panel. Spreadsheets and CSVs, PDFs, Word documents, JSON, text and images all work — up to 25 MB each, five per conversation. A chip above the message box shows the file being read and then what's in it, such as "5,000 rows x 6 columns".
            </p>
            <p className="text-sm text-gray-600 mt-3">
              Big files stay quick because the assistant isn't handed the whole file. For a spreadsheet it sees the structure and then queries it, so totals and counts come from every row rather than a sample. For a document it finds the relevant passages and cites the page. Images and short PDFs it reads directly, so charts, screenshots and scans are fine. If a file can't be read — a scanned PDF with no text, or a protected file — the chip says so.
            </p>
            <p className="text-sm text-gray-600 mt-3">
              Files are private to you and stay available for the rest of that conversation, so you can keep asking about them. Deleting the conversation deletes its files.
            </p>
          </div>

          <div className="bg-white p-5 border rounded-lg shadow-sm">
            <div className="font-semibold text-gray-900 flex items-center gap-2 mb-2">
              <History className="w-4 h-4 text-purple-500" />
              Saved conversations
            </div>
            <p className="text-sm text-gray-600">
              Conversations are saved as you go, so reloading the browser or coming back tomorrow picks up where you left off. The clock icon lists your recent conversations — click one to reopen it, use the pencil to rename it, or the trash to delete it. The speech-bubble icon starts a new conversation and keeps the current one in the list.
            </p>
            <p className="text-sm text-gray-600 mt-3">
              Your conversations are private; nobody else sees them in the app. The 50 most recent are kept. Picking a different agent from the dropdown starts a new conversation and leaves the old one in your history.
            </p>
            <p className="text-sm text-gray-600 mt-3">
              The <strong>pin</strong> beside the agent dropdown makes your view open with the agent selected. On a view with tabs it asks whether to pin it to <strong>This tab</strong> or <strong>Every tab</strong>; a tab's own pin wins on that tab. Click a ticked choice to unpin. <strong>Settings → Assistant</strong> sets the view's pin too. Anyone can still switch agents while they're on the view.
            </p>
            <p className="text-sm text-gray-600 mt-3">
              <strong>Delete all my conversations</strong>, at the bottom of that list, removes every conversation you own along with its attached files. It asks once and can't be undone. Your administrator may also set a retention period, after which untouched conversations are deleted automatically.
            </p>
          </div>

          <div className="bg-white p-5 border rounded-lg shadow-sm">
            <div className="font-semibold text-gray-900 flex items-center gap-2 mb-2">
              <Square className="w-4 h-4 text-rose-500" />
              Stopping an answer
            </div>
            <p className="text-sm text-gray-600">
              While the assistant is working, the send button turns into a red <strong>Stop</strong> button. Clicking it ends the turn: the assistant stops calling tools, keeps what it had written so far and marks it <em>Stopped</em>. Pressing Enter never stops it, so you can keep typing your next question while it works. Reloading the page or switching conversations does not stop it; the answer is saved and waiting when you come back.
            </p>
          </div>

          <div className="bg-white p-5 border rounded-lg shadow-sm">
            <div className="font-semibold text-gray-900 flex items-center gap-2 mb-2">
              <BarChart3 className="w-4 h-4 text-emerald-500" />
              Charts
            </div>
            <p className="text-sm text-gray-600">
              When a picture explains the answer better — a trend, a comparison, a breakdown — the assistant draws a chart in the conversation, from the data it just retrieved. Ask for one ("chart that by month") if it doesn't offer. The menu on a chart saves it as PNG or SVG. Agents built in Agent Studio can chart the same way. Pictures in answers are only shown when they come from this app; one from another site appears as a small placeholder, so an answer can't pass your data to that site just by displaying an image.
            </p>
          </div>

          <div className="bg-white p-5 border rounded-lg shadow-sm">
            <div className="font-semibold text-gray-900 flex items-center gap-2 mb-2">
              <Bot className="w-4 h-4 text-amber-500" />
              What to trust
            </div>
            <p className="text-sm text-gray-600">
              Answers are generated by an AI model. They can be wrong, and they can be wrong confidently — check anything you're going to act on against the source. Where the assistant used a tool it says so, and those figures came from your data; anything else is the model's own prose.
            </p>
            <p className="text-sm text-gray-600 mt-3">
              Your administrator can narrow what the assistant is allowed to reach — querying Genie, running SQL, reading images and PDFs directly, and whether it's told what's on your screen can each be switched off for the whole deployment. If the assistant says a capability isn't available, that's usually why.
            </p>
          </div>
        </div>
      ),
    },
    {
      id: 'roles',
      category: 'Admin Guide',
      title: 'Roles & Permissions',
      icon: <Shield className="w-4 h-4" />,
      content: (
        <div className="space-y-6">
          <h2 className="text-2xl font-bold text-gray-900">Roles & Permissions</h2>
          <p className="text-gray-600 mb-4">
            The Command Center uses a dynamic Role-Based Access Control (RBAC) system to govern access to different dashboard "Domains" (such as Finance, Supply Chain, Sales, etc.).
          </p>
          
          <h3 className="text-xl font-semibold text-gray-800 mt-6 mb-3">Understanding Domains</h3>
          <p className="text-gray-700 mb-4">
            A <strong>Domain</strong> is a logical grouping of resources—specifically, global views and custom widgets. By assigning resources to a specific Domain, you isolate them so that only authorized users can see, interact with, or modify them. For example, a widget containing sensitive financial data should be assigned to the "Finance" domain, ensuring that users without Finance access cannot view or embed it.
          </p>

          <h3 className="text-xl font-semibold text-gray-800 mt-6 mb-3">Databricks Roles Integration</h3>
          <p className="text-gray-700 mb-4">
            The Command Center does not maintain its own independent user directory. Instead, it tightly integrates with your identity provider via Databricks SCIM/Entitlements. When you log in, the system retrieves your Databricks Groups and Service Principal roles. Permission mappings in the Command Center are created by linking these external Databricks roles to specific Domains at a designated Permission Level.
          </p>

          <h3 className="text-xl font-semibold text-gray-800 mt-6">Permission Levels</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="bg-white p-4 border rounded-lg shadow-sm">
              <div className="font-semibold text-gray-900 flex items-center gap-2 mb-2">
                <PlayCircle className="w-4 h-4 text-green-500" />
                Viewer
              </div>
              <p className="text-sm text-gray-600">Can view the global views and widgets belonging to this domain, and can interact with dashboards. Global views for this domain are hidden if you lack this role.</p>
            </div>
            <div className="bg-white p-4 border rounded-lg shadow-sm">
              <div className="font-semibold text-gray-900 flex items-center gap-2 mb-2">
                <Code className="w-4 h-4 text-blue-500" />
                Editor
              </div>
              <p className="text-sm text-gray-600">Has all Viewer privileges. Can also create, edit, and reorganize widgets and global views within this domain, and promote, roll back and certify them in any environment where they hold this role.</p>
            </div>
            <div className="bg-white p-4 border rounded-lg shadow-sm">
              <div className="font-semibold text-gray-900 flex items-center gap-2 mb-2">
                <Settings className="w-4 h-4 text-purple-500" />
                Admin
              </div>
              <p className="text-sm text-gray-600">Has full control. Everything an Editor can do, plus assigning domain permissions to users or groups.</p>
            </div>
          </div>
        </div>
      ),
    },
    {
      id: 'access',
      category: 'Admin Guide',
      title: 'Managing Access',
      icon: <Users className="w-4 h-4" />,
      content: (
        <div className="space-y-6">
          <h2 className="text-2xl font-bold text-gray-900">Managing Access</h2>
          <p className="text-gray-600">
            Global Administrators manage who has access to which domain from the Command Center UI, without needing database or code changes.
          </p>
          <div className="bg-white border rounded-lg p-6 shadow-sm mb-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-3">Global Admin</h3>
            <p className="text-sm text-gray-700 mb-3">
              Users granted the Global Administrator role have sweeping, unrestricted access to the entire application. They bypass all domain-level checks, meaning they can view, edit, and promote all domains and perform all administrative actions. By default, running the app locally with <code>DEV_MODE=true</code> grants you global admin rights.
            </p>
          </div>

          <div className="bg-white border rounded-lg p-6 shadow-sm">
            <h3 className="text-lg font-semibold text-gray-900 mb-3">How to Map Roles to Domains</h3>
            <p className="text-sm text-gray-700 mb-4">
              Because permissions are driven by Databricks, granting access means creating a "Mapping" between a Databricks group (or one user) and a Command Center Domain.
            </p>
            <ol className="list-decimal pl-5 space-y-3 text-gray-700">
              <li>Navigate to the <strong>Admin Panel</strong> by clicking on the shield icon in the left navigation sidebar, and open <strong>Role Mappings</strong>.</li>
              <li>Under "Create Domain Mapping", start typing in <strong>Databricks group or user</strong> and pick from the matching groups and users (e.g., <code>finance-team</code>).</li>
              <li>Choose the <strong>Mapped Domain</strong> from the list. The list is the domains under <strong>Categories &amp; Domains</strong>, so add a new domain there first.</li>
              <li>Select the appropriate Permission Level: <code>Viewer</code>, <code>Editor</code>, or <code>Admin</code>.</li>
              <li>Click <strong>Add Mapping</strong>. The backend applies this permission to any user belonging to that Databricks group upon their next session.</li>
            </ol>
            <p className="text-sm text-gray-700 mt-4">
              The group field is checked against Databricks as you type, because a mapping only applies to someone whose group or username matches it <strong>exactly, capitals included</strong>. A name that doesn't exist, or exists with different capitals, can't be saved — for a capitalisation slip the form offers the right spelling. If Databricks can't be reached for the check, the name is saved as typed and the form tells you so. A mapping whose domain has since been renamed or removed is marked <em>not a domain</em> in the table.
            </p>
          </div>
        </div>
      ),
    },
    {
      id: 'promotion',
      category: 'Admin Guide',
      title: 'Promoting Work',
      icon: <Layers className="w-4 h-4" />,
      content: (
        <div className="space-y-6">
          <h2 className="text-2xl font-bold text-gray-900">Promoting Work</h2>
          <p className="text-gray-600">
            The Command Center supports a multi-environment lifecycle (Dev, Test, Prod) to ensure experimental changes don't disrupt production end-users.
          </p>

          <div className="space-y-4 mt-6">
            <div className="bg-white p-5 border rounded-lg shadow-sm">
              <h3 className="text-lg font-semibold text-gray-900 mb-2">Versioning and Promoting Widgets</h3>
              <p className="text-sm text-gray-600 mb-3">
                Every time a custom widget's code or configuration is modified and saved in the <strong>Dev</strong> environment, its version number increments automatically. This immutable version history acts as an audit trail and enables seamless environment transitions.
              </p>
              <ul className="list-disc pl-5 text-sm text-gray-700 space-y-2 mb-3">
                <li><strong>Where:</strong> from inside <strong>Widget Studio</strong> — the <strong>Promote</strong> button in the header opens a Dev → Test → Prod panel for the widget you're editing — or for every widget at once on the Admin Panel's <strong>Widget Promotion</strong> screen. Both do the same thing.</li>
                <li><strong>Promotion:</strong> <strong>Promote to Test</strong> copies Dev's latest saved version into Test; <strong>Promote to Prod</strong> copies Test's. Unsaved edits in the studio are not included, so save first. Each environment numbers its own versions, so Dev v8 may arrive in Test as v3.</li>
                <li><strong>Rollbacks:</strong> If a promoted widget misbehaves in Test or Prod, pick an older version from that environment's <strong>Roll back to</strong> list. It becomes the current version again straight away.</li>
                <li><strong>Certification:</strong> In Prod, <strong>Certify</strong> flags the current version as reviewed and enterprise-ready. It's a signal to end users, not a permission.</li>
              </ul>
              <p className="text-sm text-gray-500 italic">
                Promoting, rolling back and certifying need <strong>Editor</strong> or <strong>Admin</strong> rights on the widget's domain in the environment you're promoting into. Without them the panel shows where the widget stands but offers no buttons.
              </p>
            </div>

            <div className="bg-white p-5 border rounded-lg shadow-sm">
              <h3 className="text-lg font-semibold text-gray-900 mb-2">Promoting Views</h3>
              <p className="text-sm text-gray-600 mb-3">
                Similarly, global View Layouts are managed via the <strong>View Promotion</strong> screen. A view is promoted with all of its tabs.
              </p>
              <p className="text-sm text-gray-600 mb-3">
                <strong>Removing a global view:</strong> click <strong>Remove</strong> on its row (you need Editor or Admin on its domain). It disappears from everyone's sidebar in Dev, Test and Prod, but nothing is deleted. Open <strong>Archived</strong> at the top of the screen to <strong>Restore</strong> it exactly as it was, or to <strong>Delete permanently</strong>, which removes every version and cannot be undone. A global view has to be archived before it can be deleted.
              </p>
              <div className="bg-orange-50 border-l-4 border-orange-400 p-3 mt-2 text-sm text-orange-800">
                <strong>Before you confirm:</strong> the promotion dialog checks the target environment and lists any widget the view uses that isn't there yet. Leave <strong>Promote them too</strong> ticked to bring them along at their current version (you need Editor on each widget's domain); otherwise the view shows without them. It also warns about widgets pinned to a version that differs there, pinned agents that don't exist there, and widgets that still need certifying.
              </div>
            </div>
          </div>
        </div>
      ),
    },
    {
      id: 'migration',
      category: 'Admin Guide',
      title: 'Moving Data to Another App',
      icon: <ArrowRightLeft className="w-4 h-4" />,
      content: (
        <div className="space-y-6">
          <h2 className="text-2xl font-bold text-gray-900">Moving Data to Another App</h2>
          <p className="text-gray-600">
            Promotion moves single widgets and views between Dev, Test and Prod inside one app. Each deployment of the Command Center — the dev app, the test app, production — has a database of its own, though, so moving people from one app to another means moving the data with them. <strong>Admin Panel → Data Migration</strong> does that. It is available to Global Administrators.
          </p>
          <div className="bg-white border rounded-lg p-6 shadow-sm">
            <ol className="list-decimal pl-5 space-y-3 text-gray-700">
              <li>In the app that has the data, tick what to include and click <strong>Download snapshot</strong>. Widgets, views and agents (every version), categories, domains and role mappings, deployment settings, and activity history are included by default. Saved conversations and their attached files are off by default, because the file would then contain every user's chats.</li>
              <li>Open <strong>Data Migration</strong> in the other app and choose the file.</li>
              <li>Pick a mode. <strong>Merge</strong> adds only what this app is missing and changes nothing already here; running it twice adds nothing the second time. <strong>Replace</strong> makes the chosen parts an exact copy of the snapshot and deletes this app's own rows in them.</li>
              <li>Click <strong>Preview</strong>. It runs the whole import and then undoes it, and shows per table what would be added, skipped and deleted.</li>
              <li>Click <strong>Import</strong>. It is only offered for the file and options you just previewed.</li>
            </ol>
            <p className="text-sm text-gray-700 mt-4">
              An import is all-or-nothing: if anything fails, nothing is changed. A Replace that would remove your own global admin mapping is refused, so you can't lock yourself out. Both exports and imports are recorded in Action Logs. The apps never connect to each other — the file is the only thing that moves — so treat it like a database backup.
            </p>
          </div>
        </div>
      ),
    },
    {
      id: 'models',
      category: 'Admin Guide',
      title: 'Choosing Models',
      icon: <Settings className="w-4 h-4" />,
      content: (
        <div className="space-y-6">
          <h2 className="text-2xl font-bold text-gray-900">Choosing Models</h2>
          <p className="text-gray-600">
            Global Administrators choose which models power the AI features from <strong>Admin Panel → Settings</strong>. Each field suggests the chat-capable models your Databricks workspace offers, so there is nothing to type from memory and no redeploy involved — changes apply to new conversations and generations.
          </p>

          <div className="bg-white border rounded-lg p-6 shadow-sm">
            <h3 className="text-lg font-semibold text-gray-900 mb-3">The four models</h3>
            <ul className="list-disc pl-5 text-sm text-gray-700 space-y-2">
              <li><strong>Chat agent model</strong> — powers the assistant panel. An agent saved in Agent Studio can pin its own model, which wins for that agent only.</li>
              <li><strong>Widget generation model</strong> — writes widget code in Widget Studio. Prefer a model with a large output budget; long widgets are the ones that suffer from a small one.</li>
              <li><strong>Widget helper model</strong> — Widget Studio's quick jobs: summarising a long conversation so it stays affordable, and deciding whether a big request is worth a question first. Your request itself always goes to the widget generation model exactly as you wrote it. It defaults to <code>system.ai.gpt-6-luna</code>, asked to answer without reasoning so these stay quick. If your workspace doesn't serve that model, the widget generation model is used instead; enter the generation model's name here to use it on purpose.</li>
              <li><strong>Agent authoring model</strong> — drafts and reviews agents in Agent Studio.</li>
            </ul>
            <p className="text-sm text-gray-500 mt-4">
              Names beginning <code>system.ai.</code> are served through the AI Gateway; plain endpoint names go directly to a serving endpoint. Both work — the app routes each request according to the name you picked — and a model your workspace doesn't list can still be entered by hand.
            </p>
          </div>

          <div className="bg-white border rounded-lg p-6 shadow-sm">
            <h3 className="text-lg font-semibold text-gray-900 mb-3">Chat agent limits</h3>
            <ul className="list-disc pl-5 text-sm text-gray-700 space-y-2">
              <li><strong>Tool calls per turn</strong> — how many rounds of tools the assistant may run before it has to answer. Raise it if answers that need several queries stop short; lower it to cap cost per question.</li>
              <li><strong>Response length limit</strong> — a ceiling on one answer, in tokens. It costs nothing until an answer actually needs the room, so raise it if long answers are getting cut off. Models that allow less than the configured number are adjusted down to their own limit automatically.</li>
            </ul>
            <p className="text-sm text-gray-500 mt-4 italic">
              A label above each field shows whether the value was set here or inherited from the deployment's configuration. Only Global Administrators can view or change this page.
            </p>
          </div>

          <div className="bg-white border rounded-lg p-6 shadow-sm">
            <h3 className="text-lg font-semibold text-gray-900 mb-3">What the assistant may reach</h3>
            <p className="text-sm text-gray-700 mb-3">
              These switch capabilities off for the whole deployment. A tool that's off isn't offered to the assistant at all, so it won't try to use it and won't explain a refusal — it simply doesn't have it. An agent saved in Agent Studio can't re-enable one by listing it.
            </p>
            <ul className="list-disc pl-5 text-sm text-gray-700 space-y-2">
              <li><strong>Allow the assistant to query Genie</strong> — the one to reach for where Genie spaces can see data the assistant shouldn't. Unity Catalog policies that constrain other callers can't distinguish Genie, so this switch is the control that does. It also removes Genie from Widget Studio's and Agent Studio's research.</li>
              <li><strong>Allow the assistant to run SQL</strong> — removes the SQL and Unity Catalog tools, and SQL research in Widget Studio and Agent Studio. Widgets themselves are unaffected.</li>
              <li><strong>Send images and PDFs to the model directly</strong> — off, attachments are only ever read through text extraction, so no raw image or PDF is uploaded to the model. Scanned documents and screenshots stop working.</li>
              <li><strong>Tell the assistant what is on screen</strong> — off, questions no longer carry a summary of the current dashboard.</li>
              <li><strong>Global views may only contain certified widgets</strong> — off by default, because certification is applied when work is promoted to production and nothing in Dev or Test is certified yet. Turn it on where "shared with everyone" should mean "reviewed".</li>
              <li><strong>Enforce the Content Security Policy</strong> — leave on. Turning it off downgrades the policy to report-only, which logs violations in the browser console instead of blocking them; it exists for diagnosing a widget that has stopped rendering, not as a running configuration.</li>
              <li><strong>Delete conversations after (days)</strong> — deletes chats untouched for that long, attachments included, for every user. 0 keeps them indefinitely.</li>
            </ul>
          </div>

          <div className="bg-white border rounded-lg p-6 shadow-sm">
            <h3 className="text-lg font-semibold text-gray-900 mb-3">Who should be allowed to author Python tools</h3>
            <p className="text-sm text-gray-700">
              A Python tool written in Agent Studio runs on the server whenever its agent decides to call it. It runs in a restricted subprocess with the app's credentials removed and limits on time and memory, which prevents the common accidents — but that's a validation sandbox, not a jail, and it doesn't replace review.
            </p>
            <p className="text-sm text-gray-700 mt-3">
              Grant the editor rights that allow Python tool authoring only to people who have completed your organisation's secure-development training, and read a new Python tool before its agent is given domain or global visibility.
            </p>
          </div>
        </div>
      ),
    },
    {
      id: 'studio',
      category: 'User Guide',
      title: 'Widget Studio',
      icon: <Code className="w-4 h-4" />,
      content: (
        <div className="space-y-6">
          <h2 className="text-2xl font-bold text-gray-900">Widget Studio</h2>
          <p className="text-gray-600">
            The Widget Studio is the primary interface for creating and managing widgets. Built with an AI-driven approach, all simple and moderately complex widgets can be generated and built entirely within the browser without needing extensive React knowledge.
          </p>

          <div className="space-y-6 mt-6">
            <div>
              <h3 className="text-lg font-semibold text-gray-800 mb-2">1. Configuring the Widget</h3>
              <ul className="list-disc pl-5 text-gray-700 space-y-2">
                <li><strong>Metadata:</strong> Provide a Name, Description, and select a Category.</li>
                <li><strong>Domain:</strong> Assign the widget to a Domain to enforce RBAC.</li>
                <li><strong>Data Source:</strong> Choose None, API, Databricks API, or SQL. <strong>Test &amp; Extract Schema</strong> shows the schema — real column types for SQL — and a few sample rows, and the agent is given both when it writes your widget. Tests run with your own permissions. A SQL statement that changes data is never run to test it; the studio tells you so instead. An external API is called from your browser, the same way the widget will call it, so if the API blocks requests from this app you find out here. Testing a SQL source also counts the rows it returns, and that number changes how the widget gets built. Searching, sorting and paging can happen in the browser or in the query, and both work at any row count; what decides is how much data the browser would have to download, roughly 10 MB. Under that the widget fetches everything once and works locally, which is fastest. Over it, all of that is pushed into SQL so the widget only ever holds the page you are looking at. An untested source is assumed to be large. By default a query returns its first 500 rows; a widget that works on the whole result asks for more, and says so when it is showing only part of the data.</li>
                <li><strong>Is Executable Action:</strong> Toggle this to indicate whether the widget performs an action (e.g., submitting a form). This is essential for telemetry collection. If your SQL data source changes data — INSERT, UPDATE, DELETE, MERGE — this is required, and saving is refused without it, because it's what records each change in Action Logs along with who made it.</li>
                <li><strong>Configuration Mode:</strong> Dictate if end-users can provide runtime inputs (like changing a URL or a parameter threshold) to the widget when placing it on a dashboard.</li>
              </ul>
            </div>

            <div>
              <h3 className="text-lg font-semibold text-gray-800 mb-2">What a widget may contain</h3>
              <p className="text-gray-700 mb-2">
                Saving is refused if the code uses <code>eval</code>, <code>new Function</code>, <code>document.write</code>, <code>innerHTML</code> or <code>dangerouslySetInnerHTML</code>, or if it references any address other than this app's own <code>/api/...</code> paths and the approved CDNs — cdn.jsdelivr.net, code.highcharts.com, unpkg.com and cdnjs.cloudflare.com. The browser enforces the same list independently, so an off-list script won't load even if it reached the database another way.
              </p>
              <p className="text-gray-700">
                If a save is refused, the message names what tripped it. The usual cause is a library pulled from a CDN that isn't on the list: ask the agent for the jsDelivr copy instead.
              </p>
            </div>

            <div>
              <h3 className="text-lg font-semibold text-gray-800 mb-2">Cards and pages</h3>
              <p className="text-gray-700">
                The <strong>Card</strong> / <strong>Page</strong> switch above the preview says what you are building. A card sits on a tab with other widgets. A page fills a whole tab of a view and brings its own background and layout, for a landing page or hub; attach a picture of the page you want and the agent works from it. If your first request asks for a landing page, hub or full-screen page the studio starts it as a page and says so, and you can switch either way at any time. A page previews under a stand-in header and tabs at <strong>Laptop</strong>, <strong>Wide</strong> or <strong>Narrow</strong> width, scaled to fit. Classes like <code>md:</code> and <code>lg:</code> follow your browser window rather than that frame, so narrow the window to check a small-screen layout. Its buttons say what they would do in a view instead of doing it. Cards that name a part of the view, such as a persona, open the tab with that name when the view has one, so name your tabs to match. Pages are marked <strong>PAGE</strong> in the Widget Library; drag one onto a page tab.
              </p>
            </div>

            <div>
              <h3 className="text-lg font-semibold text-gray-800 mb-2">Widgets that steer the view</h3>
              <p className="text-gray-700">
                A widget can open the view's other tabs and open the assistant with an agent chosen and a question typed in — ask for "tiles that go to each tab" or "an Ask about this button". For plain tiles to each tab, the built-in <strong>Tab links</strong> widget needs no Studio at all. If a widget opens a tab by a name the view doesn't have, its editors see a note on it; rename a tab to match or change the widget. It never sends the question for you: you read it and press <strong>Send</strong>. It can't open other views or addresses.
              </p>
            </div>

            <div>
              <h3 className="text-lg font-semibold text-gray-800 mb-2">2. AI Generation, Editor & Preview</h3>
              <p className="text-gray-700 mb-2">
                Switch to the TSX Editor to view the code. Instead of writing everything from scratch, you can use natural language prompts to have the AI generate your widget based on your Data Source schemas.
              </p>
              <p className="text-gray-700 mb-2">
                The editor provides real-time rendering logic. Make sure your component scales dynamically and utilizes the Tailwind CSS classes supported natively. Toggle the <strong>Preview</strong> mode to test appearance and behavior live.
              </p>
              <p className="text-gray-700">
                While the agent works, expand <strong>Thinking</strong> to see how it read your request, the steps it planned, and anything it decided to skip. On a large or vague request it may come back with up to three questions instead of code — answer the ones that matter, or press <strong>Build it anyway</strong> and it will pick sensible defaults. Two minutes of questions is cheaper than ten minutes spent building the wrong widget.
              </p>
              <p className="text-gray-700 mt-2">
                The agent can also <strong>look at your data</strong> before it writes anything. It runs read-only SQL on the app's warehouse and can ask Genie, both as you, so it sees only what you are allowed to see. Name the table you mean (<code>main.supply.shipments</code>) and it checks the real column names and values rather than guessing them; each query it ran appears under <strong>Thinking</strong>. It never changes data, and what it learns shapes the code rather than being pasted in as fixed numbers. Each step of a multi-step build can do the same, and the agent runs any SQL it writes once before handing the code back.
              </p>
              <p className="text-gray-700 mt-2">
                The studio also <strong>watches the preview run</strong>: every request the widget makes and how many rows came back, anything it logs as an error, and errors it throws. When code the agent just wrote fails as it runs — a query rejected as invalid, a crash while handling the data — the agent is sent what happened and fixes it on its own, up to twice. It leaves alone failures that code can't fix: a permission error, a server error, or your configured data source itself failing, which you fix on the Configuration tab.
              </p>
              <p className="text-gray-700 mt-2">
                <strong>Problems</strong>, the bar under the preview and the code, lists rule checks on the code — an import widgets can't use, a script from a CDN that isn't allowed, a write that skips the audit trail, text too light to read, a class the app's stylesheet doesn't have (so it does nothing), a font that isn't bundled — and what happened when the widget last ran. The agent is given both with every request. <strong>Fix with agent</strong> asks it to fix everything listed. Rule errors in code the agent wrote are fixed automatically; warnings are left for you to decide.
              </p>
            </div>

            <div>
              <h3 className="text-lg font-semibold text-gray-800 mb-2">3. Showing the Agent What You Mean</h3>
              <p className="text-gray-700 mb-2">
                The paperclip beside the message box attaches spreadsheets, documents and images for the agent to read — a sample export, say, or a design someone sent you. Below the preview, <strong>Send screenshot to agent</strong> attaches a picture of the widget exactly as it looks right now, at the size you have dragged it to.
              </p>
              <p className="text-gray-700">
                Neither one sends by itself. The file waits on your next message, so "this column is too narrow and the total is in the wrong place" arrives alongside the thing it is describing. Grabbing a second screenshot replaces the first.
              </p>
            </div>

            <div>
              <h3 className="text-lg font-semibold text-gray-800 mb-2">4. Agent Settings</h3>
              <p className="text-gray-700 mb-2">
                The sliders icon above the chat holds two options. Both are remembered in your browser, so they are yours rather than everyone's.
              </p>
              <ul className="list-disc pl-5 text-gray-700 space-y-2">
                <li><strong>Conduct review after change</strong> (off by default): once new code compiles and has run in the preview, the agent reads it back as a reviewer, with a screenshot of how it rendered and what happened when it ran — does it do everything you asked, does it handle loading, empty and error states, does it hold up squashed narrow and stretched wide, is every text color dark enough to read — and fixes what it finds. It then steps back and answers a different question under <strong>Worth considering</strong>: is this widget actually good at its job, and what are the two or three changes that would most improve it. Those are suggestions only — it never builds them unasked, so you can leave the setting on without the widget growing behind your back. Each one appears as a chip under <strong>Do next</strong>, along with an amber chip for anything it found but didn't fix; clicking one writes that instruction into the message box for you to edit or send, so you never have to retype a suggestion to act on it. It costs an extra turn, which is why you have to ask for it.</li>
                <li><strong>Ask before large builds</strong> (on by default): the clarifying questions described above. Turn it off if you would rather it always guessed and got straight to work.</li>
              </ul>
            </div>

            <div>
              <h3 className="text-lg font-semibold text-gray-800 mb-2">5. Save and Publish</h3>
              <p className="text-gray-700">
                <strong>Save</strong> (or <strong>Publish</strong>, the first time) writes your code to the Dev environment database and increments the version, and it is immediately available in the Widget Library for users with Dev access to test. Saving leaves you in the studio, so you can keep working and save as often as you like. The <strong>X</strong> closes the studio when you have finished with the widget.
              </p>
              <p className="text-gray-700 mt-2">
                Controls for the widget sit on the right, above the preview: <strong>History</strong>, <strong>Reload</strong>, <strong>Promote</strong> (see <em>Promoting Work</em>), the <strong>⋯</strong> menu with Import, Export and Reset studio, then Save and close. Only the agent's own settings sit above the chat.
              </p>
            </div>

            <div>
              <h3 className="text-lg font-semibold text-gray-800 mb-2">6. Stopping the Agent</h3>
              <p className="text-gray-700">
                While the agent works, the send button turns into a red <strong>Stop</strong> button, and pressing Enter does nothing, so you can type your next request without interrupting it. Stop ends the turn at once: steps that already finished stay in the editor, each with an entry in History, and nothing else is applied. On a multi-step build, <strong>Stop after this step</strong> lets the step in progress finish first.
              </p>
            </div>
          </div>
        </div>
      ),
    }
  ];

  const userGuideSections = sections.filter(s => s.category === 'User Guide');
  const adminGuideSections = sections.filter(s => s.category === 'Admin Guide');

  return (
    <div className="flex h-full bg-white">
      {/* Left Sidebar Menu */}
      <div className="w-64 border-r border-gray-200 bg-gray-50 flex flex-col">
        <div className="p-4 border-b border-gray-200">
          <h1 className="text-lg font-bold text-brand-navy flex items-center gap-2">
            <Book className="w-5 h-5 text-brand-blue" />
            Documentation
          </h1>
        </div>
        <nav className="flex-1 overflow-y-auto p-4 space-y-6">
          {([
            ['User Guide', userGuideSections],
            ['Admin Guide', adminGuideSections],
          ] as const).map(([label, group]) => (
            <div key={label}>
              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 px-3">
                {label}
              </h3>
              <div className="space-y-1">
                {group.map((section) => (
                  <button
                    key={section.id}
                    onClick={() => setActiveSection(section.id)}
                    className={clsx(
                      "w-full flex items-center gap-3 px-3 py-2 text-sm font-medium rounded-md transition-colors text-left",
                      activeSection === section.id
                        ? "bg-brand-blue text-white"
                        : "text-gray-600 hover:bg-gray-200 hover:text-gray-900"
                    )}
                  >
                    {React.cloneElement(section.icon as React.ReactElement<any>, {
                      className: clsx(
                        "w-4 h-4",
                        activeSection === section.id ? "text-white" : "text-gray-400"
                      )
                    })}
                    {section.title}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </nav>
      </div>

      {/* Main Content Area */}
      <div className="flex-1 overflow-y-auto p-8">
        <div className="max-w-3xl mx-auto">
          {sections.find(s => s.id === activeSection)?.content}
        </div>
      </div>
    </div>
  );
};
