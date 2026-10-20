/** Explicit token entry for a self-hosted workspace on this computer. */
export interface LocalWorkspace {
  endpoint: string
  slug: string
  token: string
}

export function readLocalWorkspace(value: unknown, endpoint: unknown): LocalWorkspace | null {
  if (!value || typeof value !== "object" || typeof endpoint !== "string") return null
  const entry = value as Partial<LocalWorkspace>
  try {
    const url = new URL(endpoint)
    if (!["http:", "https:"].includes(url.protocol) ||
      !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) ||
      url.username || url.password || url.search || url.hash) return null
    if (entry.endpoint?.replace(/\/$/, "") !== endpoint.replace(/\/$/, "")) return null
    if (typeof entry.slug !== "string" || !/^[a-zA-Z0-9_-]+$/.test(entry.slug)) return null
    if (typeof entry.token !== "string" || entry.token.length < 16) return null
    return { endpoint, slug: entry.slug, token: entry.token }
  } catch { return null }
}
