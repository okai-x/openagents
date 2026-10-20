import { beforeEach, describe, expect, it, vi } from "vitest"

const posthog = vi.hoisted(() => ({ init: vi.fn(), capture: vi.fn(), group: vi.fn() }))
vi.mock("posthog-js", () => ({ default: posthog }))

async function loadWithSetting(value: unknown) {
  vi.resetModules()
  ;(window as unknown as { api: unknown }).api = { getSetting: vi.fn().mockResolvedValue(value) }
  const analytics = await import("./analytics")
  analytics.initAnalytics()
  await new Promise((resolve) => setTimeout(resolve, 0))
  return analytics
}

describe("analytics", () => {
  beforeEach(() => {
    posthog.init.mockClear()
    posthog.capture.mockClear()
    posthog.group.mockClear()
  })

  it("sends nothing unless the setting is explicitly true", async () => {
    for (const value of [undefined, null, false, "true"]) {
      const analytics = await loadWithSetting(value)
      analytics.capture("event")
      analytics.group("workspace", "slug")
    }
    expect(posthog.init).not.toHaveBeenCalled()
    expect(posthog.capture).not.toHaveBeenCalled()
    expect(posthog.group).not.toHaveBeenCalled()
  })

  it("initializes and forwards events once enabled", async () => {
    const analytics = await loadWithSetting(true)
    analytics.capture("event")
    expect(posthog.init).toHaveBeenCalledOnce()
    expect(posthog.capture).toHaveBeenCalledWith("event", undefined)
  })
})
