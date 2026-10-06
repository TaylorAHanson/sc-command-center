/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  safelist: [
    {
      pattern: /^(bg|text|border)-(red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|slate|gray|zinc|neutral|stone)-(50|100|200|300|400|500|600|700|800|900|950)$/,
    },
    {
      // Widgets are told every hover state must stay readable, so they write them.
      pattern: /^(bg|text)-(red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|slate|gray|zinc|neutral|stone)-(50|100|200|300|400|500|600|700|800|900|950)$/,
      variants: ['hover'],
    },
    {
      pattern: /^(bg|text|border)-(white|black|transparent)$/,
    },
    // Widget code is compiled in the browser after this build, so Tailwind never
    // sees its classes: only what src/ uses and what is listed here exist. Pages
    // need display type, generous spacing and responsive columns that the app's
    // own screens don't use. Gradient stops are left to inline styles, since the
    // colour × shade × stop set would double the stylesheet.
    { pattern: /^text-(xs|sm|base|lg|xl|2xl|3xl|4xl|5xl|6xl|7xl)$/, variants: ['sm', 'md', 'lg'] },
    { pattern: /^font-(light|normal|medium|semibold|bold|extrabold|black)$/ },
    { pattern: /^tracking-(tighter|tight|normal|wide|wider|widest)$/ },
    { pattern: /^leading-(none|tight|snug|normal|relaxed|loose)$/ },
    { pattern: /^(p|px|py|pt|pb|gap|gap-x|gap-y|space-y|mt|mb|mx|my)-(0|1|2|3|4|5|6|8|10|12|16|20|24)$/, variants: ['md', 'lg'] },
    { pattern: /^grid-cols-(1|2|3|4|5|6|12)$/, variants: ['sm', 'md', 'lg', 'xl'] },
    { pattern: /^col-span-(1|2|3|4|6|full)$/, variants: ['md', 'lg'] },
    { pattern: /^row-span-(1|2|3|full)$/, variants: ['md', 'lg'] },
    { pattern: /^(flex-row|flex-col|items-start|items-center|justify-between|hidden|block|flex|grid|text-left|text-center)$/, variants: ['md', 'lg'] },
    { pattern: /^rounded(-(none|sm|md|lg|xl|2xl|3xl|full))?$/ },
    { pattern: /^shadow(-(sm|md|lg|xl|2xl|none))?$/ },
    { pattern: /^max-w-(sm|md|lg|xl|2xl|3xl|4xl|5xl|6xl|7xl|prose|full)$/ },
    { pattern: /^(bg|text|border)-(white|black)\/(5|10|20|30|40|50|60|70|80|90)$/ },
    { pattern: /^backdrop-blur(-(sm|md|lg))?$/ },
    { pattern: /^-?translate-y-(0|0\.5|1)$/, variants: ['hover', 'group-hover'] },
    { pattern: /^(min-h-(full|screen)|aspect-(square|video)|ring-1|ring-2|duration-(150|200|300))$/ },
  ],
  theme: {
    extend: {
      colors: {
        // Channels, not hex, so a view's theme can swap them at runtime and
        // opacity modifiers (`bg-brand-blue/5`) still work. Defaults: index.css.
        brand: {
          navy: 'rgb(var(--brand-navy) / <alpha-value>)',
          blue: 'rgb(var(--brand-blue) / <alpha-value>)',
          light: 'rgb(var(--brand-light) / <alpha-value>)',
        }
      }
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
  ],
}

