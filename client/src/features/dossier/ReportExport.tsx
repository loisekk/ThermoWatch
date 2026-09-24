/**
 * Report export — hands off to the server-rendered markdown report endpoint
 * (/v2/incidents/{id}/report). Opens in a new tab; a plain download link is
 * used instead of fetch-blob so the browser handles large reports natively.
 */
import { useState } from 'react';
import { v2Api } from '@/services/api/v2Client';

export function ReportExport({ incidentId }: { incidentId: string }) {
  const [copied, setCopied] = useState(false);
  const reportUrl = v2Api.getReportUrl(incidentId);

  const handleCopyLink = async () => {
    try {
      await navigator.clipboard.writeText(reportUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard blocked (permissions/insecure context) — link is visible above.
      setCopied(false);
    }
  };

  return (
    <section
      className="rounded-md border border-edge bg-panel/60 p-3"
      aria-label="Report export"
    >
      <h4 className="mono mb-2 text-[10px] font-semibold uppercase tracking-widest text-mute">
        Report Export
      </h4>

      <div className="space-y-2">
        <p className="text-[10px] leading-relaxed text-mute">
          Server-rendered markdown dossier: evidence summary, full observation
          timeline, association rationale and the complete review audit trail.
        </p>

        <div className="flex flex-wrap gap-1.5">
          <a
            href={reportUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="mono rounded-sm border border-ember/50 bg-ember/10 px-2.5 py-1.5 text-[10px] uppercase tracking-wider text-ember transition-colors hover:bg-ember/20"
          >
            Open report
          </a>
          <a
            href={reportUrl}
            download={`incident-${incidentId.slice(0, 8)}.md`}
            className="mono rounded-sm border border-edge px-2.5 py-1.5 text-[10px] uppercase tracking-wider text-mute transition-colors hover:border-steel hover:text-ink"
          >
            Download .md
          </a>
          <button
            type="button"
            onClick={() => void handleCopyLink()}
            className="mono rounded-sm border border-edge px-2.5 py-1.5 text-[10px] uppercase tracking-wider text-mute transition-colors hover:border-steel hover:text-ink"
          >
            {copied ? 'Copied' : 'Copy link'}
          </button>
        </div>

        <code className="mono block truncate rounded-sm bg-panel2 px-2 py-1 text-[9px] text-dim">
          {reportUrl}
        </code>
      </div>
    </section>
  );
}
