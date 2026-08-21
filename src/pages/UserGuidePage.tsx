import React, { useState } from 'react';
import { Book, Shield, Layers, Code, PlayCircle, Settings, Users, LayoutGrid, MousePointerClick, Lock, Copy, PlusCircle, Bot, Paperclip, History } from 'lucide-react';
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
            Your workspace is organized into "Views", which act like different tabs or pages that you can customize.
          </p>
          
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-6">
            <div className="bg-white p-5 border rounded-lg shadow-sm">
              <div className="font-semibold text-gray-900 flex items-center gap-2 mb-2">
                <PlusCircle className="w-4 h-4 text-blue-500" />
                Creating a View
              </div>
              <p className="text-sm text-gray-600">
                Click <strong>New View</strong> in the left sidebar to create a fresh, blank canvas. You can rename your view by clicking the pencil icon next to its name.
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
                Want to show someone your setup? Click the <strong>Share</strong> button in the top-right corner to copy a direct link to your current view.
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
              <p className="text-sm text-gray-600">Has all Viewer privileges. Can also create, edit, and reorganize widgets and global views within this domain.</p>
            </div>
            <div className="bg-white p-4 border rounded-lg shadow-sm">
              <div className="font-semibold text-gray-900 flex items-center gap-2 mb-2">
                <Settings className="w-4 h-4 text-purple-500" />
                Admin
              </div>
              <p className="text-sm text-gray-600">Has full control. Can promote widgets/views across environments, certify widgets in production, and assign domain permissions to users or groups.</p>
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
            Domain Administrators can manage who has access to their domains seamlessly from the Command Center UI, without needing database or code changes.
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
              Because permissions are driven by Databricks, granting access means creating a "Mapping" between a Databricks Group/Role and a Command Center Domain.
            </p>
            <ol className="list-decimal pl-5 space-y-3 text-gray-700">
              <li>Navigate to the <strong>Admin Panel</strong> by clicking on the shield icon in the left navigation sidebar.</li>
              <li>Under the <strong>Access Management</strong> tab, you will see a table of all existing role mappings.</li>
              <li>Under "Create New Mapping", enter the exact name of the Databricks role or group (e.g., <code>finance-team</code> or <code>supply-chain-viewers</code>).</li>
              <li>Type in the name of the Domain you wish to grant access to (e.g., <code>Finance</code>).</li>
              <li>Select the appropriate Permission Level: <code>Viewer</code>, <code>Editor</code>, or <code>Admin</code>.</li>
              <li>Click <strong>Add Role Mapping</strong>. The backend will automatically apply this permission to any user belonging to that Databricks group upon their next session.</li>
            </ol>
            <p className="text-sm text-gray-500 mt-4 italic">
              Note: Administrators can only create or delete mappings for domains to which they have been explicitly granted admin rights (unless they are a Global Admin).
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
                <li><strong>Promotion:</strong> To push a tested widget to a higher environment (e.g., from Dev to Test, or Test to Prod), navigate to the <strong>Widget Promotion</strong> screen. Locate your widget, find the target environment column, and select the higher version from the dropdown. The system will copy that specific version's definition into the target environment.</li>
                <li><strong>Rollbacks:</strong> If a newly promoted widget introduces a bug in Test or Prod, you can instantly revert to a previous stable state. In the same dropdown, simply select an older version number. The application immediately restores the widget to that exact historical configuration.</li>
                <li><strong>Certification:</strong> In the Production column, clicking the <strong>Certify</strong> button formally flags a widget as enterprise-ready. This is a visual indicator for end-users that the widget has passed review and is reliable.</li>
              </ul>
              <p className="text-sm text-gray-500 italic">
                Only users with <strong>Admin</strong> rights for a widget's domain can perform promotions, rollbacks, and certifications.
              </p>
            </div>

            <div className="bg-white p-5 border rounded-lg shadow-sm">
              <h3 className="text-lg font-semibold text-gray-900 mb-2">Promoting Views</h3>
              <p className="text-sm text-gray-600 mb-3">
                Similarly, global View Layouts are managed via the <strong>View Promotion</strong> screen. 
              </p>
              <div className="bg-orange-50 border-l-4 border-orange-400 p-3 mt-2 text-sm text-orange-800">
                <strong>Important:</strong> Before promoting a view to a higher environment, ensure that all widgets used within that view have already been promoted. If a view references a widget that isn't available in the target environment, the view will fail to render correctly.
              </div>
            </div>
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
              <li><strong>Widget helper model</strong> — Widget Studio's quick jobs: tightening up a vague request before the expensive call, summarising a long conversation so it stays affordable, and deciding whether a request is worth a question first. A small, fast model is the right choice here, and leaving it blank uses the widget generation model for these too.</li>
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
                <li><strong>Data Source:</strong> Choose None, API, or SQL. Test and extract schemas to make data available to the AI when generating your widget. Testing a SQL source also counts the rows it returns, and that number changes how the widget gets built: a few thousand rows are fetched once and sorted, filtered and paged in the browser, while a large table has all of that pushed into SQL so the widget only ever holds the page you are looking at. An untested source is assumed to be large.</li>
                <li><strong>Is Executable Action:</strong> Toggle this to indicate whether the widget performs an action (e.g., submitting a form). This is essential for telemetry collection.</li>
                <li><strong>Configuration Mode:</strong> Dictate if end-users can provide runtime inputs (like changing a URL or a parameter threshold) to the widget when placing it on a dashboard.</li>
              </ul>
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
                <li><strong>Conduct review after change</strong> (off by default): once new code compiles, the agent reads it back as a reviewer — does it do everything you asked, does it handle loading, empty and error states, does it hold up squashed narrow and stretched wide, is every text colour dark enough to read — and fixes what it finds. It then steps back and answers a different question under <strong>Worth considering</strong>: is this widget actually good at its job, and what are the two or three changes that would most improve it. Those are suggestions only — it never builds them unasked, so you can leave the setting on without the widget growing behind your back. Each one appears as a chip under <strong>Do next</strong>, along with an amber chip for anything it found but didn't fix; clicking one writes that instruction into the message box for you to edit or send, so you never have to retype a suggestion to act on it. It costs an extra turn, which is why you have to ask for it.</li>
                <li><strong>Ask before large builds</strong> (on by default): the clarifying questions described above. Turn it off if you would rather it always guessed and got straight to work.</li>
              </ul>
            </div>

            <div>
              <h3 className="text-lg font-semibold text-gray-800 mb-2">5. Save and Publish</h3>
              <p className="text-gray-700">
                <strong>Save</strong> (or <strong>Publish</strong>, the first time) writes your code to the Dev environment database and increments the version, and it is immediately available in the Widget Library for users with Dev access to test. Saving leaves you in the studio, so you can keep working and save as often as you like. Use <strong>Done</strong> when you have finished with the widget.
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
          <h1 className="text-lg font-bold text-qualcomm-navy flex items-center gap-2">
            <Book className="w-5 h-5 text-qualcomm-blue" />
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
                        ? "bg-qualcomm-blue text-white"
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
