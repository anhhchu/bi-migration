/** Catalog Explorer page for a Unity Catalog object such as a Metric View, or null if it cannot be built. */
export function catalogExplorerUrl(workspaceUrl: string | null | undefined, fullName: string | null | undefined) {
  if (!workspaceUrl || !fullName) return null;
  const parts = fullName
    .split('.')
    .map((part) => part.trim().replace(/^`|`$/g, ''))
    .filter(Boolean);
  if (parts.length !== 3) return null;
  return `${workspaceUrl.replace(/\/$/, '')}/explore/data/${parts.map(encodeURIComponent).join('/')}`;
}
