import posthog from "posthog-js"

const POSTHOG_KEY = "phc_t27xjrx9U42B54arcMwpiBgQxEFikBzXGnvzVtFEGtpf"
let enabled = false

export function initAnalytics(): void {
  // Opt-in: nothing is initialized, and no request leaves the app, unless the
  // analyticsEnabled setting is explicitly true.
  void window.api.getSetting("analyticsEnabled").then((value) => {
    if (value !== true) return
    enabled = true
    posthog.init(POSTHOG_KEY, {
      api_host: "https://d.openagents.org",
      person_profiles: "identified_only",
      capture_pageview: false,
      autocapture: true,
      persistence: "localStorage",
    })
    posthog.capture("app_opened")
  }).catch(() => { /* No telemetry when settings cannot be read. */ })
}

export function capture(event: string, properties?: Record<string, unknown>): void {
  if (!enabled) return
  posthog.capture(event, properties)
}

// Tie subsequent events to a workspace. The workspace slug is the join key that connects
// this install's onboarding to the website + workspace funnel stages for the same workspace.
export function group(groupType: string, groupKey: string, properties?: Record<string, unknown>): void {
  if (!enabled) return
  posthog.group(groupType, groupKey, properties)
}
