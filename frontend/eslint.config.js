import globals from 'globals';

// Catches what the switch from classic scripts to ES modules can break:
// undeclared globals (missing imports) and sloppy-mode assignments.
export default [
  {
    files: ['src/**/*.js'],
    ignores: ['src/vendor/**'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: { ...globals.browser, L: 'readonly' },
    },
    rules: {
      'no-undef': 'error',
      'no-unused-vars': ['warn', { args: 'none', caughtErrors: 'none' }],
    },
  },
];
