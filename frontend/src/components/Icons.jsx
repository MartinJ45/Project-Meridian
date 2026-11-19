// Simple line icons (24px grid, stroke = currentColor) so they follow the theme.
const base = {
  width: 22, height: 22, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor',
  strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true,
}

export const PlusIcon = (p) => (
  <svg {...base} {...p}><path d="M12 5v14M5 12h14" /></svg>
)

export const ChatIcon = (p) => (
  <svg {...base} {...p}>
    <path d="M4 5.5A1.5 1.5 0 0 1 5.5 4h13A1.5 1.5 0 0 1 20 5.5v9a1.5 1.5 0 0 1-1.5 1.5H9l-4.2 3.4a.5.5 0 0 1-.8-.4V5.5Z" />
  </svg>
)

export const DocumentIcon = (p) => (
  <svg {...base} {...p}>
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z" />
    <path d="M14 3v5h5M9 13h6M9 17h6" />
  </svg>
)

export const ReviewIcon = (p) => (
  <svg {...base} {...p}>
    <path d="M9 4h6v3H9z" />
    <path d="M15 5.5h2A1.5 1.5 0 0 1 18.5 7v12a1.5 1.5 0 0 1-1.5 1.5H7A1.5 1.5 0 0 1 5.5 19V7A1.5 1.5 0 0 1 7 5.5h2" />
    <path d="m9 14 2 2 4-4" />
  </svg>
)

export const UserIcon = (p) => (
  <svg {...base} width={26} height={26} {...p}>
    <circle cx="12" cy="12" r="9.5" />
    <circle cx="12" cy="10" r="3.2" />
    <path d="M6.2 18.4a7 7 0 0 1 11.6 0" />
  </svg>
)

export const SendIcon = (p) => (
  <svg {...base} {...p}>
    <path d="M4.5 12 20 4.5l-4.2 15-4.3-6.2L4.5 12Z" />
    <path d="M11.5 13.3 20 4.5" />
  </svg>
)



export const CopyIcon = (p) => (
  <svg {...base} width={18} height={18} {...p}>
    <rect x="8" y="8" width="12" height="12" rx="2" />
    <path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" />
  </svg>
)
