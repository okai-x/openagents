import { describe, expect, it } from "vitest"
import { readLocalWorkspace } from "./local-workspace"

describe("local workspace entry", () => {
  const token = "local-workspace-token-for-test"
  it("requires a token tied to the explicitly configured loopback service", () => {
    const endpoint = "http://127.0.0.1:18765"
    expect(readLocalWorkspace({ endpoint, slug: "my-workspace", token }, endpoint)?.slug).toBe("my-workspace")
    expect(readLocalWorkspace({ endpoint, slug: "my-workspace", token }, "http://127.0.0.1:9999")).toBeNull()
    expect(readLocalWorkspace({ endpoint, slug: "my-workspace" }, endpoint)).toBeNull()
  })
  it("rejects remote, misleading, credential-bearing and navigable endpoints", () => {
    for (const endpoint of ["https://workspace-endpoint.openagents.org", "http://127.0.0.1.example.com", "http://127.0.0.1@evil.test", "file:///tmp", "http://localhost/?token=x"]) {
      expect(readLocalWorkspace({ endpoint, slug: "local", token }, endpoint)).toBeNull()
    }
    const endpoint = "http://localhost:18765"
    expect(readLocalWorkspace({ endpoint, slug: "../other", token }, endpoint)).toBeNull()
  })
})
