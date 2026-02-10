import React from 'react';
import { HelpCircle, ArrowLeft, Book, Video, MessageCircle, FileText } from 'lucide-react';

interface HelpPageProps {
  onNavigate: (page: string | null) => void;
}

export const HelpPage: React.FC<HelpPageProps> = ({ onNavigate }) => {

  const helpSections = [
    {
      icon: Book,
      title: 'Getting Started',
      description: 'Learn the basics of using the Command Center dashboard',
      items: [
        'Creating your first dashboard',
        'Adding widgets to your dashboard',
        'Customizing widget layouts',
        'Sharing dashboards with your team'
      ]
    },
    {
      icon: Video,
      title: 'Video Tutorials',
      description: 'Watch step-by-step video guides',
      items: [
        'Dashboard overview (5 min)',
        'Widget library tour (3 min)',
        'Advanced customization (10 min)',
        'Best practices (8 min)'
      ]
    },
    {
      icon: FileText,
      title: 'Documentation',
      description: 'Comprehensive guides and references',
      items: [
        'User guide',
        'Widget reference',
        'Keyboard shortcuts',
        'Troubleshooting'
      ]
    },
    {
      icon: MessageCircle,
      title: 'Support',
      description: 'Get help from our support team',
      items: [
        'Contact support',
        'Submit a ticket',
        'Community forum',
        'FAQ'
      ]
    }
  ];

  return (
    <div className="h-full flex flex-col bg-white">
      {/* Header */}
      <div className="h-14 bg-white border-b border-gray-200 flex items-center gap-4 px-6">
        <button
          onClick={() => onNavigate(null)}
          className="p-2 hover:bg-gray-100 rounded-md transition-colors"
          title="Back to Dashboard"
        >
          <ArrowLeft className="w-5 h-5 text-gray-600" />
        </button>
        <div className="flex items-center gap-3">
          <HelpCircle className="w-5 h-5 text-qualcomm-blue" />
          <h1 className="text-lg font-semibold text-qualcomm-navy">Help & Support</h1>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-6 bg-gray-50">
        <div className="max-w-6xl mx-auto">
          {/* Welcome Section */}
          <div className="bg-white border border-gray-200 rounded-lg p-8 mb-6 text-center">
            <HelpCircle className="w-16 h-16 text-qualcomm-blue mx-auto mb-4" />
            <h2 className="text-2xl font-semibold text-qualcomm-navy mb-2">How can we help you?</h2>
            <p className="text-gray-600 max-w-2xl mx-auto">
              Find answers to common questions, learn how to use features, and get support when you need it.
            </p>
          </div>

          {/* Help Sections Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {helpSections.map((section, index) => {
              const Icon = section.icon;
              return (
                <div key={index} className="bg-white border border-gray-200 rounded-lg p-6 hover:shadow-md transition-shadow">
                  <div className="flex items-start gap-4">
                    <div className="p-3 bg-qualcomm-blue/10 rounded-lg">
                      <Icon className="w-6 h-6 text-qualcomm-blue" />
                    </div>
                    <div className="flex-1">
                      <h3 className="text-lg font-semibold text-qualcomm-navy mb-2">{section.title}</h3>
                      <p className="text-sm text-gray-600 mb-4">{section.description}</p>
                      <ul className="space-y-2">
                        {section.items.map((item, itemIndex) => (
                          <li key={itemIndex} className="text-sm text-gray-700 flex items-start gap-2">
                            <span className="text-qualcomm-blue mt-1">•</span>
                            <span>{item}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Quick Links */}
          <div className="mt-6 bg-white border border-gray-200 rounded-lg p-6">
            <h3 className="text-lg font-semibold text-qualcomm-navy mb-4">Quick Links</h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <button className="text-left p-4 border border-gray-200 rounded-md hover:border-qualcomm-blue hover:bg-qualcomm-blue/5 transition-colors">
                <div className="font-medium text-qualcomm-navy mb-1">Keyboard Shortcuts</div>
                <div className="text-sm text-gray-600">View all available shortcuts</div>
              </button>
              <button className="text-left p-4 border border-gray-200 rounded-md hover:border-qualcomm-blue hover:bg-qualcomm-blue/5 transition-colors">
                <div className="font-medium text-qualcomm-navy mb-1">Report a Bug</div>
                <div className="text-sm text-gray-600">Let us know about issues</div>
              </button>
              <button className="text-left p-4 border border-gray-200 rounded-md hover:border-qualcomm-blue hover:bg-qualcomm-blue/5 transition-colors">
                <div className="font-medium text-qualcomm-navy mb-1">Feature Request</div>
                <div className="text-sm text-gray-600">Suggest new features</div>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

