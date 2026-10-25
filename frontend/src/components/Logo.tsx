export function Logo({ size = 28, animated = true }: { size?: number; animated?: boolean }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      aria-hidden="true"
      className={animated ? "logo-mark" : undefined}
    >
      <defs>
        <linearGradient id="ff-logo-g" x1="4" y1="4" x2="44" y2="44" gradientUnits="userSpaceOnUse">
          <stop stopColor="#22d3ee" />
          <stop offset="0.5" stopColor="#6366f1" />
          <stop offset="1" stopColor="#c084fc" />
        </linearGradient>
      </defs>
      <rect x="2" y="2" width="44" height="44" rx="13" fill="url(#ff-logo-g)" />
      <path
        d="M14 15h12.5a5.5 5.5 0 0 1 0 11H21m0 0h8a5.5 5.5 0 0 1 0 11H14"
        stroke="#fff"
        strokeWidth="3.2"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.95"
      />
      <circle cx="14" cy="15" r="3.2" fill="#fff" />
      <circle cx="14" cy="37" r="3.2" fill="#fff" />
    </svg>
  );
}
