import React from 'react';
import { Settings, ArrowLeft } from 'lucide-react';

interface SettingsPageProps {
  onNavigate: (page: string | null) => void;
}

export const SettingsPage: React.FC<SettingsPageProps> = ({ onNavigate }) => {

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
          <Settings className="w-5 h-5 text-qualcomm-blue" />
          <h1 className="text-lg font-semibold text-qualcomm-navy">Settings</h1>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-6">
        <div className="max-w-4xl mx-auto space-y-6">
          {/* General Settings */}
          <section className="bg-white border border-gray-200 rounded-lg p-6">
            <h2 className="text-lg font-semibold text-qualcomm-navy mb-4">General Settings</h2>
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <label className="text-sm font-medium text-gray-700">Theme</label>
                  <p className="text-xs text-gray-500 mt-1">Choose your preferred theme</p>
                </div>
                <select className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-qualcomm-blue">
                  <option>Light</option>
                  <option>Dark</option>
                  <option>System</option>
                </select>
              </div>
              <div className="border-t border-gray-200 pt-4">
                <div className="flex items-center justify-between">
                  <div>
                    <label className="text-sm font-medium text-gray-700">Notifications</label>
                    <p className="text-xs text-gray-500 mt-1">Enable email notifications</p>
                  </div>
                  <label className="relative inline-flex items-center cursor-pointer">
                    <input type="checkbox" className="sr-only peer" defaultChecked />
                    <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-qualcomm-blue/20 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-qualcomm-blue"></div>
                  </label>
                </div>
              </div>
            </div>
          </section>

          {/* Dashboard Settings */}
          <section className="bg-white border border-gray-200 rounded-lg p-6">
            <h2 className="text-lg font-semibold text-qualcomm-navy mb-4">Dashboard Settings</h2>
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <label className="text-sm font-medium text-gray-700">Default Grid Size</label>
                  <p className="text-xs text-gray-500 mt-1">Number of columns in the grid</p>
                </div>
                <input
                  type="number"
                  defaultValue={12}
                  min={6}
                  max={24}
                  className="w-20 px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-qualcomm-blue"
                />
              </div>
              <div className="border-t border-gray-200 pt-4">
                <div className="flex items-center justify-between">
                  <div>
                    <label className="text-sm font-medium text-gray-700">Auto-save</label>
                    <p className="text-xs text-gray-500 mt-1">Automatically save dashboard changes</p>
                  </div>
                  <label className="relative inline-flex items-center cursor-pointer">
                    <input type="checkbox" className="sr-only peer" defaultChecked />
                    <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-qualcomm-blue/20 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-qualcomm-blue"></div>
                  </label>
                </div>
              </div>
            </div>
          </section>

          {/* Account Settings */}
          <section className="bg-white border border-gray-200 rounded-lg p-6">
            <h2 className="text-lg font-semibold text-qualcomm-navy mb-4">Account</h2>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Email</label>
                <input
                  type="email"
                  defaultValue="user@qualcomm.com"
                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-qualcomm-blue"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Language</label>
                <select className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-qualcomm-blue">
                  <option>English</option>
                  <option>Spanish</option>
                  <option>French</option>
                  <option>German</option>
                </select>
              </div>
            </div>
          </section>

          {/* Save Button */}
          <div className="flex justify-end">
            <button className="px-6 py-2 bg-qualcomm-blue hover:bg-blue-600 text-white rounded-md text-sm font-medium transition-colors">
              Save Changes
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

