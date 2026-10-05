import React, { useRef, useState } from 'react';
import { X, Settings2, Upload, Trash2, Plus } from 'lucide-react';
import clsx from 'clsx';
import { useDashboardStore } from '../store/dashboardStore';
import {
  colourProblem, filtersProblem, imageProblem, MAX_FILTERS, MAX_NAME_LENGTH, navStyle,
  type App, type AppFilter, type AppNav, type AppSpec,
} from '../store/appSpec';

interface FilterDraft {
  label: string;
  key: string;
  /** The key follows the label until someone types one. */
  autoKey: boolean;
  options: string;
  default: string;
}

const keyFromLabel = (label: string): string => {
  const key = label.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  return (/^[0-9]/.test(key) ? `_${key}` : key).slice(0, 64);
};

const draftOf = (filter: AppFilter): FilterDraft => ({
  label: filter.label,
  key: filter.key,
  autoKey: false,
  options: filter.options.join('\n'),
  default: filter.default || '',
});

const optionsOf = (text: string): string[] => text.split('\n').map(o => o.trim()).filter(Boolean);

const filterOf = (draft: FilterDraft): AppFilter => {
  const options = optionsOf(draft.options);
  return {
    key: draft.key.trim(),
    label: draft.label.trim() || draft.key.trim(),
    options,
    default: options.includes(draft.default) ? draft.default : null,
  };
};

const ColourField: React.FC<{
  label: string;
  fallback: string;
  value: string;
  onChange: (value: string) => void;
}> = ({ label, fallback, value, onChange }) => {
  const problem = colourProblem(value);
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">{label}</label>
      <div className="flex items-center gap-2">
        <input
          type="color"
          value={value && !problem ? value : fallback}
          onChange={e => onChange(e.target.value)}
          className="w-8 h-8 p-0.5 border border-gray-300 rounded cursor-pointer shrink-0"
          aria-label={`${label} picker`}
        />
        <input
          type="text"
          value={value}
          onChange={e => onChange(e.target.value.trim())}
          placeholder={fallback}
          maxLength={7}
          className="w-28 px-3 py-1.5 text-sm font-mono border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-brand-blue/40"
        />
        {value && (
          <button
            type="button"
            onClick={() => onChange('')}
            className="text-xs text-gray-500 hover:text-brand-blue"
          >
            Use Command Center’s
          </button>
        )}
      </div>
      {problem && <p className="text-xs mt-1 text-red-600">{problem}</p>}
    </div>
  );
};

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
  const [nav, setNav] = useState<AppNav['style']>(navStyle(app));
  const [primary, setPrimary] = useState(app.spec.theme?.primary || '');
  const [dark, setDark] = useState(app.spec.theme?.dark || '');
  const [filters, setFilters] = useState<FilterDraft[]>(() => (app.spec.filters || []).map(draftOf));
  const [saving, setSaving] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);

  const filterProblem = filtersProblem(filters.map(filterOf));
  const invalid = Boolean(imageProblem(logo) || imageProblem(favicon) || colourProblem(primary) || colourProblem(dark) || filterProblem);

  const changeFilter = (index: number, change: Partial<FilterDraft>) =>
    setFilters(prev => prev.map((f, i) => {
      if (i !== index) return f;
      const next = { ...f, ...change };
      if ('key' in change) next.autoKey = false;
      else if ('label' in change && f.autoKey) next.key = keyFromLabel(next.label);
      return next;
    }));

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
      nav: nav === 'sidebar' ? { style: 'sidebar' } : null,
      theme: primary || dark ? { primary: primary || null, dark: dark || null } : null,
      filters: filters.map(filterOf),
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

          <section className="space-y-2">
            <div>
              <h3 className="text-sm font-semibold text-gray-800">Tabs</h3>
              <p className="text-xs text-gray-500">Where the tabs sit, wherever the view opens. A view with one tab shows none.</p>
            </div>
            <div className="flex gap-2">
              {([['tabs', 'Across the top'], ['sidebar', 'Down the side']] as const).map(([value, label]) => (
                <label
                  key={value}
                  className={clsx(
                    'flex-1 flex items-center gap-2 p-2 border rounded-md cursor-pointer text-sm text-gray-800 transition-colors',
                    nav === value ? 'border-brand-blue bg-brand-blue/5' : 'border-gray-200 hover:border-gray-300'
                  )}
                >
                  <input type="radio" name="nav" checked={nav === value} onChange={() => setNav(value)} />
                  {label}
                </label>
              ))}
            </div>
          </section>

          <section className="space-y-3">
            <div>
              <h3 className="text-sm font-semibold text-gray-800">Filters</h3>
              <p className="text-xs text-gray-500">
                Dropdowns above the canvas, wherever the view opens. Each choice sets the variable named here,
                which widgets that follow that variable then use, on every tab.
              </p>
            </div>
            {filters.map((filter, index) => (
              <div key={index} className="p-3 border border-gray-200 rounded-md space-y-2">
                <div className="flex items-start gap-2">
                  <div className="flex-1 min-w-0">
                    <label className="block text-xs font-medium text-gray-600 mb-0.5">Label</label>
                    <input
                      type="text"
                      value={filter.label}
                      maxLength={MAX_NAME_LENGTH}
                      onChange={e => changeFilter(index, { label: e.target.value })}
                      placeholder="Region"
                      className="w-full px-2 py-1 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-brand-blue/40"
                    />
                  </div>
                  <div className="flex-1 min-w-0">
                    <label className="block text-xs font-medium text-gray-600 mb-0.5">Variable</label>
                    <input
                      type="text"
                      value={filter.key}
                      maxLength={64}
                      onChange={e => changeFilter(index, { key: e.target.value.trim() })}
                      placeholder="region"
                      className="w-full px-2 py-1 text-sm font-mono border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-brand-blue/40"
                    />
                  </div>
                  <button
                    type="button"
                    onClick={() => setFilters(prev => prev.filter((_, i) => i !== index))}
                    className="mt-5 p-1 text-gray-400 hover:text-red-600 hover:bg-gray-100 rounded-md"
                    title="Remove this filter"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-0.5">Options, one per line</label>
                  <textarea
                    value={filter.options}
                    rows={3}
                    onChange={e => changeFilter(index, { options: e.target.value })}
                    placeholder={'EMEA\nAPAC\nAmericas'}
                    className="w-full px-2 py-1 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-brand-blue/40"
                  />
                </div>
                <div className="flex items-center gap-2">
                  <label className="text-xs font-medium text-gray-600">Starts on</label>
                  <select
                    value={optionsOf(filter.options).includes(filter.default) ? filter.default : ''}
                    onChange={e => changeFilter(index, { default: e.target.value })}
                    className="px-2 py-1 text-sm border border-gray-300 rounded-md bg-white"
                  >
                    <option value="">All</option>
                    {optionsOf(filter.options).map(option => <option key={option} value={option}>{option}</option>)}
                  </select>
                </div>
              </div>
            ))}
            {filterProblem && <p className="text-xs text-red-600">{filterProblem}</p>}
            {filters.length < MAX_FILTERS && (
              <button
                type="button"
                onClick={() => setFilters(prev => [...prev, { label: '', key: '', autoKey: true, options: '', default: '' }])}
                className="flex items-center gap-1 text-sm text-brand-blue hover:text-brand-navy"
              >
                <Plus className="w-4 h-4" /> Add a filter
              </button>
            )}
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
            <div className="grid grid-cols-2 gap-3">
              <ColourField label="Accent colour" fallback="#007bff" value={primary} onChange={setPrimary} />
              <ColourField label="Dark colour" fallback="#001e3c" value={dark} onChange={setDark} />
            </div>
            <p className="text-xs text-gray-500 -mt-1">
              Replace Command Center’s blue and navy, in widgets too. White text sits on both, so each must be dark enough to read it on.
            </p>
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
