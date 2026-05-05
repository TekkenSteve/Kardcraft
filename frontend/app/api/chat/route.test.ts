import { describe, expect, it } from "vitest";
import { __test__ } from "./route";

describe("chat route stream normalization", () => {
  it("returns only tail when completed contains previous deltas", () => {
    expect(__test__.computeCompletedTail("Hello ", "Hello world")).toBe("world");
  });

  it("returns completed text when delta prefix is absent", () => {
    expect(__test__.computeCompletedTail("Hi", "Hello world")).toBe("Hello world");
  });

  it("extracts nested delta/completed payload", () => {
    expect(__test__.toTextDelta({ payload: { delta: "abc" } })).toBe("abc");
    expect(__test__.toCompletedText({ payload: { response: "done" } })).toBe("done");
  });

  it("extracts message text fallback for workflow/legacy completion payload", () => {
    expect(__test__.toMessageText({ payload: { message: "final answer" } })).toBe("final answer");
  });

});
