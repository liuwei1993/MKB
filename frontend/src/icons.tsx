import type { SVGProps } from 'react'

type IconProps = SVGProps<SVGSVGElement>

function svg(props: IconProps) {
  return {
    width: 18,
    height: 18,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.7,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true as const,
    ...props,
  }
}

export function IconPlus(props: IconProps) {
  return (
    <svg {...svg(props)}>
      <circle cx="12" cy="12" r="8" />
      <path d="M12 8.5v7M8.5 12h7" />
    </svg>
  )
}

export function IconChevron(props: IconProps) {
  return (
    <svg {...svg(props)}>
      <path d="m9 6 6 6-6 6" />
    </svg>
  )
}

export function IconCheck(props: IconProps) {
  return (
    <svg {...svg({ strokeWidth: 2.4, ...props })}>
      <path d="m6.5 12.2 3.2 3.3 7.8-8" />
    </svg>
  )
}

export function IconClose(props: IconProps) {
  return (
    <svg {...svg(props)}>
      <path d="M7 7l10 10M17 7 7 17" />
    </svg>
  )
}

export function IconSend(props: IconProps) {
  return (
    <svg {...svg({ fill: 'currentColor', stroke: 'none', ...props })}>
      <path d="M5.2 11.2 18.6 5.4c.7-.3 1.4.4 1.1 1.1l-5.8 13.4c-.3.7-1.3.7-1.6 0l-2.2-5.1-5.1-2.2c-.7-.3-.7-1.3 0-1.6z" />
    </svg>
  )
}

export function IconStop(props: IconProps) {
  return (
    <svg {...svg({ fill: 'currentColor', stroke: 'none', ...props })}>
      <rect x="7" y="7" width="10" height="10" rx="2" />
    </svg>
  )
}

export function IconMic(props: IconProps) {
  return (
    <svg {...svg(props)}>
      <rect x="9" y="3.5" width="6" height="10" rx="3" />
      <path d="M7 11a5 5 0 0 0 10 0M12 16v4M9 20h6" />
    </svg>
  )
}

export function IconRefresh(props: IconProps) {
  return (
    <svg {...svg(props)}>
      <path d="M19 12a7 7 0 1 1-2-4.9" />
      <path d="M19 5v4h-4" />
    </svg>
  )
}

export function IconDownload(props: IconProps) {
  return (
    <svg {...svg(props)}>
      <path d="M12 5v10M8 11l4 4 4-4" />
      <path d="M6 19h12" />
    </svg>
  )
}

export function IconCopy(props: IconProps) {
  return (
    <svg {...svg(props)}>
      <rect x="8" y="8" width="10" height="11" rx="1.6" />
      <path d="M16 8V6.2A1.2 1.2 0 0 0 14.8 5H6.2A1.2 1.2 0 0 0 5 6.2v8.6A1.2 1.2 0 0 0 6.2 16H8" />
    </svg>
  )
}

export function IconSearch(props: IconProps) {
  return (
    <svg {...svg(props)}>
      <circle cx="11" cy="11" r="6" />
      <path d="m16 16 3.5 3.5" />
    </svg>
  )
}

export function IconSpark(props: IconProps) {
  return (
    <svg {...svg({ fill: 'currentColor', stroke: 'none', ...props })}>
      <path d="M12 2.2c.45 3.1 1.5 4.7 4.7 5.8-3.2 1.1-4.25 2.7-4.7 5.8-.45-3.1-1.5-4.7-4.7-5.8 3.2-1.1 4.25-2.7 4.7-5.8z" />
      <path d="M18.1 13.4c.2 1.2.55 1.85 1.7 2.2-1.15.35-1.5 1-1.7 2.2-.2-1.2-.55-1.85-1.7-2.2 1.15-.35 1.5-1 1.7-2.2z" />
    </svg>
  )
}

export function IconDown(props: IconProps) {
  return (
    <svg {...svg(props)}>
      <path d="M6 10l6 6 6-6" />
    </svg>
  )
}

export function IconChat(props: IconProps) {
  return (
    <svg {...svg(props)}>
      <path d="M6 16.5 4.5 20 9 18h7.2A2.8 2.8 0 0 0 19 15.2V7.8A2.8 2.8 0 0 0 16.2 5H7.8A2.8 2.8 0 0 0 5 7.8v6.2A2.5 2.5 0 0 0 6 16.5z" />
    </svg>
  )
}
