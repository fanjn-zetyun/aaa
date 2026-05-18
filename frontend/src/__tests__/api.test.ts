import { describe, it, expect } from "vitest";
import { getToken, setToken, clearToken } from "../lib/api";

describe("api token management", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("getToken returns null when no token", () => {
    expect(getToken()).toBeNull();
  });

  it("setToken stores and getToken retrieves", () => {
    setToken("test-token-123");
    expect(getToken()).toBe("test-token-123");
  });

  it("clearToken removes the token", () => {
    setToken("test-token-123");
    clearToken();
    expect(getToken()).toBeNull();
  });
});
