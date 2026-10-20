import { describe, expect, it } from 'vitest';
import { isLoopbackDesktopApi } from './self-hosted-desktop';

describe('isLoopbackDesktopApi', () => {
  it('recognises the desktop bundle pointed at this computer', () => {
    for (const api of ['http://127.0.0.1:18800', 'http://localhost:8000', 'http://[::1]:18800']) {
      expect(isLoopbackDesktopApi('workspace', api)).toBe(true);
    }
  });

  it('keeps the hosted service and every other host first-party as before', () => {
    expect(isLoopbackDesktopApi('workspace', 'https://workspace-endpoint.openagents.org')).toBe(false);
    expect(isLoopbackDesktopApi('workspace', 'http://127.0.0.1.example.com')).toBe(false);
    expect(isLoopbackDesktopApi('workspace.openagents.org', 'http://127.0.0.1:18800')).toBe(false);
    expect(isLoopbackDesktopApi('workspace', undefined)).toBe(false);
    expect(isLoopbackDesktopApi('workspace', 'not a url')).toBe(false);
  });
});
