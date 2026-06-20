import { useGoing } from "../../lib/going";
import { IconGoing } from "../../lib/icons";

// «Ты идёшь» marker for list rows / cards — passive recognition of your RSVPs while scanning.
// Reads the global going store directly (no prop threading); renders nothing unless you're going.
export function GoingBadge({ eventId, className = "" }: { eventId: string; className?: string }) {
  const going = useGoing();
  if (!going.has(eventId)) return null;
  return (
    <span className={`going-badge${className ? ` ${className}` : ""}`} title="Ты идёшь" aria-label="Ты идёшь">
      <IconGoing size={12} />
    </span>
  );
}
