import { cfg } from './config';

/**
 * Durable-ish publish path: batches that fail (API restarting, network blip)
 * are queued in memory and flushed on the next poll — detections are never
 * silently dropped. Queue is capped; oldest rows are shed beyond the cap.
 */
const queue: object[] = [];
const MAX_QUEUE = 500;

export async function publish(batch: object[]): Promise<{ sent: number; queued: number }> {
  queue.push(...batch);
  if (queue.length > MAX_QUEUE) queue.splice(0, queue.length - MAX_QUEUE);
  if (queue.length === 0) return { sent: 0, queued: 0 };

  try {
    const res = await fetch(`${cfg.apiUrl}/api/v1/ingest/events`, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        ...(cfg.ingestToken ? { 'x-ingest-token': cfg.ingestToken } : {}),
      },
      body: JSON.stringify(queue),
    });
    if (!res.ok) throw new Error(`API ${res.status}`);
    const sent = queue.length;
    queue.length = 0;
    return { sent, queued: 0 };
  } catch {
    // API unreachable: keep everything queued; the next poll retries.
    return { sent: 0, queued: queue.length };
  }
}

