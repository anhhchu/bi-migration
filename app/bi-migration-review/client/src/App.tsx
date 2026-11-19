import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
  Progress,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@databricks/appkit-ui/react';
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  CircleHelp,
  Copy,
  ExternalLink,
  FileUp,
  FileWarning,
  Layers3,
  UserRound,
} from 'lucide-react';

type GroupSummary = {
  group_id: string;
  display_name: string;
  selection_id: string;
  corpus_id: 'downloaded' | 'synthetic' | 'uploaded';
  corpus_label: string;
  coverage_signature: string;
  assets: string[];
  field_count: number;
  mapped_fields: number;
  unresolved_fields: number;
  mapping_percentage: number;
  contract_status: string;
  ready: boolean;
};

type ReviewResponse = {
  run: { kind: 'test_portfolio'; label: string; description: string };
  journey: string[];
  groups: GroupSummary[];
  summary: {
    artifacts: number;
    workbooks: number;
    dashboards: number;
    groups: number;
    readyGroups: number;
    mappedFields: number;
    unresolvedFields: number;
    quarantined: number;
    inventoryErrors: number;
  };
  groupEvidence: Record<string, { reason: string; dependencies: string[]; sharedDependencies: string[] }>;
};

type GroupDetail = {
  groupId: string;
  readiness: {
    ready: boolean;
    contract_status: string;
    coverage: {
      total_fields: number;
      mapped_fields: number;
      dispositioned_fields: number;
      unresolved_fields: number;
      mapping_percentage: number;
      total_relationships: number;
      mapped_relationships: number;
      unresolved_relationships: number;
    };
    issues: Array<{ code: string; count: number; severity: string }>;
    unresolved: Array<{ datasource: string; legacy: string; assets: string[] }>;
  };
  sourceInventory: Array<{
    asset_id: string;
    source_file: string;
    dashboards: Array<{ name: string }>;
    worksheets: Array<unknown>;
    datasources: Array<{
      id: string;
      caption?: string;
      tables?: string[];
    }>;
  }>;
  grouping: { reason: string; dependencies: string[]; sharedDependencies: string[] } | null;
  mappingContract: {
    status: string;
    kpis?: Array<{
      legacy_name: string;
      legacy_expression: string;
      aliases?: string[];
      assets?: string[];
    }>;
    workbook_helpers?: Array<{ name: string; assets?: string[]; datasources?: string[] }>;
    relationships?: Array<{
      datasource: string;
      source: { left_table: string; right_table: string; join_type: string; condition: string; source_kind: string };
      target: {
        left_table_candidates: string[];
        right_table_candidates: string[];
        join_type: string;
        condition: string;
        cardinality: string;
        temporal_predicates: string[];
        record_filters: string[];
      };
      confidence: number;
      status: string;
      evidence?: string[];
      assets?: string[];
    }>;
    fields: Array<{
      datasource: string;
      legacy: string;
      datatype: string;
      calculation?: string | null;
      target_table?: string;
      target_expression?: string;
      source_table?: string;
      source_grain?: string;
      target_grain?: string;
      conversion?: string;
      confidence?: number;
      status: string;
      evidence?: string[];
      assets?: string[];
    }>;
  };
};

type UploadResponse = {
  migrationName: string;
  migrationRoot?: string | null;
  storage: string;
  uploadDestination: { fullName: string; path: string } | null;
  files: Array<{ name: string; sizeBytes: number; status: string; kind: string; volumePath?: string }>;
  detectedNamespaces: Array<{ catalog: string; schema: string }>;
  processing: {
    status: 'idle' | 'running' | 'complete' | 'failed';
    message: string;
    runId?: number | null;
    runUrl?: string | null;
  };
};

type SemanticWorkflowRun = {
  workflowRunId: string;
  databricksRunId: number;
  requestedBy: string;
  submittedAt: string;
  lifeCycleState?: string;
  resultState?: string;
  runUrl?: string | null;
  tasks?: Array<{ taskKey: string; lifeCycleState: string; resultState: string }>;
  artifactPaths?: Record<string, string>;
  artifactAvailability?: Record<string, boolean>;
};

type SemanticResults = {
  manifest: { candidate_metric_view_fqn?: string; genie_agent_name?: string };
  metricView: { status?: string; metric_view_fqn?: string; dimension_count?: number; measure_count?: number };
  agent: {
    status?: string;
    genie_agent?: { name?: string; space_id?: string; url_path?: string };
    benchmark_configuration?: Array<unknown>;
    benchmark_summary?: {
      num_questions?: number;
      num_correct?: number;
      num_needs_review?: number;
      num_bad?: number;
      failures?: string[];
    };
    exceptions?: Array<{ id?: string; detail?: string }>;
  };
  audit: { status?: string; warnings?: string[]; missing?: string[] };
  promotion?: {
    status?: string;
    final_metric_view_fqn?: string;
    final_agent_name?: string;
    approved_by?: string;
    approved_at?: string;
  } | null;
};

type JobSetup = {
  instructions: string;
  jobs: Array<{
    label: string;
    jobId?: string;
    jobUrl?: string | null;
    tasks: Array<{ taskKey: string; prompt: string }>;
  }>;
};

type DatabricksTargets = {
  catalog: string;
  schema: string;
  identity: string;
  tables: Array<{
    fullName: string;
    name: string;
    tableType: string;
    comment?: string;
    columns: Array<{ name: string; type: string }>;
  }>;
};
type MappingStatus = 'unavailable' | 'unmapped' | 'imported' | 'suggested' | 'draft' | 'approved';

const mappingStatusLabels: Record<MappingStatus, string> = {
  unavailable: 'Target unavailable',
  unmapped: 'Unmapped',
  imported: 'Imported mapping',
  suggested: 'Suggested',
  draft: 'Updated',
  approved: 'Approved',
};

function parseCsv(content: string) {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = '';
  let quoted = false;
  for (let index = 0; index < content.length; index += 1) {
    const character = content[index];
    if (character === '"' && quoted && content[index + 1] === '"') {
      cell += '"';
      index += 1;
    } else if (character === '"') {
      quoted = !quoted;
    } else if (character === ',' && !quoted) {
      row.push(cell);
      cell = '';
    } else if ((character === '\n' || character === '\r') && !quoted) {
      if (character === '\r' && content[index + 1] === '\n') index += 1;
      row.push(cell);
      if (row.some((value) => value.length > 0)) rows.push(row);
      row = [];
      cell = '';
    } else {
      cell += character;
    }
  }
  row.push(cell);
  if (row.some((value) => value.length > 0)) rows.push(row);
  return rows;
}

function getMappingStatus(
  field: GroupDetail['mappingContract']['fields'][number],
  targets: DatabricksTargets | null,
  saved: boolean
): MappingStatus {
  const imported = field.evidence?.some((item) => item.startsWith('mapping_document:'));
  const userSaved = field.evidence?.includes('user_selected_unity_catalog');
  if (field.status === 'approved') return 'approved';
  if (
    targets &&
    field.target_table &&
    !targets.tables.some(
      (table) =>
        table.fullName === field.target_table &&
        (field.conversion === 'calculated' || table.columns.some((column) => column.name === field.target_expression))
    )
  ) {
    return 'unavailable';
  }
  if (saved || userSaved) return 'draft';
  if (imported) return 'imported';
  if (field.status === 'proposed') return 'suggested';
  return 'unmapped';
}

const issueLabels: Record<string, string> = {
  contract_not_approved: 'Contract approval required',
  unresolved_fields: 'Field mappings unresolved',
  mapping_conflicts: 'Mapping evidence conflicts',
  inventory_errors: 'Inventory errors detected',
  mapping_document_errors: 'Mapping documents quarantined',
};

export default function App() {
  const [view, setView] = useState<'upload' | 'review'>(() =>
    new URLSearchParams(window.location.search).get('view') === 'review' ? 'review' : 'upload'
  );
  const [review, setReview] = useState<ReviewResponse | null>(null);
  const [selectedGroupId, setSelectedGroupId] = useState<string | null>(null);
  const [detail, setDetail] = useState<GroupDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mappingOpen, setMappingOpen] = useState(
    () => new URLSearchParams(window.location.search).get('mapping') === 'open'
  );
  const [sessionUser, setSessionUser] = useState<{ displayName: string; userName: string } | null>(null);

  useEffect(() => {
    void fetch('/api/session')
      .then((response) => response.json() as Promise<{ displayName: string; userName: string }>)
      .then(setSessionUser)
      .catch(() => setSessionUser({ displayName: 'Signed-in Databricks user', userName: '' }));
  }, []);

  const loadReview = async (preferredCorpusId?: string) => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch('/api/review');
      const payload = (await response.json()) as ReviewResponse & { error?: string; detail?: string };
      if (!response.ok) throw new Error([payload.error, payload.detail].filter(Boolean).join(' '));
      setReview(payload);
      setSelectedGroupId((current) => {
        if (preferredCorpusId) {
          return payload.groups.find((group) => group.corpus_id === preferredCorpusId)?.selection_id ?? current;
        }
        return current ?? payload.groups[0]?.selection_id ?? null;
      });
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Unable to load review output.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!selectedGroupId) {
      setDetail(null);
      return;
    }
    const loadDetail = async () => {
      setDetailLoading(true);
      try {
        const [corpusId, groupId] = selectedGroupId.split(':');
        const response = await fetch(`/api/groups/${groupId}?corpus=${corpusId}`);
        const payload = (await response.json()) as GroupDetail & { error?: string };
        if (!response.ok) throw new Error(payload.error ?? 'Unable to load semantic group.');
        setDetail({
          ...payload,
          readiness: {
            ...payload.readiness,
            issues: payload.readiness?.issues ?? [],
            unresolved: payload.readiness?.unresolved ?? [],
          },
          sourceInventory: (payload.sourceInventory ?? []).map((asset) => ({
            ...asset,
            dashboards: asset.dashboards ?? [],
            worksheets: asset.worksheets ?? [],
            datasources: asset.datasources ?? [],
          })),
          mappingContract: {
            ...payload.mappingContract,
            fields: payload.mappingContract?.fields ?? [],
            kpis: payload.mappingContract?.kpis ?? [],
            workbook_helpers: payload.mappingContract?.workbook_helpers ?? [],
          },
        });
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : 'Unable to load semantic group.');
      } finally {
        setDetailLoading(false);
      }
    };
    void loadDetail();
  }, [selectedGroupId]);

  const selectedGroup = useMemo(
    () => review?.groups.find((group) => group.selection_id === selectedGroupId) ?? null,
    [review, selectedGroupId]
  );

  return (
    <TooltipProvider>
      <div className="app-shell">
        <header className="app-header">
          <div className="app-header__inner">
            <div>
              <p className="app-kicker">BI migration control plane</p>
              <h1 className="app-title">Migration review</h1>
            </div>
            <div className="header-actions">
              <a className="header-doc-link" href="/api/docs/project-plan" target="_blank" rel="noreferrer">
                Project plan
              </a>
              <a className="header-doc-link" href="/api/docs/mapping-guide" target="_blank" rel="noreferrer">
                Mapping guide
              </a>
              <div className="header-user" title={sessionUser?.userName || sessionUser?.displayName}>
                <UserRound className="size-4" aria-hidden="true" />
                <span>{sessionUser?.displayName || 'Loading user…'}</span>
              </div>
            </div>
          </div>
        </header>

        <div className="app-body">
          <aside className="workflow-sidebar">
            <p className="workflow-sidebar__label">Migration workflow</p>
            <nav aria-label="Migration workflow steps">
              <button
                className={view === 'upload' ? 'workflow-step workflow-step--active' : 'workflow-step'}
                type="button"
                onClick={() => {
                  setView('upload');
                  setMappingOpen(false);
                }}
              >
                <span>1</span>
                Upload assets
              </button>
              <button
                className={view === 'review' && !mappingOpen ? 'workflow-step workflow-step--active' : 'workflow-step'}
                type="button"
                onClick={() => {
                  setMappingOpen(false);
                  void loadReview('uploaded').then(() => setView('review'));
                }}
              >
                <span>2</span>
                Review groups
              </button>
            </nav>
          </aside>

          <main className="review-main">
          <section className="page-intro">
            <h2>Scale governed BI migration to Databricks</h2>
            <p>
              Inventory BI portfolios, standardize mappings and metrics, orchestrate migration waves, and validate AI/BI
              outputs with traceable approvals.
            </p>
          </section>

          {view === 'upload' ? (
            <UploadPanel
              onReview={() => {
                void loadReview('uploaded').then(() => setView('review'));
              }}
            />
          ) : null}
          <div className="review-content" hidden={view !== 'review'}>
            {error ? (
              <Alert variant="destructive">
                <AlertCircle className="size-4" />
                <AlertTitle>Review data unavailable</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}
            {loading ? <LoadingState /> : null}
            {!loading && review?.groups.length === 0 ? (
              <EmptyMessage
                title="No semantic groups"
                description="Upload assets and run inventory before reviewing semantic groups."
              />
            ) : null}
            {!loading && review && review.groups.length > 0 ? (
              mappingOpen && selectedGroup && detail ? (
                <MappingWorkspace group={selectedGroup} detail={detail} onBack={() => setMappingOpen(false)} />
              ) : (
                <>
                  <Alert className="run-context">
                    <Layers3 className="size-4" />
                    <AlertTitle>{review.run.label}</AlertTitle>
                    <AlertDescription>{review.run.description}</AlertDescription>
                  </Alert>
                  <SummaryCards review={review} />
                  <div className="review-workspace">
                    <GroupTable
                      groups={review.groups}
                      evidence={review.groupEvidence}
                      selectedGroupId={selectedGroupId}
                      onSelect={setSelectedGroupId}
                    />
                    <GroupPanel
                      group={selectedGroup}
                      detail={detail}
                      loading={detailLoading}
                      onReviewMappings={() => setMappingOpen(true)}
                    />
                  </div>
                </>
              )
            ) : null}
          </div>
          </main>
        </div>
      </div>
    </TooltipProvider>
  );
}

function UploadPanel({ onReview }: { onReview: () => void }) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploads, setUploads] = useState<UploadResponse | null>(null);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [selectedVolume, setSelectedVolume] = useState('');
  const [migrationName, setMigrationName] = useState('');
  const [mappingPreview, setMappingPreview] = useState<{ name: string; content: string } | null>(null);
  const previewRows = useMemo(
    () => (mappingPreview?.name.toLowerCase().endsWith('.csv') ? parseCsv(mappingPreview.content) : []),
    [mappingPreview]
  );

  const loadUploads = async () => {
    const query = selectedVolume ? `?volume=${encodeURIComponent(selectedVolume)}` : '';
    const response = await fetch(`/api/uploads${query}`);
    const payload = (await response.json()) as UploadResponse;
    setUploads({
      ...payload,
      files: payload.files ?? [],
      detectedNamespaces: payload.detectedNamespaces ?? [],
      processing: payload.processing ?? { status: 'idle', message: 'Ready to process uploaded assets.' },
    });
    if (payload.uploadDestination?.fullName) {
      setSelectedVolume((current) => current || payload.uploadDestination?.fullName || '');
    }
    setMigrationName((current) => current || payload.migrationName || '');
  };

  const applyMigrationName = async () => {
    const response = await fetch('/api/migration-context', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ name: migrationName }),
    });
    const payload = (await response.json()) as { name?: string; error?: string };
    if (!response.ok || !payload.name) {
      setUploadError(payload.error ?? 'Could not set migration name.');
      return;
    }
    setMigrationName(payload.name);
    await loadUploads();
  };

  useEffect(() => {
    void loadUploads();
    const timer = window.setInterval(() => void loadUploads(), 3000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (selectedVolume) void loadUploads();
  }, [selectedVolume]);

  const uploadFiles = async () => {
    setBusy(true);
    setUploadError(null);
    try {
      for (const file of selectedFiles) {
        const response = await fetch('/api/uploads', {
          method: 'POST',
          headers: {
            'x-file-name': encodeURIComponent(file.name),
            'x-volume-name': selectedVolume,
            'content-type': 'application/octet-stream',
          },
          body: file,
        });
        const payload = (await response.json()) as { error?: string };
        if (!response.ok) throw new Error(payload.error ?? `Could not upload ${file.name}.`);
      }
      setSelectedFiles([]);
      if (fileInputRef.current) fileInputRef.current.value = '';
      await loadUploads();
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : 'Upload failed.');
    } finally {
      setBusy(false);
    }
  };

  const previewMapping = async (fileName: string) => {
    setUploadError(null);
    const response = await fetch(`/api/uploads/${encodeURIComponent(fileName)}/content`);
    const payload = (await response.json()) as { name?: string; content?: string; error?: string };
    if (!response.ok || !payload.name || payload.content === undefined) {
      setUploadError(payload.error ?? 'Could not open mapping evidence.');
      return;
    }
    setMappingPreview({ name: payload.name, content: payload.content });
  };

  const processUploads = async () => {
    setBusy(true);
    setUploadError(null);
    try {
      const response = await fetch('/api/uploads/process', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ volume: selectedVolume }),
      });
      const responseText = await response.text();
      let payload: { error?: string; detail?: string } = {};
      try {
        payload = JSON.parse(responseText) as { error?: string; detail?: string };
      } catch {
        throw new Error(`Inventory request failed with HTTP ${response.status}.`);
      }
      if (!response.ok) {
        throw new Error([payload.error, payload.detail].filter(Boolean).join(' ') || 'Could not start inventory processing.');
      }
      await loadUploads();
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : 'Processing failed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="upload-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FileUp className="size-5" />
          Upload test assets
        </CardTitle>
      </CardHeader>
      <CardContent className="upload-content">
        <div className="upload-dropzone">
          <label htmlFor="tableau-files">Choose workbooks and mapping evidence</label>
          <p>TWB/TWBX plus CSV, JSON, YAML, or Markdown mappings, up to 100 MB each.</p>
          <input
            ref={fileInputRef}
            id="tableau-files"
            type="file"
            accept=".twb,.twbx,.csv,.json,.yaml,.yml,.md"
            multiple
            onChange={(event) => {
              const addedFiles = Array.from(event.target.files ?? []);
              setSelectedFiles((current) => {
                const filesByIdentity = new Map(
                  current.map((file) => [`${file.name}:${file.size}:${file.lastModified}`, file])
                );
                for (const file of addedFiles) {
                  filesByIdentity.set(`${file.name}:${file.size}:${file.lastModified}`, file);
                }
                return Array.from(filesByIdentity.values());
              });
              event.target.value = '';
            }}
          />
          <div className="upload-dropzone__actions">
            <Button variant="outline" onClick={() => fileInputRef.current?.click()} disabled={busy}>
              Choose files
            </Button>
          </div>
          {selectedFiles.length > 0 ? (
            <p className="upload-action-hint">
              {selectedFiles.length} {selectedFiles.length === 1 ? 'file' : 'files'} selected
            </p>
          ) : null}
        </div>
        {uploadError ? (
          <Alert variant="destructive">
            <AlertCircle className="size-4" />
            <AlertTitle>Action failed</AlertTitle>
            <AlertDescription>{uploadError}</AlertDescription>
          </Alert>
        ) : null}
        <div className="upload-status">
          <div>
            <h3>Landing inventory</h3>
            <p>{uploads?.storage ?? 'Loading storage status…'}</p>
          </div>
          <Badge variant="outline">
            {uploads?.files.length ?? 0} uploaded
            {selectedFiles.length > 0 ? ` · ${selectedFiles.length} selected` : ''}
          </Badge>
        </div>
        <div className="upload-file-list">
          {selectedFiles.map((file) => (
            <div className="upload-file upload-file--pending" key={`pending-${file.name}-${file.lastModified}`}>
              <span>
                <strong>{file.name}</strong>
                <small>Pending upload</small>
              </span>
              <span>{(file.size / 1024).toFixed(1)} KB</span>
            </div>
          ))}
          {uploads?.files.map((file) => (
            <div className="upload-file" key={file.name}>
              <span>
                {file.kind === 'Mapping evidence' ? (
                  <button className="upload-file__preview" type="button" onClick={() => void previewMapping(file.name)}>
                    {file.name}
                  </button>
                ) : (
                  <strong>{file.name}</strong>
                )}
                <small>{file.kind}</small>
                {file.volumePath ? <small className="upload-volume-path">{file.volumePath}</small> : null}
              </span>
              <span>{(file.sizeBytes / 1024).toFixed(1)} KB</span>
            </div>
          ))}
        </div>
        <Dialog open={mappingPreview !== null} onOpenChange={(open) => !open && setMappingPreview(null)}>
          <DialogContent className="mapping-preview-dialog">
            <DialogHeader>
              <DialogTitle>{mappingPreview?.name ?? 'Mapping evidence'}</DialogTitle>
              <DialogDescription>Uploaded mapping evidence</DialogDescription>
            </DialogHeader>
            {previewRows.length > 0 ? (
              <div className="mapping-preview-table">
                <Table>
                  <TableHeader>
                    <TableRow>
                      {previewRows[0].map((heading) => (
                        <TableHead key={heading}>{heading}</TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {previewRows.slice(1).map((row) => (
                      <TableRow key={row.join('\u0000')}>
                        {previewRows[0].map((heading, columnIndex) => (
                          <TableCell key={heading}>{row[columnIndex] ?? ''}</TableCell>
                        ))}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            ) : (
              <pre>{mappingPreview?.content}</pre>
            )}
            <DialogFooter>
              <Button variant="outline" onClick={() => setMappingPreview(null)}>
                Close
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
        <div>
          <h3>Detected target namespaces</h3>
          <p className="mapping-source-note">
            Fully qualified Databricks tables are detected from uploaded mappings. Change the selection only to inspect an additional scope.
          </p>
          {uploads?.detectedNamespaces.length ? (
            <div className="detected-namespaces" aria-label="Detected Databricks scopes">
              {uploads.detectedNamespaces.map((namespace) => (
                <Badge variant="outline" key={`${namespace.catalog}.${namespace.schema}`}>
                  {namespace.catalog}.{namespace.schema}
                </Badge>
              ))}
            </div>
          ) : (
            <p className="mapping-source-note">No Databricks scope detected from the uploaded files yet.</p>
          )}
        </div>
        <div className="namespace-picker">
          <div className="namespace-picker__heading">
            <h3>Upload destination</h3>
            <p>The app uploads assets to its authorized Unity Catalog Volume.</p>
          </div>
          <label>
            Volume
            <select value={selectedVolume} disabled={!selectedVolume}>
              <option value="">Loading authorized Volume…</option>
              {selectedVolume ? <option value={selectedVolume}>{selectedVolume}</option> : null}
            </select>
          </label>
          <label>
            Migration name
            <input value={migrationName} onChange={(event) => setMigrationName(event.target.value)} />
          </label>
          <Button variant="outline" onClick={() => void applyMigrationName()} disabled={!migrationName.trim()}>
            Use migration
          </Button>
        </div>
        <div className="upload-destination-action">
          <Button
            onClick={() => void uploadFiles()}
            disabled={busy || selectedFiles.length === 0 || !selectedVolume}
          >
            {busy
              ? 'Uploading…'
              : selectedFiles.length > 0
                ? `Upload ${selectedFiles.length} ${selectedFiles.length === 1 ? 'file' : 'files'}`
                : 'Upload files'}
          </Button>
          {selectedFiles.length > 0 && !selectedVolume ? (
            <span>Choose a Volume to enable upload.</span>
          ) : selectedVolume ? (
            <span>Destination: /Volumes/{selectedVolume.split('.').join('/')}/bi-migrations/{migrationName || 'migration-name'}/</span>
          ) : null}
        </div>
        <div className="upload-actions">
          <Button
            variant="outline"
            onClick={() => void processUploads()}
            disabled={
              busy ||
              !uploads?.files.length ||
              uploads.processing.status === 'running'
            }
          >
            Run inventory
          </Button>
          <span>
            {uploads?.processing.message || 'Upload files, then run inventory and grouping.'}
            {uploads?.processing.runUrl ? (
              <>
                {' '}
                <a className="job-run-link" href={uploads.processing.runUrl} target="_blank" rel="noreferrer">
                  View Job run
                  <ExternalLink aria-hidden="true" />
                </a>
              </>
            ) : null}
          </span>
          {uploads?.processing.status === 'complete' ? <Button onClick={onReview}>Review groups</Button> : null}
        </div>
      </CardContent>
    </Card>
  );
}

function SummaryCards({ review }: { review: ReviewResponse }) {
  const items = [
    {
      label: 'Workbooks inventoried',
      value: review.summary.workbooks,
      detail: `${review.summary.artifacts} Tableau files registered`,
      help: 'Distinct TWB or TWBX workbooks successfully registered in this pipeline run. This is not a dashboard count.',
    },
    {
      label: 'Dashboard pages found',
      value: review.summary.dashboards,
      detail: `Across ${review.summary.workbooks} workbooks`,
      help: 'Named interactive pages found inside the inventoried workbooks. Tableau technically calls each of these pages a dashboard object.',
    },
    {
      label: 'Semantic groups',
      value: review.summary.groups,
      detail: `${review.summary.readyGroups} ready for import`,
      help: 'Connected components of workbooks that share datasource or table dependencies. Mapping and approval happen once per group.',
    },
    {
      label: 'Fields mapped',
      value: review.summary.mappedFields,
      detail: `${review.summary.unresolvedFields} unresolved`,
      help: 'Legacy workbook fields with an accepted target mapping. The unresolved count still needs mapping evidence or a documented disposition.',
    },
    {
      label: 'Quarantined',
      value: review.summary.quarantined,
      detail: `${review.summary.inventoryErrors} inventory errors`,
      help: 'Files isolated because they could not be safely inventoried. Quarantined files do not participate in grouping.',
    },
  ];
  return (
    <section aria-label="Portfolio summary" className="summary-band">
      {items.map((item) => (
        <div className="summary-item" key={item.label}>
          <p className="summary-item__label">
            {item.label} <InfoTooltip label={item.label} content={item.help} />
          </p>
          <p className="summary-item__value">{item.value.toLocaleString()}</p>
          <p className="summary-item__detail">{item.detail}</p>
        </div>
      ))}
    </section>
  );
}

function GroupTable({
  groups,
  evidence,
  selectedGroupId,
  onSelect,
}: {
  groups: GroupSummary[];
  evidence: ReviewResponse['groupEvidence'];
  selectedGroupId: string | null;
  onSelect: (groupId: string) => void;
}) {
  return (
    <Card className="workspace-card semantic-groups-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Layers3 className="size-5" />
          Semantic groups
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>
                Workbook group{' '}
                <InfoTooltip
                  label="Semantic group"
                  content="Workbooks connected by shared datasource or table dependencies."
                />
              </TableHead>
              <TableHead>Workbooks</TableHead>
              <TableHead>
                Coverage{' '}
                <InfoTooltip
                  label="Mapping coverage"
                  content="Mapped legacy fields divided by all distinct legacy fields inventoried for this group."
                />
              </TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {groups.map((group) => (
              <TableRow
                key={group.selection_id}
                data-state={selectedGroupId === group.selection_id ? 'selected' : undefined}
                className="group-row"
                onClick={() => onSelect(group.selection_id)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') onSelect(group.selection_id);
                }}
                tabIndex={0}
              >
                <TableCell>
                  <div className="group-name">
                    <span className="font-medium group-display-name">{group.display_name}</span>
                    <InfoTooltip
                      label={`${group.display_name} details`}
                      content={evidence[group.selection_id]?.reason ?? 'Grouping evidence is unavailable.'}
                    />
                  </div>
                  <Badge className="corpus-badge" variant="outline">
                    {group.corpus_label}
                  </Badge>
                </TableCell>
                <TableCell className="tabular-nums">{group.assets.length}</TableCell>
                <TableCell>
                  <div className="coverage-cell">
                    <div className="coverage-cell__labels">
                      <span>{group.mapping_percentage.toFixed(1)}%</span>
                      <span className="text-muted-foreground">
                        {group.mapped_fields}/{group.field_count}
                      </span>
                    </div>
                    <Progress value={group.mapping_percentage} />
                  </div>
                </TableCell>
                <TableCell>
                  <Badge variant={group.ready ? 'default' : 'secondary'}>{group.ready ? 'Ready' : 'Blocked'}</Badge>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function GroupPanel({
  group,
  detail,
  loading,
  onReviewMappings,
}: {
  group: GroupSummary | null;
  detail: GroupDetail | null;
  loading: boolean;
  onReviewMappings: () => void;
}) {
  if (loading) return <DetailLoadingState />;
  if (!group || !detail)
    return (
      <Card className="workspace-card">
        <CardContent className="pt-6">
          <EmptyMessage title="Select a semantic group" description="Choose a group to inspect mapping readiness." />
        </CardContent>
      </Card>
    );
  return (
    <Card className="workspace-card">
      <CardHeader className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <CardTitle>{group.display_name}</CardTitle>
          <Badge variant={detail.readiness.ready ? 'default' : 'destructive'}>
            {detail.readiness.ready ? 'Ready' : 'Action required'}
          </Badge>
        </div>
        <div className="detail-meta">
          <span>{detail.readiness.contract_status} contract</span>
          <span>·</span>
          <span>{detail.readiness.coverage.mapping_percentage.toFixed(1)}% coverage</span>
          <span>·</span>
          <span>
            {group.assets.length} workbook{group.assets.length === 1 ? '' : 's'}
          </span>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        <section className="detail-section grouping-evidence">
          <h3>
            Why this group?{' '}
            <InfoTooltip
              label="Grouping evidence"
              content="Grouping is based on shared technical dependencies, not similar workbook titles or business topics."
            />
          </h3>
          <p>{detail.grouping?.reason ?? 'Grouping evidence is unavailable.'}</p>
        </section>
        <section className="detail-section">
          <h3>Blocking checks</h3>
          {detail.readiness.issues.length === 0 ? (
            <div className="flex items-center gap-2 text-sm">
              <CheckCircle2 className="size-4 text-success" />
              All readiness checks passed.
            </div>
          ) : (
            <div className="check-list">
              {detail.readiness.issues.map((issue) => (
                <div key={issue.code} className="check-row">
                  <span className="check-row__label">
                    <FileWarning className="size-4 text-muted-foreground" />
                    {issueLabels[issue.code] ?? issue.code.replaceAll('_', ' ')}
                  </span>
                  <Badge variant="outline">{issue.count}</Badge>
                </div>
              ))}
            </div>
          )}
        </section>
        <section className="detail-section">
          <h3>Workbooks and dashboard pages</h3>
          <div className="asset-list">
            {detail.sourceInventory.map((asset) => (
              <div key={asset.asset_id} className="asset-row">
                <p className="font-medium">{asset.asset_id}</p>
                <p className="asset-row__meta">
                  {asset.dashboards.length} dashboard pages · {asset.worksheets.length} worksheets ·{' '}
                  {asset.datasources.length} datasources
                </p>
                <ul className="dashboard-list">
                  {asset.dashboards.map((dashboard) => (
                    <li key={dashboard.name}>{dashboard.name}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </section>
        <Button onClick={onReviewMappings}>Review field mappings</Button>
      </CardContent>
    </Card>
  );
}

function MappingWorkspace({ group, detail, onBack }: { group: GroupSummary; detail: GroupDetail; onBack: () => void }) {
  const datasourceFields = useMemo(
    () =>
      detail.mappingContract.fields.filter(
        (field) =>
          field.datasource !== 'Parameters' &&
          !field.calculation &&
          field.datatype !== 'table' &&
          !/^\[.*\]$/.test(field.legacy)
      ),
    [detail.mappingContract.fields]
  );
  const suggestedNamespace = useMemo(() => {
    const importedTarget = datasourceFields.find(
      (field) => field.target_table && field.evidence?.some((item) => item.startsWith('mapping_document:'))
    )?.target_table;
    const targetTable = importedTarget ?? datasourceFields.find((field) => field.target_table)?.target_table;
    const parts = targetTable?.split('.') ?? [];
    return parts.length >= 3 ? { catalog: parts[0], schema: parts[1] } : null;
  }, [datasourceFields]);
  const targets = useMemo<DatabricksTargets | null>(() => {
    const mappedFields = datasourceFields.filter((field) => field.target_table && field.target_expression);
    if (mappedFields.length === 0) return null;
    const tables = new Map<string, DatabricksTargets['tables'][number]>();
    for (const field of mappedFields) {
      const tableName = field.target_table as string;
      const table = tables.get(tableName) ?? {
        fullName: tableName,
        name: tableName.split('.').at(-1) ?? tableName,
        tableType: 'MAPPED_TARGET',
        columns: [],
      };
      if (!table.columns.some((column) => column.name === field.target_expression)) {
        table.columns.push({ name: field.target_expression as string, type: field.datatype });
      }
      tables.set(tableName, table);
    }
    return {
      catalog: suggestedNamespace?.catalog ?? 'mapped',
      schema: suggestedNamespace?.schema ?? 'targets',
      identity: 'uploaded mapping evidence',
      tables: Array.from(tables.values()),
    };
  }, [datasourceFields, suggestedNamespace]);
  const [savedFields, setSavedFields] = useState<Set<string>>(() => new Set());
  const [savedRelationships, setSavedRelationships] = useState<Set<number>>(() => new Set());
  const [expandedStatuses, setExpandedStatuses] = useState<Set<MappingStatus>>(
    () => new Set(['unavailable', 'unmapped', 'imported'])
  );
  const [reviewMode, setReviewMode] = useState<'datasources' | 'relationships' | 'derived'>('datasources');
  const [groupStage, setGroupStage] = useState<'mappings' | 'build' | 'validate' | 'promote'>('mappings');
  const [approvalStatus, setApprovalStatus] = useState(detail.mappingContract.status);
  const [approvalBusy, setApprovalBusy] = useState(false);
  const [approvalError, setApprovalError] = useState<string | null>(null);
  const [importPackage, setImportPackage] = useState<{
    mappingFileName: string;
    contractYaml: string;
    prompt: string;
    session1PromptPath: string;
    metricViewPrompt: string;
    metricViewPromptPath: string;
    genieAgentPrompt: string;
    genieAgentPromptPath: string;
    semanticArtifacts: {
      preflightPath: string;
      session1PromptPath: string;
      metricViewPromptPath: string;
      genieAgentPromptPath: string;
      metricViewPath: string;
      genieAgentPath: string;
      benchmarkPath: string;
    };
    jobSetup: JobSetup;
  } | null>(null);
  const [importPackageOpen, setImportPackageOpen] = useState(false);
  const [semanticRun, setSemanticRun] = useState<SemanticWorkflowRun | null>(null);
  const [dashboardRun, setDashboardRun] = useState<SemanticWorkflowRun | null>(null);
  const [dashboardRunBusy, setDashboardRunBusy] = useState(false);
  const [dashboardRunError, setDashboardRunError] = useState<string | null>(null);
  const [semanticRunBusy, setSemanticRunBusy] = useState(false);
  const [semanticRunError, setSemanticRunError] = useState<string | null>(null);
  const [semanticResults, setSemanticResults] = useState<SemanticResults | null>(null);
  const [semanticResultsError, setSemanticResultsError] = useState<string | null>(null);
  const [semanticResultsLoading, setSemanticResultsLoading] = useState(false);
  const [finalMetricViewFqn, setFinalMetricViewFqn] = useState('');
  const [finalAgentName, setFinalAgentName] = useState('');
  const [promotionNotes, setPromotionNotes] = useState('');
  const [promotionBusy, setPromotionBusy] = useState(false);
  const groupedFields = useMemo(() => {
    const groups = new Map<MappingStatus, GroupDetail['mappingContract']['fields']>();
    for (const status of ['unavailable', 'unmapped', 'imported', 'suggested', 'draft', 'approved'] as const) {
      groups.set(status, []);
    }
    for (const field of datasourceFields) {
      const fieldKey = `${field.datasource}-${field.legacy}`;
      groups.get(getMappingStatus(field, targets, savedFields.has(fieldKey)))?.push(field);
    }
    return Array.from(groups.entries()).filter(([, fields]) => fields.length > 0);
  }, [datasourceFields, savedFields, targets]);
  const blockingMappingCount = groupedFields
    .filter(([status]) => status === 'unavailable' || status === 'unmapped')
    .reduce((total, [, fields]) => total + fields.length, 0);
  const blockingRelationshipCount = (detail.mappingContract.relationships ?? []).filter(
    (relationship, index) => relationship.status === 'unresolved' && !savedRelationships.has(index)
  ).length;
  const totalBlockingCount = blockingMappingCount + blockingRelationshipCount;

  const loadSemanticRun = async () => {
    const response = await fetch(`/api/groups/${group.group_id}/semantic-run`);
    if (!response.ok) return;
    setSemanticRun((await response.json()) as SemanticWorkflowRun);
  };

  const loadDashboardRun = async () => {
    const response = await fetch(`/api/groups/${group.group_id}/dashboard-import-run`);
    if (!response.ok) return;
    setDashboardRun((await response.json()) as SemanticWorkflowRun);
  };

  const loadSemanticResults = async () => {
    setSemanticResultsLoading(true);
    setSemanticResultsError(null);
    try {
      const response = await fetch(`/api/groups/${group.group_id}/semantic-results`);
      const payload = (await response.json()) as SemanticResults & { error?: string; detail?: string };
      if (!response.ok) throw new Error([payload.error, payload.detail].filter(Boolean).join(' '));
      setSemanticResults(payload);
      setFinalMetricViewFqn(
        payload.promotion?.final_metric_view_fqn ?? payload.manifest.candidate_metric_view_fqn ?? ''
      );
      setFinalAgentName(payload.promotion?.final_agent_name ?? payload.agent.genie_agent?.name ?? payload.manifest.genie_agent_name ?? '');
    } catch (error) {
      setSemanticResultsError(error instanceof Error ? error.message : 'Semantic results could not be loaded.');
    } finally {
      setSemanticResultsLoading(false);
    }
  };

  const savePromotion = async () => {
    setPromotionBusy(true);
    setSemanticResultsError(null);
    try {
      const response = await fetch(`/api/groups/${group.group_id}/promotion`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ finalMetricViewFqn, finalAgentName, notes: promotionNotes }),
      });
      const payload = (await response.json()) as SemanticResults['promotion'] & { error?: string; detail?: string };
      if (!response.ok) throw new Error([payload.error, payload.detail].filter(Boolean).join(' '));
      setSemanticResults((current) => current ? { ...current, promotion: payload } : current);
    } catch (error) {
      setSemanticResultsError(error instanceof Error ? error.message : 'Promotion decision could not be saved.');
    } finally {
      setPromotionBusy(false);
    }
  };

  useEffect(() => {
    if (groupStage === 'validate' || groupStage === 'promote') void loadSemanticResults();
  }, [groupStage, group.group_id]);

  useEffect(() => {
    if (approvalStatus !== 'approved') return;
    void loadSemanticRun();
    void loadDashboardRun();
    const timer = window.setInterval(() => {
      if (!semanticRun || !['TERMINATED', 'SKIPPED', 'INTERNAL_ERROR'].includes(semanticRun.lifeCycleState ?? '')) {
        void loadSemanticRun();
      }
      if (!dashboardRun || !['TERMINATED', 'SKIPPED', 'INTERNAL_ERROR'].includes(dashboardRun.lifeCycleState ?? '')) {
        void loadDashboardRun();
      }
    }, 5000);
    return () => window.clearInterval(timer);
  }, [approvalStatus, group.group_id, semanticRun?.lifeCycleState, dashboardRun?.lifeCycleState]);

  const startDashboardImport = async () => {
    setDashboardRunBusy(true);
    setDashboardRunError(null);
    try {
      const response = await fetch(`/api/groups/${group.group_id}/dashboard-import-run`, { method: 'POST' });
      const payload = (await response.json()) as SemanticWorkflowRun & { error?: string; detail?: string };
      if (!response.ok) throw new Error([payload.error, payload.detail].filter(Boolean).join(' '));
      setDashboardRun(payload);
    } catch (error) {
      setDashboardRunError(error instanceof Error ? error.message : 'Dashboard Import Job could not be started.');
    } finally {
      setDashboardRunBusy(false);
    }
  };

  const startSemanticWorkflow = async () => {
    setSemanticRunBusy(true);
    setSemanticRunError(null);
    try {
      const response = await fetch(`/api/groups/${group.group_id}/semantic-run`, { method: 'POST' });
      const payload = (await response.json()) as SemanticWorkflowRun & { error?: string; detail?: string };
      if (!response.ok) throw new Error([payload.error, payload.detail].filter(Boolean).join(' '));
      setSemanticRun(payload);
      setGroupStage('build');
    } catch (error) {
      setSemanticRunError(error instanceof Error ? error.message : 'Semantic workflow could not be started.');
    } finally {
      setSemanticRunBusy(false);
    }
  };

  const approveMappings = async () => {
    setApprovalBusy(true);
    setApprovalError(null);
    try {
      const response = await fetch(`/api/groups/${group.group_id}/mappings/approve`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ corpusId: group.corpus_id }),
      });
      const payload = (await response.json()) as {
        contractYaml?: string;
        mappingFileName?: string;
        prompt?: string;
        session1PromptPath?: string;
        metricViewPrompt?: string;
        metricViewPromptPath?: string;
        genieAgentPrompt?: string;
        genieAgentPromptPath?: string;
        semanticArtifacts?: {
          preflightPath: string;
          session1PromptPath: string;
          metricViewPromptPath: string;
          genieAgentPromptPath: string;
          metricViewPath: string;
          genieAgentPath: string;
          benchmarkPath: string;
        };
        jobSetup?: JobSetup;
        error?: string;
        detail?: string;
      };
      if (
        !response.ok ||
        !payload.contractYaml ||
        !payload.mappingFileName ||
        !payload.prompt ||
        !payload.session1PromptPath ||
        !payload.metricViewPrompt ||
        !payload.metricViewPromptPath ||
        !payload.genieAgentPrompt ||
        !payload.genieAgentPromptPath ||
        !payload.semanticArtifacts ||
        !payload.jobSetup
      ) {
        throw new Error([payload.error, payload.detail].filter(Boolean).join(' ') || 'Approval failed.');
      }
      setApprovalStatus('approved');
      setImportPackage({
        mappingFileName: payload.mappingFileName,
        contractYaml: payload.contractYaml,
        prompt: payload.prompt,
        session1PromptPath: payload.session1PromptPath,
        metricViewPrompt: payload.metricViewPrompt,
        metricViewPromptPath: payload.metricViewPromptPath,
        genieAgentPrompt: payload.genieAgentPrompt,
        genieAgentPromptPath: payload.genieAgentPromptPath,
        semanticArtifacts: payload.semanticArtifacts,
        jobSetup: payload.jobSetup,
      });
      setGroupStage('build');
    } catch (error) {
      setApprovalError(error instanceof Error ? error.message : 'Mappings could not be approved.');
    } finally {
      setApprovalBusy(false);
    }
  };

  const openImportPackage = async (showDialog = true) => {
    setApprovalError(null);
    if (importPackage) {
      if (showDialog) setImportPackageOpen(true);
      return;
    }
    const response = await fetch(
      `/api/groups/${group.group_id}/import-package?corpus=${encodeURIComponent(group.corpus_id)}`
    );
    const payload = (await response.json()) as {
      mappingFileName?: string;
      contractYaml?: string;
      prompt?: string;
      session1PromptPath?: string;
      metricViewPrompt?: string;
      metricViewPromptPath?: string;
      genieAgentPrompt?: string;
      genieAgentPromptPath?: string;
      semanticArtifacts?: {
        preflightPath: string;
        session1PromptPath: string;
        metricViewPromptPath: string;
        genieAgentPromptPath: string;
        metricViewPath: string;
        genieAgentPath: string;
        benchmarkPath: string;
      };
      jobSetup?: JobSetup;
      error?: string;
      detail?: string;
    };
    if (
      !response.ok ||
      !payload.mappingFileName ||
      !payload.contractYaml ||
      !payload.prompt ||
      !payload.session1PromptPath ||
      !payload.metricViewPrompt ||
      !payload.metricViewPromptPath ||
      !payload.genieAgentPrompt ||
      !payload.genieAgentPromptPath ||
      !payload.semanticArtifacts ||
      !payload.jobSetup
    ) {
      if (payload.detail?.includes('uses local paths') || payload.detail?.includes('Prepare the import package again')) {
        setApprovalStatus('mapping-approved');
        await approveMappings();
        return;
      }
      setApprovalError([payload.error, payload.detail].filter(Boolean).join(' ') || 'Import package is unavailable.');
      setApprovalStatus('mapping-approved');
      return;
    }
    setImportPackage({
      mappingFileName: payload.mappingFileName,
      contractYaml: payload.contractYaml,
      prompt: payload.prompt,
      session1PromptPath: payload.session1PromptPath,
      metricViewPrompt: payload.metricViewPrompt,
      metricViewPromptPath: payload.metricViewPromptPath,
      genieAgentPrompt: payload.genieAgentPrompt,
      genieAgentPromptPath: payload.genieAgentPromptPath,
      semanticArtifacts: payload.semanticArtifacts,
      jobSetup: payload.jobSetup,
    });
    if (showDialog) setImportPackageOpen(true);
  };

  useEffect(() => {
    if (approvalStatus === 'approved' && !importPackage) void openImportPackage(false);
  }, [approvalStatus, group.group_id]);

  const downloadContract = () => {
    if (!importPackage) return;
    const url = URL.createObjectURL(new Blob([importPackage.contractYaml], { type: 'application/yaml' }));
      const link = document.createElement('a');
      link.href = url;
      link.download = importPackage.mappingFileName;
      link.click();
      URL.revokeObjectURL(url);
  };

  return (
    <Card className="mapping-workspace-card">
      <CardHeader className="mapping-workspace-header">
        <Button variant="ghost" onClick={onBack}>
          <ArrowLeft className="size-4" />
          Back to groups
        </Button>
        <div>
          <CardTitle>{group.display_name}</CardTitle>
          <p>
            {datasourceFields.length} datasource fields to review · {detail.mappingContract.kpis?.length ?? 0}{' '}
            workbook calculations and {detail.mappingContract.workbook_helpers?.length ?? 0} helper fields cataloged separately
          </p>
        </div>
      </CardHeader>
      <CardContent className="mapping-workspace-content">
        <nav className="group-workflow" aria-label={`${group.display_name} workflow`}>
          {[
            { id: 'mappings' as const, number: 3, label: 'Review mappings', disabled: false },
            { id: 'build' as const, number: 4, label: 'Build assets', disabled: false },
            { id: 'validate' as const, number: 5, label: 'Review results', disabled: semanticRun?.resultState !== 'SUCCESS' },
            { id: 'promote' as const, number: 6, label: 'Promote', disabled: !semanticResults?.audit.status?.startsWith('COMPLETE') },
          ].map((stage) => (
            <button
              className={groupStage === stage.id ? 'group-workflow__step group-workflow__step--active' : 'group-workflow__step'}
              type="button"
              disabled={stage.disabled}
              onClick={() => setGroupStage(stage.id)}
              key={stage.id}
            >
              <span>{stage.number}</span>
              {stage.label}
            </button>
          ))}
        </nav>
        <div className="group-stage" hidden={groupStage !== 'mappings'}>
        <div className="mapping-review-tabs" role="tablist" aria-label="Mapping review type">
          <Button
            variant={reviewMode === 'datasources' ? 'default' : 'outline'}
            role="tab"
            aria-selected={reviewMode === 'datasources'}
            onClick={() => setReviewMode('datasources')}
          >
            Datasource mappings
            <Badge className={reviewMode === 'datasources' ? 'mapping-tab-count--active' : undefined} variant="outline">
              {datasourceFields.length}
            </Badge>
          </Button>
          <Button
            variant={reviewMode === 'relationships' ? 'default' : 'outline'}
            role="tab"
            aria-selected={reviewMode === 'relationships'}
            onClick={() => setReviewMode('relationships')}
          >
            Relationships &amp; grain
            <Badge className={reviewMode === 'relationships' ? 'mapping-tab-count--active' : undefined} variant="outline">
              {detail.mappingContract.relationships?.length ?? 0}
            </Badge>
          </Button>
          <Button
            variant={reviewMode === 'derived' ? 'default' : 'outline'}
            role="tab"
            aria-selected={reviewMode === 'derived'}
            onClick={() => setReviewMode('derived')}
          >
            Derived logic
            <Badge className={reviewMode === 'derived' ? 'mapping-tab-count--active' : undefined} variant="outline">
              {(detail.mappingContract.kpis?.length ?? 0) + (detail.mappingContract.workbook_helpers?.length ?? 0)}
            </Badge>
          </Button>
        </div>
        <div className="mapping-review-pane" hidden={reviewMode !== 'datasources'}>
        <p className="mapping-source-note">
          {targets
            ? `Targets loaded from the ${targets.identity}; physical validation runs in the inventory notebook.`
            : 'Upload mapping evidence with fully qualified Databricks targets.'}
        </p>
        <div className="mapping-groups">
          {groupedFields.map(([status, fields]) => (
            <details
              className={`mapping-status-group mapping-status-group--${status}`}
              key={status}
              open={expandedStatuses.has(status)}
              onToggle={(event) => {
                const open = event.currentTarget.open;
                setExpandedStatuses((current) => {
                  if (current.has(status) === open) return current;
                  const next = new Set(current);
                  if (open) next.add(status);
                  else next.delete(status);
                  return next;
                });
              }}
            >
              <summary className="mapping-status-group__header">
                <h3>
                  <span aria-hidden="true" />
                  {mappingStatusLabels[status]}
                </h3>
                <Badge variant="outline">{fields.length}</Badge>
              </summary>
              <div className="mapping-list">
                {fields.map((field) => {
                  const fieldKey = `${field.datasource}-${field.legacy}`;
                  return (
                    <MappingEditorCard
                      key={`${fieldKey}-${targets ? 'ready' : 'loading'}`}
                      field={field}
                      group={group}
                      targets={targets}
                      status={status}
                      onSaved={() => setSavedFields((current) => new Set(current).add(fieldKey))}
                      usageLabel={field.assets?.join(', ') || 'Workbook usage unavailable'}
                    />
                  );
                })}
              </div>
            </details>
          ))}
        </div>
        <section className="mapping-graph-section">
          <div className="section-heading">
            <div>
              <h3>Mapping graph</h3>
              <p>Source tables and fields mapped to this group’s Databricks targets.</p>
            </div>
          </div>
          <MappingGraph fields={datasourceFields} relationships={detail.mappingContract.relationships ?? []} />
        </section>
        </div>
        <div className="mapping-review-pane" hidden={reviewMode !== 'relationships'}>
          <Alert>
            <Layers3 className="size-4" />
            <AlertTitle>Resolve relationships and grain</AlertTitle>
            <AlertDescription>
              For each unresolved item: select the two Databricks tables, confirm cardinality, enter the join
              condition, then add any as-of predicates and current-record filters required by the target grains.
              Apply the relationship to remove the approval blocker. The approved mapping YAML is updated automatically.
            </AlertDescription>
          </Alert>
          <div className="relationship-list">
            {(detail.mappingContract.relationships ?? []).map((relationship, index) => (
              <RelationshipEditor
                key={`${relationship.datasource}-${index}`}
                relationship={relationship}
                relationshipIndex={index}
                group={group}
                targetTables={targets?.tables.map((table) => table.fullName) ?? []}
                saved={savedRelationships.has(index)}
                onSaved={() => setSavedRelationships((current) => new Set(current).add(index))}
              />
            ))}
            {(detail.mappingContract.relationships?.length ?? 0) === 0 ? <p>No source relationships were found.</p> : null}
          </div>
        </div>
        <div className="mapping-review-pane" hidden={reviewMode !== 'derived'}>
          <Alert>
            <Layers3 className="size-4" />
            <AlertTitle>Derived from the workbook</AlertTitle>
            <AlertDescription>
              These calculations and UI objects are converted after datasource mappings are approved. Users do not map
              them to physical Databricks columns.
            </AlertDescription>
          </Alert>
          <section className="derived-section">
            <div className="section-heading">
              <h3>KPI calculations</h3>
              <Badge variant="outline">{detail.mappingContract.kpis?.length ?? 0}</Badge>
            </div>
            <div className="derived-list">
              {detail.mappingContract.kpis?.map((kpi) => (
                <details key={`${kpi.legacy_name}-${kpi.legacy_expression}`}>
                  <summary>
                    <strong>{kpi.legacy_name}</strong>
                    <Badge variant="outline">Derived</Badge>
                  </summary>
                  <code>{kpi.legacy_expression}</code>
                  <p>Used in {kpi.assets?.join(', ') || 'workbook'}</p>
                  {kpi.aliases && kpi.aliases.length > 1 ? <p>Aliases: {kpi.aliases.join(', ')}</p> : null}
                </details>
              ))}
            </div>
          </section>
          <section className="derived-section">
            <div className="section-heading">
              <h3>Workbook UI objects</h3>
              <Badge variant="outline">{detail.mappingContract.workbook_helpers?.length ?? 0}</Badge>
            </div>
            <p className="mapping-source-note">
              Parameters, navigation menus, extract replicas, annotations, groups, bins, and clipboard controls are
              preserved or redesigned by the conversion process.
            </p>
            <div className="helper-chip-list">
              {detail.mappingContract.workbook_helpers?.map((helper) => (
                <Badge variant="outline" key={`${helper.name}-${helper.assets?.join('|')}`}>
                  {helper.name}
                </Badge>
              ))}
            </div>
          </section>
        </div>
        </div>
        <section className="mapping-approval-action" hidden={groupStage !== 'build'}>
          <div>
            <strong>{approvalStatus === 'approved' ? 'Mappings approved' : 'Ready to prepare the import'}</strong>
            <p>
              {approvalStatus === 'approved'
                ? 'The approved contract and /importBI context are ready.'
                : `${totalBlockingCount} unresolved field or relationship mappings must be resolved before approval.`}
            </p>
          </div>
          {approvalStatus === 'approved' ? (
            <div className="mapping-draft-action">
              <Button variant="outline" onClick={() => void openImportPackage()}>Open mapping package</Button>
            </div>
          ) : (
            <Button
              onClick={() => void approveMappings()}
              disabled={approvalBusy || totalBlockingCount > 0}
            >
              {approvalBusy
                ? 'Preparing…'
                : approvalStatus === 'mapping-approved'
                  ? 'Prepare import package'
                  : 'Approve mappings and prepare import'}
            </Button>
          )}
        </section>
        {approvalError ? (
          <Alert variant="destructive">
            <AlertCircle className="size-4" />
            <AlertTitle>Approval failed</AlertTitle>
            <AlertDescription>{approvalError}</AlertDescription>
          </Alert>
        ) : null}
        {semanticRunError ? (
          <Alert variant="destructive">
            <AlertCircle className="size-4" />
            <AlertTitle>Workflow failed to start</AlertTitle>
            <AlertDescription>{semanticRunError}</AlertDescription>
          </Alert>
        ) : null}
        {dashboardRunError ? (
          <Alert variant="destructive">
            <AlertCircle className="size-4" />
            <AlertTitle>Dashboard Import Job failed to start</AlertTitle>
            <AlertDescription>{dashboardRunError}</AlertDescription>
          </Alert>
        ) : null}
        <section className="build-assets-stage" hidden={groupStage !== 'build'}>
          <div className="build-stage-intro">
            <h3>Build Databricks assets</h3>
            <p>Run Dashboard Import first. When it succeeds, run Semantic Build to create and validate the Metric View and Genie Agent.</p>
          </div>
          {importPackage?.jobSetup ? (
            <Alert>
              <CircleHelp className="size-4" />
              <AlertTitle>One-time Genie Code task setup</AlertTitle>
              <AlertDescription>
                {importPackage.jobSetup.instructions} Each Job below includes its exact prompts and a direct Job link.
              </AlertDescription>
            </Alert>
          ) : null}
          <section className="workflow-job">
            <div className="workflow-job-heading">
              <div className="workflow-job-title"><span>1</span><div><strong>Dashboard Import</strong><p>Convert this workbook group with `/importBI`.</p></div></div>
              <div className="workflow-job-actions">
                {importPackage?.jobSetup.jobs[0]?.jobUrl ? <a className="job-run-link" href={importPackage.jobSetup.jobs[0].jobUrl ?? undefined} target="_blank" rel="noreferrer">Open Job <ExternalLink aria-hidden="true" /></a> : null}
                {dashboardRun?.runUrl ? <a className="job-run-link" href={dashboardRun.runUrl} target="_blank" rel="noreferrer">View run <ExternalLink aria-hidden="true" /></a> : null}
                <Button onClick={() => void startDashboardImport()} disabled={dashboardRunBusy || approvalStatus !== 'approved'}>
                  {dashboardRunBusy ? 'Starting…' : dashboardRun ? 'Run again' : 'Run Dashboard Import'}
                </Button>
              </div>
            </div>
            {importPackage?.jobSetup.jobs[0]?.tasks.map((task) => <JobPrompt key={task.taskKey} task={task} />)}
            {dashboardRun ? (
              <JobRunSummary run={dashboardRun} runningLabel="Import is running" />
            ) : <p className="workflow-job-empty">Approve the mappings, then run Dashboard Import.</p>}
          </section>
          <section className="workflow-job">
            <div className="workflow-job-heading">
              <div className="workflow-job-title"><span>2</span><div><strong>Semantic Build</strong><p>Create the Metric View, validate it, then create the Genie Agent.</p></div></div>
              <div className="workflow-job-actions">
                {importPackage?.jobSetup.jobs[1]?.jobUrl ? <a className="job-run-link" href={importPackage.jobSetup.jobs[1].jobUrl ?? undefined} target="_blank" rel="noreferrer">Open Job <ExternalLink aria-hidden="true" /></a> : null}
                {semanticRun?.runUrl ? <a className="job-run-link" href={semanticRun.runUrl} target="_blank" rel="noreferrer">View run <ExternalLink aria-hidden="true" /></a> : null}
                <Button onClick={() => void startSemanticWorkflow()} disabled={semanticRunBusy || dashboardRun?.resultState !== 'SUCCESS'}>
                  {semanticRunBusy ? 'Starting…' : semanticRun ? 'Run again' : 'Run Semantic Build'}
                </Button>
              </div>
            </div>
            {importPackage?.jobSetup.jobs[1]?.tasks.map((task) => <JobPrompt key={task.taskKey} task={task} />)}
          {semanticRun ? (
            <JobRunSummary run={semanticRun} runningLabel="Workflow is running" />
          ) : (
            <p className="workflow-job-empty">Complete Dashboard Import successfully to unlock this job.</p>
          )}
          </section>
        </section>
        <section className="build-assets-stage" hidden={groupStage !== 'validate'}>
          <div className="build-stage-intro">
            <h3>Review generated assets</h3>
            <p>Confirm the governed Metric View, Genie Agent, and benchmark evidence before promotion.</p>
          </div>
          {semanticResultsLoading ? <Progress value={65} /> : null}
          {semanticResultsError ? (
            <Alert variant="destructive">
              <AlertCircle className="size-4" />
              <AlertTitle>Results unavailable</AlertTitle>
              <AlertDescription>{semanticResultsError}</AlertDescription>
            </Alert>
          ) : null}
          {semanticResults ? (
            <>
              <div className="semantic-result-grid">
                <section className="workflow-job">
                  <Badge variant="outline">{semanticResults.metricView.status ?? 'UNKNOWN'}</Badge>
                  <h4>Metric View</h4>
                  <code>{semanticResults.metricView.metric_view_fqn ?? semanticResults.manifest.candidate_metric_view_fqn}</code>
                  <p>{semanticResults.metricView.measure_count ?? '—'} measures · {semanticResults.metricView.dimension_count ?? '—'} dimensions</p>
                </section>
                <section className="workflow-job">
                  <Badge variant="outline">{semanticResults.agent.status ?? 'UNKNOWN'}</Badge>
                  <h4>Genie Agent</h4>
                  <strong>{semanticResults.agent.genie_agent?.name}</strong>
                  <p>Space ID: <code>{semanticResults.agent.genie_agent?.space_id}</code></p>
                </section>
                <section className="workflow-job">
                  <Badge variant="outline">{semanticResults.audit.status ?? 'UNKNOWN'}</Badge>
                  <h4>Benchmark evaluation</h4>
                  <strong>{semanticResults.agent.benchmark_summary?.num_correct ?? 0} / {semanticResults.agent.benchmark_summary?.num_questions ?? semanticResults.agent.benchmark_configuration?.length ?? 0} correct</strong>
                  <p>{semanticResults.agent.benchmark_summary?.num_needs_review ?? 0} need review · {semanticResults.agent.benchmark_summary?.num_bad ?? 0} failed</p>
                </section>
              </div>
              {(semanticResults.audit.warnings?.length || semanticResults.agent.exceptions?.length) ? (
                <section className="workflow-job">
                  <h4>Review findings</h4>
                  <ul>
                    {semanticResults.audit.warnings?.map((warning) => <li key={warning}>{warning}</li>)}
                    {semanticResults.agent.exceptions?.map((exception) => <li key={exception.id ?? exception.detail}>{exception.id ? `${exception.id}: ` : ''}{exception.detail}</li>)}
                  </ul>
                </section>
              ) : null}
              <div className="workflow-job-actions">
                <Button variant="outline" onClick={() => void loadSemanticResults()}>Refresh results</Button>
                <Button onClick={() => setGroupStage('promote')}>Continue to promotion</Button>
              </div>
            </>
          ) : null}
        </section>
        <section className="build-assets-stage" hidden={groupStage !== 'promote'}>
          <div className="build-stage-intro">
            <h3>Promotion decision</h3>
            <p>Accept the generated assets as final, or request stable production names for a later rename workflow.</p>
          </div>
          <section className="workflow-job promotion-form">
            <label>
              <span>Final Metric View FQN</span>
              <input value={finalMetricViewFqn} onChange={(event) => setFinalMetricViewFqn(event.target.value)} />
            </label>
            <label>
              <span>Final Genie Agent name</span>
              <input value={finalAgentName} onChange={(event) => setFinalAgentName(event.target.value)} />
            </label>
            <label>
              <span>Review notes</span>
              <textarea value={promotionNotes} onChange={(event) => setPromotionNotes(event.target.value)} rows={4} />
            </label>
            <Alert>
              <CircleHelp className="size-4" />
              <AlertTitle>Promotion behavior</AlertTitle>
              <AlertDescription>
                Keeping the current names accepts the created assets as final. Different names create an approved pending rename request; this step does not silently copy or rename governed assets.
              </AlertDescription>
            </Alert>
            <div className="workflow-job-actions">
              <Button onClick={() => void savePromotion()} disabled={promotionBusy || !finalMetricViewFqn || !finalAgentName}>
                {promotionBusy ? 'Saving…' : 'Save promotion decision'}
              </Button>
            </div>
            {semanticResults?.promotion ? (
              <Alert>
                <CheckCircle2 className="size-4" />
                <AlertTitle>{semanticResults.promotion.status}</AlertTitle>
                <AlertDescription>
                  Saved by {semanticResults.promotion.approved_by} at {semanticResults.promotion.approved_at}.
                </AlertDescription>
              </Alert>
            ) : null}
          </section>
        </section>
        <Dialog open={importPackageOpen} onOpenChange={setImportPackageOpen}>
          <DialogContent className="mapping-preview-dialog mapping-package-dialog">
            <DialogHeader>
              <DialogTitle>Prepared Genie Code package</DialogTitle>
              <DialogDescription>Copy the executable Job prompt. Rendered Volume prompts are read-only references.</DialogDescription>
            </DialogHeader>
            <div className="import-package-content">
              <p className="package-setup-note">{importPackage?.jobSetup.instructions}</p>
              <section className="package-step">
                <div className="package-step__heading">
                  <div><span>1</span><h3>Dashboard migration</h3></div>
                  {importPackage?.jobSetup.jobs[0]?.jobUrl ? <a className="job-run-link" href={importPackage.jobSetup.jobs[0].jobUrl ?? undefined} target="_blank" rel="noreferrer">Open Dashboard Import Job <ExternalLink aria-hidden="true" /></a> : null}
                </div>
                {importPackage?.jobSetup.jobs[0]?.tasks.map((task) => <JobPrompt key={task.taskKey} task={task} />)}
                <ReferencePrompt
                  label="Rendered dashboard reference"
                  path={importPackage?.session1PromptPath}
                  prompt={importPackage?.prompt}
                />
              </section>
              <section className="package-step">
                <div className="package-step__heading">
                  <div><span>2</span><h3>Metric View</h3></div>
                  {importPackage?.jobSetup.jobs[1]?.jobUrl ? <a className="job-run-link" href={importPackage.jobSetup.jobs[1].jobUrl ?? undefined} target="_blank" rel="noreferrer">Open Semantic Build Job <ExternalLink aria-hidden="true" /></a> : null}
                </div>
                {importPackage?.jobSetup.jobs[1]?.tasks.filter((task) => task.taskKey === 'build_metric_view').map((task) => <JobPrompt key={task.taskKey} task={task} />)}
                <ReferencePrompt
                  label="Rendered Metric View reference"
                  path={importPackage?.metricViewPromptPath}
                  prompt={importPackage?.metricViewPrompt}
                />
              </section>
              <section className="package-step">
                <div className="package-step__heading">
                  <div><span>3</span><h3>Genie Agent</h3></div>
                  {importPackage?.jobSetup.jobs[1]?.jobUrl ? <a className="job-run-link" href={importPackage.jobSetup.jobs[1].jobUrl ?? undefined} target="_blank" rel="noreferrer">Open Semantic Build Job <ExternalLink aria-hidden="true" /></a> : null}
                </div>
                {importPackage?.jobSetup.jobs[1]?.tasks.filter((task) => task.taskKey === 'build_genie_agent').map((task) => <JobPrompt key={task.taskKey} task={task} />)}
                <ReferencePrompt
                  label="Rendered Genie Agent reference"
                  path={importPackage?.genieAgentPromptPath}
                  prompt={importPackage?.genieAgentPrompt}
                />
              </section>
              <section className="package-contract">
                <h3>Approved mapping contract</h3>
                <details className="job-prompt">
                  <summary><span>{importPackage?.mappingFileName}</span><Badge variant="outline">YAML</Badge></summary>
                  <div className="job-prompt__content">
                    <pre>{importPackage?.contractYaml}</pre>
                    <div className="mapping-draft-action">
                      <CopyButton value={importPackage?.contractYaml ?? ''} label="Copy YAML" />
                      <Button size="sm" onClick={downloadContract}>Download YAML</Button>
                    </div>
                  </div>
                </details>
              </section>
            </div>
            <DialogFooter>
              <Button onClick={downloadContract}>Download YAML</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </CardContent>
    </Card>
  );
}

function JobPrompt({ task }: { task: { taskKey: string; prompt: string } }) {
  return (
    <details className="job-prompt">
      <summary>
        <span>Genie Code prompt</span>
        <Badge variant="outline">{task.taskKey.replaceAll('_', ' ')}</Badge>
      </summary>
      <div className="job-prompt__content">
        <pre>{task.prompt}</pre>
        <CopyButton value={task.prompt} label="Copy prompt" />
      </div>
    </details>
  );
}

function ReferencePrompt({ label, path, prompt }: { label: string; path?: string; prompt?: string }) {
  if (!path || !prompt) return null;
  return (
    <details className="job-prompt">
      <summary>
        <span>{label}</span>
        <Badge variant="outline">Read only</Badge>
      </summary>
      <div className="job-prompt__content">
        <p>{path}</p>
        <pre>{prompt}</pre>
      </div>
    </details>
  );
}

function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  };

  return (
    <Button variant="outline" size="sm" onClick={() => void copy()} disabled={!value}>
      {copied ? <CheckCircle2 aria-hidden="true" /> : <Copy aria-hidden="true" />}
      {copied ? 'Copied' : label}
    </Button>
  );
}

function JobRunSummary({ run, runningLabel }: { run: SemanticWorkflowRun; runningLabel: string }) {
  const completedTasks = (run.tasks ?? []).filter((task) =>
    ['TERMINATED', 'SKIPPED'].includes(task.lifeCycleState)
  ).length;
  const progress = run.tasks?.length ? Math.round((completedTasks / run.tasks.length) * 100) : 0;
  return (
    <div className="semantic-run-summary">
      <div>
        <strong>{run.lifeCycleState ?? 'PENDING'}</strong>
        <span>{run.resultState || runningLabel} · Run {run.databricksRunId}</span>
      </div>
      <Progress value={progress} />
      <p className="job-run-detail-note">Open the Job run to inspect task order, logs, retries, and failures.</p>
    </div>
  );
}

function MappingGraph({
  fields,
  relationships,
}: {
  fields: GroupDetail['mappingContract']['fields'];
  relationships: NonNullable<GroupDetail['mappingContract']['relationships']>;
}) {
  const sourceTables = Array.from(new Set(fields.map((field) => field.source_table || field.datasource))).sort();
  const targetTables = Array.from(new Set(fields.map((field) => field.target_table).filter(Boolean) as string[])).sort();
  const height = Math.max(260, Math.max(sourceTables.length, targetTables.length) * 76 + 70);
  const sourceY = new Map(sourceTables.map((table, index) => [table, 60 + index * 76]));
  const targetY = new Map(targetTables.map((table, index) => [table, 60 + index * 76]));
  const mappingEdges = new Map<string, { source: string; target: string; count: number; unresolved: boolean }>();
  for (const field of fields) {
    if (!field.target_table) continue;
    const source = field.source_table || field.datasource;
    const key = `${source}\u0000${field.target_table}`;
    const edge = mappingEdges.get(key) ?? { source, target: field.target_table, count: 0, unresolved: false };
    edge.count += 1;
    edge.unresolved ||= field.status === 'unresolved';
    mappingEdges.set(key, edge);
  }
  const shortName = (value: string) => value.split('.').at(-1) ?? value;
  return (
    <div className="mapping-graph" role="img" aria-label="Source-to-Databricks mapping graph">
      <svg viewBox={`0 0 1000 ${height}`} preserveAspectRatio="xMinYMin meet">
        <text className="mapping-graph__column-title" x="40" y="28">Source</text>
        <text className="mapping-graph__column-title" x="700" y="28">Databricks target</text>
        {Array.from(mappingEdges.values()).map((edge) => {
          const startY = (sourceY.get(edge.source) ?? 0) + 23;
          const endY = (targetY.get(edge.target) ?? 0) + 23;
          return (
            <g key={`${edge.source}-${edge.target}`}>
              <path className={edge.unresolved ? 'mapping-graph__edge mapping-graph__edge--unresolved' : 'mapping-graph__edge'} d={`M 280 ${startY} C 430 ${startY}, 560 ${endY}, 700 ${endY}`} />
              <text className="mapping-graph__edge-label" x="490" y={(startY + endY) / 2 - 4}>{edge.count} fields</text>
            </g>
          );
        })}
        {relationships.flatMap((relationship, index) => {
          const left = relationship.target.left_table_candidates.length === 1 ? relationship.target.left_table_candidates[0] : '';
          const right = relationship.target.right_table_candidates.length === 1 ? relationship.target.right_table_candidates[0] : '';
          if (!targetY.has(left) || !targetY.has(right)) return [];
          const leftY = (targetY.get(left) ?? 0) + 46;
          const rightY = targetY.get(right) ?? 0;
          return [<path key={`relationship-${index}`} className={`mapping-graph__relationship mapping-graph__relationship--${relationship.status}`} d={`M 940 ${leftY} C 980 ${leftY}, 980 ${rightY}, 940 ${rightY}`}><title>{relationship.target.condition}</title></path>];
        })}
        {sourceTables.map((table) => (
          <g key={table} transform={`translate(40 ${sourceY.get(table)})`}>
            <rect className="mapping-graph__node mapping-graph__node--source" width="240" height="46" rx="6" />
            <text x="12" y="28"><title>{table}</title>{shortName(table)}</text>
          </g>
        ))}
        {targetTables.map((table) => (
          <g key={table} transform={`translate(700 ${targetY.get(table)})`}>
            <rect className="mapping-graph__node mapping-graph__node--target" width="240" height="46" rx="6" />
            <text x="12" y="28"><title>{table}</title>{shortName(table)}</text>
          </g>
        ))}
      </svg>
      <div className="mapping-graph__legend"><span>Field mapping</span><span>Target relationship</span><span>Red requires review</span></div>
    </div>
  );
}

function RelationshipEditor({
  relationship,
  relationshipIndex,
  group,
  targetTables,
  saved,
  onSaved,
}: {
  relationship: NonNullable<GroupDetail['mappingContract']['relationships']>[number];
  relationshipIndex: number;
  group: GroupSummary;
  targetTables: string[];
  saved: boolean;
  onSaved: () => void;
}) {
  const [leftTable, setLeftTable] = useState(relationship.target.left_table_candidates.length === 1 ? relationship.target.left_table_candidates[0] : '');
  const [rightTable, setRightTable] = useState(relationship.target.right_table_candidates.length === 1 ? relationship.target.right_table_candidates[0] : '');
  const [joinType, setJoinType] = useState(relationship.target.join_type || 'left');
  const [condition, setCondition] = useState(relationship.target.condition || '');
  const [cardinality, setCardinality] = useState(relationship.target.cardinality || 'unknown');
  const [temporalPredicates, setTemporalPredicates] = useState(relationship.target.temporal_predicates.join('\n'));
  const [recordFilters, setRecordFilters] = useState(relationship.target.record_filters.join('\n'));
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'error'>('idle');
  const save = async () => {
    setSaveState('saving');
    const response = await fetch(`/api/groups/${group.group_id}/relationships/draft`, {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        corpusId: group.corpus_id,
        relationshipIndex,
        leftTable,
        rightTable,
        joinType,
        condition,
        cardinality,
        temporalPredicates: temporalPredicates.split('\n').map((value) => value.trim()).filter(Boolean),
        recordFilters: recordFilters.split('\n').map((value) => value.trim()).filter(Boolean),
      }),
    });
    if (!response.ok) {
      setSaveState('error');
      return;
    }
    setSaveState('idle');
    onSaved();
  };
  return (
    <article className={`relationship-card relationship-card--${saved ? 'proposed' : relationship.status}`}>
      <div className="relationship-card__header">
        <div><h3>{relationship.source.left_table || 'Source table'} → {relationship.source.right_table}</h3><p>{relationship.source.condition || 'Source join condition unavailable'}</p></div>
        <Badge variant="outline">{saved ? 'Updated' : relationship.status}</Badge>
      </div>
      <div className="relationship-editor-grid">
        <label>Left Databricks table<select value={leftTable} onChange={(event) => setLeftTable(event.target.value)}><option value="">Select table</option>{targetTables.map((table) => <option key={table}>{table}</option>)}</select></label>
        <label>Right Databricks table<select value={rightTable} onChange={(event) => setRightTable(event.target.value)}><option value="">Select table</option>{targetTables.map((table) => <option key={table}>{table}</option>)}</select></label>
        <label>Join type<select value={joinType} onChange={(event) => setJoinType(event.target.value)}>{['inner', 'left', 'right', 'full', 'relationship'].map((value) => <option key={value}>{value}</option>)}</select></label>
        <label>Grain / cardinality<select value={cardinality} onChange={(event) => setCardinality(event.target.value)}>{['one_to_one', 'one_to_many', 'many_to_one', 'many_to_many', 'unknown'].map((value) => <option key={value}>{value}</option>)}</select></label>
        <label className="relationship-editor-grid__wide">Target join condition<input value={condition} onChange={(event) => setCondition(event.target.value)} /></label>
        <label className="relationship-editor-grid__wide">Temporal predicates<textarea value={temporalPredicates} onChange={(event) => setTemporalPredicates(event.target.value)} placeholder="One predicate per line" /></label>
        <label className="relationship-editor-grid__wide">Current-record filters<textarea value={recordFilters} onChange={(event) => setRecordFilters(event.target.value)} placeholder="One filter per line" /></label>
      </div>
      <div className="relationship-card__actions"><Button size="sm" onClick={() => void save()} disabled={!leftTable || !rightTable || !condition || cardinality === 'unknown' || saveState === 'saving'}>{saveState === 'saving' ? 'Applying…' : 'Apply relationship'}</Button>{cardinality === 'unknown' ? <span>Choose the target grain/cardinality to continue.</span> : null}{saveState === 'error' ? <span>Update failed</span> : null}</div>
    </article>
  );
}

function MappingEditorCard({
  field,
  group,
  targets,
  status,
  onSaved,
  usageLabel,
}: {
  field: GroupDetail['mappingContract']['fields'][number];
  group: GroupSummary;
  targets: DatabricksTargets | null;
  status: MappingStatus;
  onSaved: () => void;
  usageLabel: string;
}) {
  const initialTable = targets?.tables.some((table) => table.fullName === field.target_table)
    ? (field.target_table ?? '')
    : '';
  const [targetTable, setTargetTable] = useState(initialTable);
  const [targetExpression, setTargetExpression] = useState(initialTable ? (field.target_expression ?? '') : '');
  const [conversion, setConversion] = useState(field.conversion ?? 'direct');
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [hasChanges, setHasChanges] = useState(false);
  const selectedTable = targets?.tables.find((table) => table.fullName === targetTable);
  const grainNeedsReview = Boolean(
    field.source_grain &&
      field.target_grain &&
      field.source_grain.trim().toLowerCase() !== field.target_grain.trim().toLowerCase()
  );

  const saveMapping = async () => {
    setSaveState('saving');
    const response = await fetch(`/api/groups/${group.group_id}/mappings/draft`, {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        corpusId: group.corpus_id,
        datasource: field.datasource,
        legacy: field.legacy,
        targetTable,
        targetExpression,
        conversion,
      }),
    });
    setSaveState(response.ok ? 'saved' : 'error');
    if (response.ok) {
      setHasChanges(false);
      onSaved();
    }
  };

  return (
    <article className={`mapping-card mapping-card--${status}`}>
      <div className="mapping-card__header">
        <div>
          <h4>{field.legacy}</h4>
          <p>
            Source: {field.source_table || 'Embedded datasource'} · Used in {usageLabel} · {field.datatype}
          </p>
        </div>
        <Badge className={`mapping-status-badge mapping-status-badge--${status}`} variant="outline">
          {saveState === 'error' ? 'Save failed' : mappingStatusLabels[saveState === 'saved' ? 'draft' : status]}
        </Badge>
      </div>
      <div className="mapping-card__target">
        <label>
          Databricks table
          <select
            aria-label={`Databricks table for ${field.legacy}`}
            value={targetTable}
            onChange={(event) => {
              setTargetTable(event.target.value);
              setTargetExpression('');
              setSaveState('idle');
              setHasChanges(true);
            }}
          >
            <option value="">Select table</option>
            {targets?.tables.map((table) => (
              <option value={table.fullName} key={table.fullName}>
                {table.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {conversion === 'calculated' ? 'SQL expression' : 'Databricks field'}
          {conversion === 'calculated' ? (
            <input
              aria-label={`Databricks expression for ${field.legacy}`}
              placeholder="Enter SQL expression"
              value={targetExpression}
              onChange={(event) => {
                setTargetExpression(event.target.value);
                setSaveState('idle');
                setHasChanges(true);
              }}
            />
          ) : (
            <select
              aria-label={`Databricks field for ${field.legacy}`}
              value={targetExpression}
              onChange={(event) => {
                setTargetExpression(event.target.value);
                setSaveState('idle');
                setHasChanges(true);
              }}
              disabled={!selectedTable}
            >
              <option value="">Select field</option>
              {selectedTable?.columns.map((column) => (
                <option value={column.name} key={column.name}>
                  {column.name} · {column.type}
                </option>
              ))}
            </select>
          )}
        </label>
      </div>
      {field.source_grain || field.target_grain ? (
        <div className={`mapping-grain${grainNeedsReview ? ' mapping-grain--review' : ''}`}>
          <span>
            Source grain: {field.source_grain || 'Not provided'} · Target grain: {field.target_grain || 'Not declared'}
          </span>
          {grainNeedsReview ? (
            <InfoTooltip
              label="Grain review required"
              content="The source and target describe different row-level detail. Confirm the required aggregation, allocation, join, or temporal rule before approval."
            />
          ) : null}
        </div>
      ) : null}
      {status === 'unavailable' ? (
        <p className="mapping-warning">
          Imported target not found: {field.target_table}.{field.target_expression}
        </p>
      ) : null}
      {targetTable ? <span className="selected-target-name">{targetTable}</span> : null}
      <div className="mapping-card__footer">
        <label>
          Mapping type
          <select
            className="mapping-type-select"
            value={conversion}
            aria-label={`Mapping type for ${field.legacy}`}
            onChange={(event) => {
              setConversion(event.target.value);
              setSaveState('idle');
              setHasChanges(true);
            }}
          >
            {['direct', 'renamed', 'calculated', 'joined', 'temporal', 'skipped', 'redesign'].map((value) => (
              <option value={value} key={value}>
                {value.charAt(0).toUpperCase() + value.slice(1)}
              </option>
            ))}
          </select>
        </label>
        {hasChanges || saveState === 'error' ? (
          <div className="mapping-draft-action">
            <Button
              size="sm"
              variant="outline"
              onClick={() => void saveMapping()}
              disabled={!targetTable || !targetExpression || saveState === 'saving'}
            >
              {saveState === 'saving' ? 'Applying…' : saveState === 'error' ? 'Retry update' : 'Apply change'}
            </Button>
            <InfoTooltip
              label="Apply change"
              content="Updates this field mapping. Imported mappings require no action unless you change them."
            />
          </div>
        ) : null}
      </div>
    </article>
  );
}

function LoadingState() {
  return (
    <div className="loading-grid" aria-label="Loading migration review">
      <div className="summary-band">
        {['assets', 'groups', 'mapped', 'quarantined'].map((key) => (
          <Skeleton key={key} className="h-28" />
        ))}
      </div>
      <div className="grid gap-6 xl:grid-cols-2">
        <Skeleton className="h-[32rem]" />
        <Skeleton className="h-[32rem]" />
      </div>
    </div>
  );
}

function DetailLoadingState() {
  return (
    <Card>
      <CardContent className="space-y-4 pt-6" aria-label="Loading semantic group">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-24" />
        <Skeleton className="h-48" />
      </CardContent>
    </Card>
  );
}

function EmptyMessage({ title, description }: { title: string; description: string }) {
  return (
    <Empty>
      <EmptyHeader>
        <EmptyTitle>{title}</EmptyTitle>
        <EmptyDescription>{description}</EmptyDescription>
      </EmptyHeader>
    </Empty>
  );
}

function InfoTooltip({ label, content }: { label: string; content: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button className="info-tooltip" type="button" aria-label={`Explain ${label}`}>
          <CircleHelp className="size-4" aria-hidden="true" />
        </button>
      </TooltipTrigger>
      <TooltipContent className="tooltip-content">{content}</TooltipContent>
    </Tooltip>
  );
}

