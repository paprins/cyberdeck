/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/templates/**/*.html"],
  corePlugins: {
    animation: false,
    transitionProperty: false,
    transitionDuration: false,
    transitionTimingFunction: false,
    transitionDelay: false,
  },
  theme: {
    extend: {
      colors: {
        bg:       'oklch(9% 0.005 90)',
        surface:  'oklch(15% 0.007 90)',
        elevated: 'oklch(20% 0.010 90)',
        border:   'oklch(30% 0.008 90)',
        amber: {
          DEFAULT: 'oklch(80% 0.15 75)',
          mid:     'oklch(68% 0.10 75)',
          ghost:   'oklch(35% 0.06 75)',
        },
        text: {
          hi:  'oklch(92% 0.006 90)',
          mid: 'oklch(66% 0.006 90)',
          lo:  'oklch(48% 0.005 90)',
        },
        tile: {
          medical:      'oklch(68% 0.25 25)',
          maps:         'oklch(72% 0.22 145)',
          survival:     'oklch(76% 0.18 58)',
          food:         'oklch(74% 0.19 118)',
          encyclopedia: 'oklch(70% 0.18 232)',
          packages:     'oklch(65% 0.14 195)',
          internet:     'oklch(72% 0.20 260)',
        },
      },
      fontFamily: {
        display: ['B612', 'monospace'],
        body:    ['Atkinson Hyperlegible', 'sans-serif'],
      },
      borderRadius: {
        tile: '16px',
      },
    },
  },
}
