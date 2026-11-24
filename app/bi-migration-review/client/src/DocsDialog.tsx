import { useEffect, useState } from 'react';
import DOMPurify from 'dompurify';
import { marked } from 'marked';
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@databricks/appkit-ui/react';

export type AppDocument = 'installation-guide' | 'mapping-guide';

const DOCUMENTS: Record<AppDocument, { title: string; description: string; endpoint: string }> = {
  'installation-guide': {
    title: 'Installation guide',
    description: 'Prerequisites, workflow deployment, and App deployment',
    endpoint: '/api/docs/installation',
  },
  'mapping-guide': {
    title: 'Mapping guide',
    description: 'How to describe Tableau-to-Databricks table and field mappings',
    endpoint: '/api/docs/mapping-guide',
  },
};

export function renderMarkdown(markdown: string): string {
  const html = marked.parse(markdown, { async: false, gfm: true });
  return DOMPurify.sanitize(html, { USE_PROFILES: { html: true } });
}

export function DocsDialog({ document, onClose }: { document: AppDocument | null; onClose: () => void }) {
  const [loaded, setLoaded] = useState<{ document: AppDocument; html?: string; error?: string } | null>(null);

  useEffect(() => {
    if (!document) return;
    let cancelled = false;
    fetch(DOCUMENTS[document].endpoint)
      .then(async (response) => {
        const text = await response.text();
        if (!response.ok) throw new Error(text || `HTTP ${response.status}`);
        if (!cancelled) setLoaded({ document, html: renderMarkdown(text) });
      })
      .catch((loadError: unknown) => {
        if (!cancelled) {
          setLoaded({
            document,
            error: loadError instanceof Error ? loadError.message : 'Documentation is unavailable.',
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [document]);

  const current = loaded && loaded.document === document ? loaded : null;
  const html = current?.html ?? null;
  const error = current?.error ?? null;
  const meta = document ? DOCUMENTS[document] : null;
  return (
    <Dialog open={document !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="doc-dialog">
        <DialogHeader>
          <DialogTitle>{meta?.title}</DialogTitle>
          <DialogDescription>{meta?.description}</DialogDescription>
        </DialogHeader>
        <div className="doc-dialog__body">
          {error ? <p className="doc-dialog__status">{error}</p> : null}
          {!error && html === null ? <p className="doc-dialog__status">Loading…</p> : null}
          {html ? <article className="doc-prose" dangerouslySetInnerHTML={{ __html: html }} /> : null}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
