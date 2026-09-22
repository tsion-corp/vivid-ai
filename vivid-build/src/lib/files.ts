export type FileTreeNode =
  | { kind: "dir"; name: string; path: string; children: FileTreeNode[] }
  | { kind: "file"; name: string; path: string };

/**
 * Builds the directory tree from file paths. Directories are implied by the
 * paths rather than stored, so there is no way for the tree and the files to
 * disagree.
 */
export function buildTree(paths: string[]): FileTreeNode[] {
  const root: FileTreeNode[] = [];
  const dirs = new Map<string, FileTreeNode & { kind: "dir" }>();

  const ensureDir = (path: string): FileTreeNode[] => {
    if (!path) return root;
    const existing = dirs.get(path);
    if (existing) return existing.children;

    const slash = path.lastIndexOf("/");
    const parent = ensureDir(slash === -1 ? "" : path.slice(0, slash));
    const node: FileTreeNode & { kind: "dir" } = {
      kind: "dir",
      name: slash === -1 ? path : path.slice(slash + 1),
      path,
      children: [],
    };
    dirs.set(path, node);
    parent.push(node);
    return node.children;
  };

  for (const path of [...paths].sort()) {
    const slash = path.lastIndexOf("/");
    const siblings = ensureDir(slash === -1 ? "" : path.slice(0, slash));
    siblings.push({ kind: "file", name: slash === -1 ? path : path.slice(slash + 1), path });
  }

  return sortNodes(root);
}

/** Directories first, then files, each alphabetical. */
function sortNodes(nodes: FileTreeNode[]): FileTreeNode[] {
  nodes.sort((a, b) => {
    if (a.kind !== b.kind) return a.kind === "dir" ? -1 : 1;
    return a.name.localeCompare(b.name);
  });
  for (const node of nodes) {
    if (node.kind === "dir") sortNodes(node.children);
  }
  return nodes;
}

export function countLines(content: string): number {
  return content.length === 0 ? 0 : content.split("\n").length;
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
