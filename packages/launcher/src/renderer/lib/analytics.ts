import posthog from "posthog-js"

const POSTHOG_KEY = "phc_t27xjrx9U42B54arcMwpiBgQxEFikBzXGnvzVtFEGtpf"
let enabled = false

export function initAnalytics(): void {
  // Resolve consent before initializing: local deployments can opt out without
  // making even the initial analytics request.
  void window.api.getSetting("analyticsEnabled").then((value) => {
    if (value === false) return
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
