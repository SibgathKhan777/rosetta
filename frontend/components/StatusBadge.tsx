const COLOR_VAR: Record<string, string> = {
  queued: "var(--ink-faint)",
  downloading: "var(--gold)",
  processing: "var(--gold)",
  stitching: "var(--gold)",
  done: "var(--patina)",
  failed: "var(--danger)",
};

export default function StatusBadge({ status }: { status: string }) {
  const color = COLOR_VAR[status] || "var(--ink-faint)";
  return (
    <span
      className="pill"
      style={{
        color,
        borderColor: color,
        textTransform: "capitalize",
      }}
    >
      {status}
    </span>
  );
}
