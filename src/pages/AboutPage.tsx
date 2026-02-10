import React from 'react';
import { Info, ArrowLeft, Code, Users, Shield, Zap } from 'lucide-react';

interface AboutPageProps {
  onNavigate: (page: string | null) => void;
}

export const AboutPage: React.FC<AboutPageProps> = ({ onNavigate }) => {

  const features = [
    {
      icon: Zap,
      title: 'Real-time Updates',
      description: 'Get live data updates across all your dashboards'
    },
    {
      icon: Shield,
      title: 'Secure & Private',
      description: 'Your data is encrypted and stored securely'
    },
    {
      icon: Users,
      title: 'Team Collaboration',
      description: 'Share dashboards and collaborate with your team'
    },
    {
      icon: Code,
      title: 'Customizable',
      description: 'Build custom widgets and tailor your experience'
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
          <Info className="w-5 h-5 text-qualcomm-blue" />
          <h1 className="text-lg font-semibold text-qualcomm-navy">About</h1>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-6 bg-gray-50">
        <div className="max-w-4xl mx-auto space-y-6">
          {/* Main About Section */}
          <div className="bg-white border border-gray-200 rounded-lg p-8 text-center">
            <div className="w-20 h-20 bg-qualcomm-blue rounded-full flex items-center justify-center mx-auto mb-4">
              <Info className="w-10 h-10 text-white" />
            </div>
            <h2 className="text-3xl font-bold text-qualcomm-navy mb-3">Command Center</h2>
            <p className="text-lg text-gray-600 mb-2">Version 1.0.0</p>
            <p className="text-gray-500 max-w-2xl mx-auto">
              A powerful supply chain management dashboard that helps you monitor, analyze, and optimize your operations in real-time.
            </p>
          </div>

          {/* Features */}
          <div className="bg-white border border-gray-200 rounded-lg p-6">
            <h3 className="text-xl font-semibold text-qualcomm-navy mb-6">Key Features</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {features.map((feature, index) => {
                const Icon = feature.icon;
                return (
                  <div key={index} className="flex items-start gap-4 p-4 hover:bg-gray-50 rounded-md transition-colors">
                    <div className="p-2 bg-qualcomm-blue/10 rounded-lg">
                      <Icon className="w-5 h-5 text-qualcomm-blue" />
                    </div>
                    <div>
                      <h4 className="font-semibold text-qualcomm-navy mb-1">{feature.title}</h4>
                      <p className="text-sm text-gray-600">{feature.description}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Company Info */}
          <div className="bg-white border border-gray-200 rounded-lg p-6">
            <h3 className="text-xl font-semibold text-qualcomm-navy mb-4">About Qualcomm</h3>
            <p className="text-gray-600 mb-4">
              Qualcomm is a leading technology company that invents breakthrough technologies that transform how the world connects, computes, and communicates.
            </p>
            <div className="space-y-2 text-sm text-gray-600">
              <p><strong className="text-qualcomm-navy">Company:</strong> Qualcomm Technologies, Inc.</p>
              <p><strong className="text-qualcomm-navy">Website:</strong> <a href="https://www.qualcomm.com" target="_blank" rel="noopener noreferrer" className="text-qualcomm-blue hover:underline">www.qualcomm.com</a></p>
            </div>
          </div>

          {/* Technical Info */}
          <div className="bg-white border border-gray-200 rounded-lg p-6">
            <h3 className="text-xl font-semibold text-qualcomm-navy mb-4">Technical Information</h3>
            <div className="space-y-2 text-sm text-gray-600">
              <p><strong className="text-qualcomm-navy">Built with:</strong> React, TypeScript, Tailwind CSS</p>
              <p><strong className="text-qualcomm-navy">Backend:</strong> FastAPI, Python</p>
              <p><strong className="text-qualcomm-navy">Data Platform:</strong> Databricks</p>
            </div>
          </div>

          {/* Copyright */}
          <div className="text-center text-sm text-gray-500 pt-4">
            <p>© {new Date().getFullYear()} Qualcomm Technologies, Inc. All rights reserved.</p>
          </div>
        </div>
      </div>
    </div>
  );
};

