/**
 * Plain-English labels for the agent's tools, transcribed from §3 of the
 * integration guide.
 *
 * The point is that a non-technical user can read the activity list: "Writing
 * src/pages/Shop.tsx" rather than a tool name and a JSON blob.
 */
type Input = Record<string, unknown> | undefined;

const str = (input: Input, field: string) => {
  const value = input?.[field];
  return typeof value === "string" ? value : null;
};

const LABELS: Record<string, (input: Input) => string> = {
  read_file: (i) => `Reading ${str(i, "path") ?? "a file"}`,
  write_file: (i) => `Writing ${str(i, "path") ?? "a file"}`,
  edit_file: (i) => `Editing ${str(i, "path") ?? "a file"}`,
  list_files: () => "Looking at the files",
  run_command: (i) => `Running: ${str(i, "command") ?? "a command"}`,
  get_dev_server_logs: () => "Checking the dev server",
  generate_image: (i) => `Making a picture: ${str(i, "name") ?? str(i, "kind") ?? "image"}`,
  apply_migration: (i) => `Updating the database: ${str(i, "name") ?? "migration"}`,
  deploy_edge_function: (i) => `Deploying ${str(i, "name") ?? "a function"}`,
  // The value is never in the stream, and must never be rendered even if it were.
  set_secret: (i) => `Storing a secret: ${str(i, "key") ?? "secret"}`,
  ask_user: () => "Asking a few questions",
  write_spec: () => "Writing the spec",
};

/** Falls back to the tool's own name, de-underscored, for anything new. */
export function toolLabel(toolName: string, input: Input): string {
  const label = LABELS[toolName];
  if (label) return label(input);
  return toolName.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

/** Tools that get their own card rather than an activity row. */
export const SPECIAL_TOOLS = new Set(["ask_user", "write_spec"]);
