import React, { useState } from 'react';
import { Book, Shield, Layers, Code, PlayCircle, Settings, Users, LayoutGrid, MousePointerClick, Lock, Copy, PlusCircle } from 'lucide-react';
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
                <li><strong>Data Source:</strong> Choose None, API, or SQL. Test and extract schemas to make data available to the AI when generating your widget.</li>
                <li><strong>Is Executable Action:</strong> Toggle this to indicate whether the widget performs an action (e.g., submitting a form). This is essential for telemetry collection.</li>
                <li><strong>Configuration Mode:</strong> Dictate if end-users can provide runtime inputs (like changing a URL or a parameter threshold) to the widget when placing it on a dashboard.</li>
              </ul>
            </div>

            <div>
              <h3 className="text-lg font-semibold text-gray-800 mb-2">2. AI Generation, Editor & Preview</h3>
              <p className="text-gray-700 mb-2">
                Switch to the TSX Editor to view the code. Instead of writing everything from scratch, you can use natural language prompts to have the AI generate your widget based on your Data Source schemas.
              </p>
              <p className="text-gray-700">
                The editor provides real-time rendering logic. Make sure your component scales dynamically and utilizes the Tailwind CSS classes supported natively. Toggle the <strong>Preview</strong> mode to test appearance and behavior live.
              </p>
            </div>

            <div>
              <h3 className="text-lg font-semibold text-gray-800 mb-2">3. Publish</h3>
              <p className="text-gray-700">
                When you click <strong>Publish</strong> or <strong>Update</strong>, your code is saved to the Dev environment database and is immediately available in the Widget Library for users with Dev access to test.
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
          {/* User Guide Category */}
          <div>
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 px-3">
              User Guide
            </h3>
            <div className="space-y-1">
              {userGuideSections.map((section) => (
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

          {/* Admin Guide Category */}
          <div>
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 px-3">
              Admin Guide
            </h3>
            <div className="space-y-1">
              {adminGuideSections.map((section) => (
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
