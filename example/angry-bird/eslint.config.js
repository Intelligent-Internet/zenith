import js from '@eslint/js';

export default [
  {
    ignores: [
      'dist/**',
      'node_modules/**',
      'coverage/**',
      '.mission/**',
      '.omx/**',
      '.agents/**',
      '.codex/**',
      '.claude/**',
    ]
  },
  js.configs.recommended,
  {
    files: ['**/*.js'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: {
        console: 'readonly',
        document: 'readonly',
        window: 'readonly'
      }
    }
  }
];
