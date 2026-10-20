/**
 * Whether this is the desktop bundle (served at openagents://workspace) pointed
 * by the launcher at a self-hosted Workspace on this computer.
 *
 * That deployment is not OpenAgents' own: its workspaces open with their
 * workspace token, exactly as the web app does on a third-party host, instead
 * of waiting for an OpenAgents sign-in that a token-only local install never
 * has. Only loopback API hosts qualify, matching the launcher's own rule.
 */
export function isLoopbackDesktopApi(hostname: string, apiUrl: unknown): boolean {
  if (hostname !== 'workspace' || typeof apiUrl !== 'string') return false;
  try {
    return ['127.0.0.1', 'localhost', '[::1]'].includes(new URL(apiUrl).hostname);
  } catch {
    return false;
  }
}
