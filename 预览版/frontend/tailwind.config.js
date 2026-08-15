/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,ts}'],
  theme: {
    extend: {
      colors: {
        primary: '#007AFF',
        bg: '#F5F5F7',
        card: '#FFFFFF',
        border: '#E5E5EA',
        borderStrong: '#C7C7CC',
        textPrimary: '#1D1D1F',
        textSecondary: '#6E6E73',
        textTertiary: '#AEAEB2',
        success: '#34C759',
        warning: '#FF9500',
        error: '#FF3B30',
        question: '#3B82F6',
        analysis: '#10B981',
      },
      fontSize: {
        h1: ['28px', { fontWeight: 600 }],
        h2: ['20px', { fontWeight: 600 }],
        h3: ['16px', { fontWeight: 600 }],
        body: ['14px', { lineHeight: '1.6' }],
        caption: ['12px', { lineHeight: '1.4' }],
      },
      spacing: {
        xs: '4px', sm: '8px', md: '12px', lg: '16px', xl: '20px', '2xl': '32px',
      },
      borderRadius: {
        btn: '8px', card: '12px', tag: '6px',
      },
    },
  },
  plugins: [],
}
