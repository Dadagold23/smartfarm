import { test } from "node:test";
import assert from "node:assert/strict";
import { satisfiesPermission } from "../lib/permissions.js";

test("exact permission match", () => {
  assert.equal(satisfiesPermission(["farm.create"], "farm.create"), true);
  assert.equal(satisfiesPermission(["farm.create"], "farm.delete"), false);
});

test("all-variant satisfies own-variant", () => {
  const perms = ["farm.read.all"];
  assert.equal(satisfiesPermission(perms, "farm.read.own"), true);
});

test("own-variant does not satisfy all-variant", () => {
  assert.equal(satisfiesPermission(["farm.read.own"], "farm.read.all"), false);
});

test("unrelated permissions never leak", () => {
  assert.equal(satisfiesPermission(["zone.read"], "farm.read.own"), false);
});

test("defensive against missing/invalid permission list", () => {
  assert.equal(satisfiesPermission(undefined, "farm.read.own"), false);
  assert.equal(satisfiesPermission([], "farm.read.own"), false);
});
