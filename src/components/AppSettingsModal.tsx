import React, { useRef, useState } from 'react';
import { X, Settings2, Upload, Trash2 } from 'lucide-react';
import clsx from 'clsx';
import { useDashboardStore } from '../store/dashboardStore';
import { imageProblem, MAX_NAME_LENGTH, type App, type AppSpec } from '../store/appSpec';

const readAsDataUrl = (file: File): Promise<string> =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });

const ImageField: React.FC<{
  label: string;
  hint: string;
  value: string;
  onChange: (value: string) => void;
}> = ({ label, hint, value, onChange }) => {
  const fileInput = useRef<HTMLInputElement>(null);
  const [readError, setReadError] = useState<string | null>(null);
  const problem = readError || imageProblem(value);
  const isUpload = value.startsWith('data:');

  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">{label}</label>
      <div className="flex items-center gap-2">
        {value && !problem && (
          <img src={value} alt="" className="w-8 h-8 object-contain rounded border border-gray-200 bg-white shrink-0" />
        )}
        <input
          type="text"
          value={isUpload ? 'Uploaded image' : value}
          readOnly={isUpload}
          onChange={e => { setReadError(null); onChange(e.target.value.trim()); }}
          placeholder="https://…"
          className="flex-1 min-w-0 px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-brand-blue/40 read-only:bg-gray-50 read-only:text-gray-500"
        />
        <button
          type="button"
          onClick={() => fileInput.current?.click()}
          className="p-1.5 text-gray-500 hover:text-brand-blue hover:bg-gray-100 rounded-md"
          title="Upload an image"
        >
          <Upload className="w-4 h-4" />
        </button>
        {value && (
          <button
            type="button"
            onClick={() => { setReadError(null); onChange(''); }}
            className="p-1.5 text-gray-500 hover:text-red-600 hover:bg-gray-100 rounded-md"
            title={`Remove the ${label.toLowerCase()}`}
          >
            <Trash2 className="w-4 h-4" />
          </button>
        )}
        <input
          ref={fileInput}
          type="file"
          accept="image/png,image/jpeg,image/gif,image/webp,image/svg+xml,image/x-icon,.ico"
          className="hidden"
          onChange={async e => {
            const file = e.target.files?.[0];
            e.target.value = '';
            if (!file) return;
            try {
              setReadError(null);
              onChange(await readAsDataUrl(file));
            } catch {
              setReadError('That file could not be read.');
            }
          }}
        />
      </div>
      <p className={clsx('text-xs mt-1', problem ? 'text-red-600' : 'text-gray-500')}>{problem || hint}</p>
    </div>
  );
};

/**
 * How a view opens from its link, and how it looks and talks when it opens on
 * its own. Changing any of it is the same right as renaming the view.
 */
export const AppSettingsModal: React.FC<{ app: App; onClose: () => void }> = ({ app, onClose }) => {
  const { updateAppSpec } = useDashboardStore();
  const branding = app.spec.branding || {};
  const [presentation, setPresentation] = useState<AppSpec['presentation']>(app.spec.presentation);
  const [title, setTitle] = useState(branding.title || '');
  const [logo, setLogo] = useState(branding.logo || '');
  const [favicon, setFavicon] = useState(branding.favicon || '');
  const [assistant, setAssistant] = useState<AppSpec['assistant']>(app.spec.assistant);
  const [assistantName, setAssistantName] = useState(branding.assistant_name || '');
  const [saving, setSaving] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);

  const invalid = Boolean(imageProblem(logo) || imageProblem(favicon));

  const save = async () => {
    setSaving(true);
    setRefusal(null);
    const reason = await updateAppSpec(app.id, {
      ...app.spec,
      presentation,
      assistant,
      branding: {
        title: title.trim() || null,
        logo: logo || null,
        favicon: favicon || null,
        assistant_name: assistantName.trim() || null,
      },
    });
    setSaving(false);
    if (reason) setRefusal(reason);
    else onClose();
  };

  const choice = (value: AppSpec['presentation'], label: string, detail: string) => (
    <label
      className={clsx(
        'flex items-start gap-3 p-3 border rounded-md cursor-pointer transition-colors',
        presentation === value ? 'border-brand-blue bg-brand-blue/5' : 'border-gray-200 hover:border-gray-300'
      )}
    >
      <input
        type="radio"
        name="presentation"
        className="mt-1"
        checked={presentation === value}
        onChange={() => setPresentation(value)}
      />
      <span>
        <span className="block text-sm font-medium text-gray-800">{label}</span>
        <span className="block text-xs text-gray-500">{detail}</span>
      </span>
    </label>
  );

  return (
    <div className="fixed inset-0 bg-black/50 z-[60] flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="bg-white rounded-lg shadow-xl w-full max-w-lg flex flex-col max-h-[90vh]"
        onClick={e => e.stopPropagation()}
        role="dialog"
        aria-label="View settings"
      >
        <div className="flex items-center justify-between p-4 border-b border-gray-200">
          <div className="flex items-center gap-2">
            <Settings2 className="w-5 h-5 text-brand-blue" />
            <h2 className="text-lg font-semibold text-gray-800">View settings</h2>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600" title="Close">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-4 space-y-5 overflow-y-auto">
          <section className="space-y-2">
            <h3 className="text-sm font-semibold text-gray-800">When someone opens this view’s link</h3>
            {choice('workspace', 'Inside Command Center', 'With the sidebar, the widget library and the studios, as views have always opened.')}
            {choice('standalone', 'On its own', 'Just this view, under its own title and logo. Its editors still build it here.')}
          </section>

          <section className="space-y-3">
            <div>
              <h3 className="text-sm font-semibold text-gray-800">When it opens on its own</h3>
              <p className="text-xs text-gray-500">Inside Command Center the view keeps its name and the usual assistant.</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Title</label>
              <input
                type="text"
                value={title}
                maxLength={MAX_NAME_LENGTH}
                onChange={e => setTitle(e.target.value)}
                placeholder={app.name}
                className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-brand-blue/40"
              />
            </div>
            <ImageField label="Logo" hint="Shown beside the title." value={logo} onChange={setLogo} />
            <ImageField label="Browser tab icon" hint="Shown on the browser tab." value={favicon} onChange={setFavicon} />
            <label className="flex items-center gap-2 text-sm text-gray-700">
              <input type="checkbox" checked={assistant === 'on'} onChange={e => setAssistant(e.target.checked ? 'on' : 'off')} />
              Offer the assistant
            </label>
            {assistant === 'on' && (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Assistant name</label>
                <input
                  type="text"
                  value={assistantName}
                  maxLength={MAX_NAME_LENGTH}
                  onChange={e => setAssistantName(e.target.value)}
                  placeholder="EDH Agent"
                  className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-brand-blue/40"
                />
              </div>
            )}
          </section>

          {refusal && <p className="text-sm text-red-600">{refusal}</p>}
        </div>

        <div className="flex justify-end gap-2 p-4 border-t border-gray-200">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-md">
            Cancel
          </button>
          <button
            onClick={save}
            disabled={saving || invalid}
            className="px-4 py-2 text-sm bg-brand-blue text-white rounded-md hover:bg-brand-navy disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
};
