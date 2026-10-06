import React, { useRef, useState } from 'react';
import { Upload, Trash2 } from 'lucide-react';
import clsx from 'clsx';
import { colourProblem, imageProblem } from '../store/appSpec';

const HEX = /^#[0-9a-fA-F]{6}$/;

/**
 * A colour, picked or typed. `onWhite` colours carry white text, so they are
 * held to the same contrast as the server holds them; a background is not.
 */
export const ColourField: React.FC<{
  label: string;
  fallback: string;
  value: string;
  onChange: (value: string) => void;
  clearLabel?: string;
  onWhite?: boolean;
}> = ({ label, fallback, value, onChange, clearLabel = 'Use default', onWhite = true }) => {
  const problem = onWhite ? colourProblem(value) : (value && !HEX.test(value) ? 'Use a colour written as #rrggbb.' : null);
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 mb-1">
        <label className="text-sm font-medium text-gray-700">{label}</label>
        {value && clearLabel && (
          <button
            type="button"
            onClick={() => onChange('')}
            className="text-xs text-gray-500 hover:text-brand-blue whitespace-nowrap"
          >
            {clearLabel}
          </button>
        )}
      </div>
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
          aria-label={label}
          className="w-28 px-3 py-1.5 text-sm font-mono border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-brand-blue/40"
        />
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

export const ImageField: React.FC<{
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
          aria-label={label}
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
