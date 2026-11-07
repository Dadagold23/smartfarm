// Pure client-side mirror of the backend `satisfies()` rule for UI gating:
// a held `resource.action.all` permission implies `resource.action.own`.
// This is a UI hint only — the API independently enforces every operation.

export function satisfiesPermission(perms, required) {
  if (!Array.isArray(perms)) return false;
  if (perms.includes(required)) return true;
  if (required.endsWith(".own")) {
    return perms.includes(required.slice(0, -".own".length) + ".all");
  }
  return false;
}
