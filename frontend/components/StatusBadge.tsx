const COLORS: Record<string, string> = {
  queued: "#888",
  downloading: "#0ea5e9",
  processing: "#0ea5e9",
  stitching: "#0ea5e9",
  done: "#22c55e",
  failed: "#ef4444",
};

export default function StatusBadge({ status }: { status: string }) {
  const color = COLORS[status] || "#888";
  return (
    <span
      style={{
        display: "inline-block",
        padding: "0.15rem 0.6rem",
        borderRadius: 999,
        fontSize: "0.8rem",
        border: `1px solid ${color}`,
        color,
        textTransform: "capitalize",
      }}
    >
      {status}
    </span>
  );
}
