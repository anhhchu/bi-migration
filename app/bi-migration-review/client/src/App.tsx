import { useEffect, useMemo, useRef, useState } from 'react';
import { DocsDialog, type AppDocument } from './DocsDialog';
import { HomePage } from './HomePage';
import { DASHBOARD_MIGRATION_ENABLED } from '@/lib/features';
import { statusLabel, statusTone } from '@/lib/status';
import { catalogExplorerUrl } from '@/lib/catalog-links';
import { isOneOf, isString, readPersistedValue, usePersistentState, writePersistedValue } from '@/lib/persistent-state';
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
  FileText,
  FileUp,
  FileWarning,
  FolderSearch,
  Layers3,
  Play,
  UserRound,
  Wrench,
} from 'lucide-react';

type MigrationMode = 'semantic_model' | 'dashboard';

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
  migrationMode: MigrationMode;
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

type SemanticRunGroup = {
  group_id: string;
  display_name: string;
  group_path: string;
  report_path?: string;
  candidate_metric_view_fqn?: string;
  status: string;
  readiness?: string | null;
  gateStatus?: string | null;
  migrationStatus?: string | null;
};

const MIGRATION_RUNNING_STATUSES = new Set(['MIGRATION_RUNNING', 'MIGRATION_SUBMITTED']);

/** Status shown for one group: its gate result once evaluated, otherwise where it is in the workflow. */
function groupDisplayStatus(group: SemanticRunGroup, runStatus: string | undefined): string {
  if (group.gateStatus || group.readiness) return group.gateStatus ?? group.readiness ?? group.status;
  if (runStatus && MIGRATION_RUNNING_STATUSES.has(runStatus)) return 'MIGRATION_IN_PROGRESS';
  if (runStatus && !PENDING_APPROVAL_STATUSES.has(runStatus)) return 'NO_RESULT';
  return group.status;
}

type SemanticRun = {
  runId: string;
  approval?: {
    approvedBy?: string | null;
    approvedAt?: string | null;
    migrationRunId?: string | null;
    migrationRunUrl?: string | null;
  } | null;
  manifestStatus?: string | null;
  supersededBy?: string | null;
  runFolder: string;
  runPath: string;
  createdAt?: string | null;
  inputVolumePath?: string | null;
  status: string;
  headline: string;
  totals: Record<string, number>;
  groups: SemanticRunGroup[];
  reportPath: string;
};

type SemanticRunsResponse = {
  root: string;
  runs: SemanticRun[];
  error?: string;
  detail?: string;
};

type GateStage = {
  key: string;
  label: string;
  status: 'PASS' | 'WARN' | 'FAIL' | 'NOT_RUN';
  summary: string;
  next_step?: string | null;
  measures?: Array<{ name: string; additivity: string; basis: string; expression: string }>;
  tables?: Array<{ table: string; grain?: string | null }>;
};

type ActionItem = {
  title: string;
  detail: string;
  what_to_do: string;
  blocking: boolean;
  expression?: string | null;
  names?: string[];
};

type ActionGroups = {
  groups: Array<{
    category: string;
    label: string;
    owner: string;
    why_human: string;
    blocking: boolean;
    items: ActionItem[];
  }>;
  automatic: Array<{ title: string; detail: string; names?: string[] }>;
  blocking_count: number;
  review_count: number;
};

function ActionGroupsView({ actionGroups }: { actionGroups: ActionGroups }) {
  return (
    <div className="action-groups">
      <p className="action-groups__summary">
        {actionGroups.blocking_count} blocking · {actionGroups.review_count} to review
      </p>
      {actionGroups.groups.map((group) => (
        <section
          key={group.category}
          className={group.blocking ? 'action-group action-group--blocking' : 'action-group'}
        >
          <header>
            <h4>
              {group.label}
              <span className="action-group__count">
                {group.items.reduce((total, item) => total + (item.names?.length ?? 1), 0)}
              </span>
            </h4>
            <span className="action-group__owner">{group.owner}</span>
          </header>
          <p className="action-group__why">
            <strong>Who:</strong> {group.owner}. <strong>Why a person is needed:</strong> {group.why_human}
          </p>
          <ul>
            {group.items.map((item) => (
              <li key={item.title}>
                <div className="action-group__title">
                  <span>{item.title}</span>
                  {item.blocking ? <StatusBadge status="BLOCKING" /> : null}
                </div>
                {(item.names?.length ?? 0) > 1 ? (
                  <div className="action-names">
                    {item.names?.map((name) => (
                      <span key={name}>{name}</span>
                    ))}
                  </div>
                ) : null}
                <p>{item.detail}</p>
                {item.expression ? <code className="action-expression">{item.expression}</code> : null}
                <small>What to do: {item.what_to_do}</small>
              </li>
            ))}
          </ul>
        </section>
      ))}
      {actionGroups.automatic.length ? (
        <details className="action-automatic">
          <summary>Handled automatically · {actionGroups.automatic.length} (no action needed)</summary>
          <ul>
            {actionGroups.automatic.map((item) => (
              <li key={item.detail}>
                <strong>{item.title}</strong>: {item.detail}
                {(item.names?.length ?? 0) > 1 ? (
                  <div className="action-names">
                    {item.names?.map((name) => (
                      <span key={name}>{name}</span>
                    ))}
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

type ReleaseGate = { status: string; headline: string; next_step?: string | null; stages: GateStage[] };

const GATE_STAGE_TEXT: Record<GateStage['status'], string> = {
  PASS: 'Pass',
  WARN: 'Review',
  FAIL: 'Fix',
  NOT_RUN: 'Not run',
};

function ReleaseGateCard({ gate }: { gate: ReleaseGate }) {
  const contract = gate.stages.find((stage) => stage.key === 'contract');
  return (
    <Card className="workspace-card release-gate-card">
      <CardHeader>
        <div className="review-card-heading">
          <CardTitle>Release gate</CardTitle>
          <StatusBadge status={gate.status} />
        </div>
      </CardHeader>
      <CardContent className="semantic-review-section">
        <div className="run-next-step">
          <strong>{gate.headline}</strong>
          {gate.next_step ? <p>Next step: {gate.next_step}</p> : null}
        </div>
        <ol className="gate-stages">
          {gate.stages.map((stage) => (
            <li key={stage.key} className={`gate-stage gate-stage--${stage.status.toLowerCase()}`}>
              <span className="gate-stage__marker" aria-hidden="true" />
              <div>
                <div className="gate-stage__title">
                  <strong>{stage.label}</strong>
                  <span className="gate-stage__status">{GATE_STAGE_TEXT[stage.status]}</span>
                </div>
                <p>{stage.summary}</p>
                {stage.next_step && stage.status !== 'PASS' ? <small>Next: {stage.next_step}</small> : null}
              </div>
            </li>
          ))}
        </ol>
        {contract?.measures?.length ? (
          <details className="gate-contract">
            <summary>Contract details: grain and measure additivity (inferred)</summary>
            {contract.tables?.length ? (
              <ul>
                {contract.tables.map((table) => (
                  <li key={table.table}>
                    <code>{table.table}</code>: {table.grain ?? 'grain not recorded'}
                  </li>
                ))}
              </ul>
            ) : null}
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Measure</TableHead>
                  <TableHead>Additivity</TableHead>
                  <TableHead>Why</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {contract.measures.map((measure) => (
                  <TableRow key={measure.name}>
                    <TableCell>{measure.name}</TableCell>
                    <TableCell>{measure.additivity.replaceAll('_', '-')}</TableCell>
                    <TableCell>{measure.basis}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </details>
        ) : null}
      </CardContent>
    </Card>
  );
}

type SemanticGroupReview = {
  group: SemanticRunGroup;
  sourceSummary?: {
    grouping_rationale?: string;
    datasource_count?: number;
    target_tables?: string[];
    datasources?: Array<{ datasource_name?: string; source_path?: string }>;
    supporting_datasources?: Array<{ datasource_name?: string; source_path?: string }>;
  } | null;
  migrationReview?: {
    status?: string;
    readiness?: string;
    headline?: string;
    gate?: ReleaseGate;
    action_groups?: ActionGroups;
    candidate?: { metric_view_fqn?: string };
    coverage?: {
      semantic_coverage_percent?: number;
      dimensions_created?: number;
      measures_created?: number;
      business_items_not_translated?: number;
    };
    recommended_actions?: Array<{
      priority?: string;
      title?: string;
      description?: string;
      items?: string[];
      details?: Array<{ name: string; expression: string }>;
      how_to_fix?: string;
    }>;
  } | null;
  repairReview?: {
    status?: string;
    readiness?: string;
    headline?: string;
    attempt?: number;
    rolled_back?: boolean;
    decision_reasons?: string[];
    coverage_gates?: Array<{
      key?: string;
      label?: string;
      definition?: string;
      before?: number;
      after?: number;
      threshold?: number;
      passed?: boolean;
      gap_count?: number;
    }>;
    blocking_findings?: Array<{
      source_name?: string;
      status?: string;
      recommended_action?: string;
      failure_details?: Array<{ code?: string; meaning?: string; action?: string }>;
      target?: { expr?: string } | null;
      query_detail?: { status?: string; reason?: string };
    }>;
  } | null;
  reports?: {
    migrationReviewHtml?: string | null;
    repairReviewHtml?: string | null;
  };
  artifacts: Record<string, string>;
  error?: string;
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
  dashboardSummary: {
    status?: string;
    dashboards?: Array<{ dashboard_id?: string; display_name?: string; workbook_name?: string; url?: string | null }>;
    findings?: Array<{
      severity?: string;
      type?: string;
      detail?: string;
      resolution?: string;
      workbook_name?: string;
    }>;
  };
  metricView: { status?: string; metric_view_fqn?: string; dimension_count?: number; measure_count?: number };
  metricExceptions?: {
    exceptions?: Array<{ id?: string; severity?: string; type?: string; detail?: string; resolution?: string }>;
  };
  agent: {
    status?: string;
    genie_agent?: { name?: string; space_id?: string; url_path?: string };
    benchmark_configuration?: Array<{ benchmark_key?: string; question?: string }>;
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
  links?: { metricView?: string | null; genieAgent?: string | null };
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

const PENDING_APPROVAL_STATUSES = new Set(['GROUPING_REVIEW_REQUIRED', 'AWAITING_APPROVAL']);

let workspaceUrlRequest: Promise<string | null> | null = null;

/** Workspace address for deep links, fetched once per page load. */
function useWorkspaceUrl() {
  const [workspaceUrl, setWorkspaceUrl] = useState<string | null>(null);
  useEffect(() => {
    workspaceUrlRequest ??= fetch('/api/session')
      .then((response) => response.json() as Promise<{ workspaceUrl?: string | null }>)
      .then((payload) => payload.workspaceUrl ?? null)
      .catch(() => null);
    void workspaceUrlRequest.then(setWorkspaceUrl);
  }, []);
  return workspaceUrl;
}

/** A Metric View name with a Catalog Explorer link once the view exists. */
function MetricViewName({ fullName, exists = true }: { fullName?: string | null; exists?: boolean }) {
  const workspaceUrl = useWorkspaceUrl();
  const href = exists ? catalogExplorerUrl(workspaceUrl, fullName) : null;
  return (
    <div className="metric-view-name">
      <code>{fullName ?? 'Not created'}</code>
      {href ? (
        <a className="job-run-link" href={href} target="_blank" rel="noreferrer">
          Open in Catalog Explorer <ExternalLink aria-hidden="true" />
        </a>
      ) : null}
    </div>
  );
}

export default function App() {
  const [view, setView] = useState<'home' | 'upload' | 'review' | 'semantic' | 'runs'>(() => {
    const requestedView = new URLSearchParams(window.location.search).get('view');
    return requestedView === 'upload' ||
      requestedView === 'review' ||
      requestedView === 'semantic' ||
      requestedView === 'runs'
      ? requestedView
      : 'home';
  });
  const [migrationMode, setMigrationMode] = usePersistentState<MigrationMode>(
    'migration-mode',
    'semantic_model',
    isOneOf(['semantic_model', 'dashboard'] as const)
  );
  useEffect(() => {
    const requestedMode = new URLSearchParams(window.location.search).get('mode');
    if (requestedMode === 'dashboard' || requestedMode === 'semantic_model') setMigrationMode(requestedMode);
  }, []);
  useEffect(() => {
    // Dashboard migration is temporarily hidden; never leave a saved or linked dashboard mode active.
    if (!DASHBOARD_MIGRATION_ENABLED && migrationMode === 'dashboard') setMigrationMode('semantic_model');
  }, [migrationMode]);
  const [semanticRunStatus, setSemanticRunStatus] = useState<string | null>(null);
  // Which run the run browser should select when a step is opened (nonce re-applies the same request).
  const [runFocus, setRunFocus] = useState<RunFocus>({ nonce: 0 });
  // The step a user opened decides what is shown; run status only marks steps as done.
  const [semanticStepView, setSemanticStepView] = useState<2 | 3>(2);
  const semanticStep = view === 'upload' ? 1 : semanticStepView;
  const selectedRunApproved = Boolean(semanticRunStatus && !PENDING_APPROVAL_STATUSES.has(semanticRunStatus));
  const previousRunStatus = useRef<string | null>(null);
  useEffect(() => {
    // Approving moves the user forward once; they can still go back to step 2.
    if (semanticRunStatus === 'MIGRATION_SUBMITTED' && previousRunStatus.current !== 'MIGRATION_SUBMITTED') {
      setSemanticStepView(3);
    }
    previousRunStatus.current = semanticRunStatus;
  }, [semanticRunStatus]);
  const pageIntro =
    view === 'runs'
      ? {
          title: 'Previous semantic migrations',
          description: 'Reopen any run, select a semantic group, and review migration and repair evidence.',
        }
      : migrationMode !== 'semantic_model'
        ? {
            title: 'Migrate Tableau dashboards',
            description: 'Inventory workbooks, approve mappings, and create AI/BI dashboards with traceable approvals.',
          }
        : semanticStep === 1
          ? {
              title: 'Propose semantic groups',
              description:
                'Provide Tableau datasources and a table mapping. The workflow groups them into semantic domains for your review; nothing is created yet.',
            }
          : semanticStep === 2
            ? {
                title: 'Approve and migrate',
                description:
                  'Check each proposed group, then approve. Approval starts one candidate Metric View build per group.',
              }
            : {
                title: 'Review Metric Views',
                description: 'Inspect each candidate Metric View, its evaluation gates, and automatic repair results.',
              };
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
  const [openDocument, setOpenDocument] = useState<AppDocument | null>(null);

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
              <button type="button" className="header-doc-link" onClick={() => setOpenDocument('installation-guide')}>
                Installation guide
              </button>
              <button type="button" className="header-doc-link" onClick={() => setOpenDocument('mapping-guide')}>
                Mapping guide
              </button>
              <div className="header-user" title={sessionUser?.userName || sessionUser?.displayName}>
                <UserRound className="size-4" aria-hidden="true" />
                <span>{sessionUser?.displayName || 'Loading user…'}</span>
              </div>
            </div>
          </div>
        </header>

        <nav className="app-primary-nav" aria-label="Application sections">
          <div className="app-primary-nav__inner">
            <button
              type="button"
              className={view === 'home' ? 'app-primary-tab app-primary-tab--active' : 'app-primary-tab'}
              onClick={() => {
                setMappingOpen(false);
                setView('home');
              }}
            >
              Home
            </button>
            <button
              type="button"
              className={
                view !== 'runs' && view !== 'home' ? 'app-primary-tab app-primary-tab--active' : 'app-primary-tab'
              }
              onClick={() =>
                setView(migrationMode === 'semantic_model' ? 'upload' : review?.groups.length ? 'review' : 'upload')
              }
            >
              Migration
            </button>
            <button
              type="button"
              className={view === 'runs' ? 'app-primary-tab app-primary-tab--active' : 'app-primary-tab'}
              onClick={() => {
                setMappingOpen(false);
                setView('runs');
              }}
            >
              Previous runs
            </button>
          </div>
        </nav>

        <div className={view === 'runs' ? 'app-body app-body--wide' : 'app-body'}>
          {view !== 'runs' && view !== 'home' ? (
            <aside className="workflow-sidebar">
              <p className="workflow-sidebar__label">Migration workflow</p>
              {migrationMode === 'semantic_model' ? (
                <nav aria-label="Semantic model migration steps">
                  {[
                    { step: 1, title: 'Propose semantic groups', job: 'Propose semantic groups Job' },
                    { step: 2, title: 'Approve and migrate', job: 'Migrate approved semantic groups Job' },
                    { step: 3, title: 'Review Metric Views', job: 'Semantic group and repair Jobs' },
                  ].map(({ step, title, job }) => (
                    <button
                      key={step}
                      className={[
                        'workflow-step',
                        semanticStep === step ? 'workflow-step--active' : '',
                        step === 2 && selectedRunApproved && semanticStep !== 2 ? 'workflow-step--done' : '',
                      ]
                        .filter(Boolean)
                        .join(' ')}
                      type="button"
                      aria-current={semanticStep === step ? 'step' : undefined}
                      onClick={() => {
                        if (step === 2) setRunFocus({ preferPending: true, nonce: Date.now() });
                        if (step !== 1) setSemanticStepView(step as 2 | 3);
                        setView(step === 1 ? 'upload' : 'semantic');
                      }}
                    >
                      <span>{step === 2 && selectedRunApproved && semanticStep !== 2 ? '✓' : step}</span>
                      <span className="workflow-step__text">
                        {title}
                        <small>{job}</small>
                      </span>
                    </button>
                  ))}
                </nav>
              ) : (
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
                    Start migration
                  </button>
                  <button
                    className={
                      view === 'review' && !mappingOpen ? 'workflow-step workflow-step--active' : 'workflow-step'
                    }
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
              )}
            </aside>
          ) : null}

          <main className="review-main">
            {view === 'home' ? (
              <HomePage
                onStart={(option) => {
                  if (option === 'runs') {
                    setView('runs');
                    return;
                  }
                  setMigrationMode(option === 'dashboard' ? 'dashboard' : 'semantic_model');
                  setView('upload');
                }}
              />
            ) : (
              <section className="page-intro">
                {view !== 'runs' && migrationMode === 'semantic_model' ? (
                  <p className="page-intro__step">Step {semanticStep} of 3</p>
                ) : null}
                <h2>{pageIntro.title}</h2>
                <p>{pageIntro.description}</p>
              </section>
            )}

            {view === 'upload' ? (
              <UploadPanel
                migrationMode={migrationMode}
                onMigrationModeChange={(nextMode) => {
                  setMigrationMode(nextMode);
                  setMappingOpen(false);
                }}
                onReview={() => {
                  void loadReview('uploaded').then(() => setView('review'));
                }}
                onBrowseRuns={(proposalRunId) => {
                  setRunFocus({ runId: proposalRunId, preferPending: true, nonce: Date.now() });
                  setSemanticStepView(2);
                  setView('semantic');
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
            {view === 'runs' || view === 'semantic' ? (
              <SemanticRunBrowser
                sessionUser={sessionUser}
                focus={view === 'semantic' ? runFocus : undefined}
                stage={view === 'semantic' ? semanticStepView : 3}
                onSelectedRunStatusChange={view === 'semantic' ? setSemanticRunStatus : undefined}
              />
            ) : null}
          </main>
        </div>
        <DocsDialog document={openDocument} onClose={() => setOpenDocument(null)} />
      </div>
    </TooltipProvider>
  );
}

const isTableMappingFile = (name: string) => /^table-mapping\.(csv|ya?ml)$/i.test(name);

function UploadPanel({
  migrationMode,
  onMigrationModeChange,
  onReview,
  onBrowseRuns,
}: {
  migrationMode: MigrationMode;
  onMigrationModeChange: (mode: MigrationMode) => void;
  onReview: () => void;
  onBrowseRuns: (proposalRunId?: string) => void;
}) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploads, setUploads] = useState<UploadResponse | null>(null);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [selectedVolume, setSelectedVolume] = useState('');
  const [migrationName, setMigrationName] = usePersistentState('migration-name', '', isString);
  const [inputMethod, setInputMethod] = usePersistentState(
    'input-method',
    'upload',
    isOneOf(['upload', 'volume'] as const)
  );
  const [datasourcePath, setDatasourcePath] = usePersistentState('datasource-path', '', isString);
  const [mappingPath, setMappingPath] = usePersistentState('mapping-path', '', isString);
  const [inspectedInputRoot, setInspectedInputRoot] = useState('');
  const [mappingPreview, setMappingPreview] = useState<{ name: string; content: string } | null>(null);
  const previewRows = useMemo(
    () => (mappingPreview?.name.toLowerCase().endsWith('.csv') ? parseCsv(mappingPreview.content) : []),
    [mappingPreview]
  );

  const migrationNameSynced = useRef(false);
  const allFiles = uploads?.files ?? [];
  const modeFiles = allFiles.filter((file) =>
    migrationMode === 'semantic_model'
      ? file.kind === 'Tableau datasource' || file.kind === 'Mapping evidence'
      : file.kind !== 'Tableau datasource'
  );
  const hiddenFileCount = allFiles.length - modeFiles.length;
  const datasourceCount = allFiles.filter((file) => file.kind === 'Tableau datasource').length;
  const hasTableMapping = allFiles.some((file) => isTableMappingFile(file.name));
  const readyToProcess =
    inputMethod === 'volume'
      ? Boolean(inspectedInputRoot)
      : migrationMode === 'semantic_model'
        ? datasourceCount > 0 && hasTableMapping
        : allFiles.some((file) => file.kind === 'Tableau workbook');

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
    if (!migrationNameSynced.current) {
      // Reconcile the remembered name with the server's active migration once per page load.
      migrationNameSynced.current = true;
      const rememberedName = readPersistedValue('migration-name', '', isString);
      if (
        rememberedName &&
        payload.migrationName &&
        rememberedName !== payload.migrationName &&
        payload.processing?.status !== 'running'
      ) {
        await applyMigrationName(rememberedName);
        return;
      }
      setMigrationName(payload.migrationName || rememberedName);
      return;
    }
    setMigrationName((current) => current || payload.migrationName || '');
  };

  const applyMigrationName = async (name: string = migrationName) => {
    const response = await fetch('/api/migration-context', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ name, mode: migrationMode }),
    });
    const payload = (await response.json()) as { name?: string; error?: string };
    if (!response.ok || !payload.name) {
      setUploadError(payload.error ?? 'Could not set migration name.');
      return;
    }
    setMigrationName(payload.name);
    await loadUploads();
  };

  const inspectVolumeInputs = async () => {
    setBusy(true);
    setUploadError(null);
    setInspectedInputRoot('');
    try {
      const response = await fetch('/api/volume-inputs/inspect', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ datasourcePath, mappingPath }),
      });
      const payload = (await response.json()) as { inputRoot?: string; error?: string };
      if (!response.ok || !payload.inputRoot) throw new Error(payload.error ?? 'Could not inspect Volume inputs.');
      setInspectedInputRoot(payload.inputRoot);
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : 'Could not inspect Volume inputs.');
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    // Re-validate restored Volume paths so a returning user can start without re-entering them.
    if (inputMethod === 'volume' && datasourcePath && mappingPath) void inspectVolumeInputs();
  }, []);

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
        body: JSON.stringify({
          volume: selectedVolume,
          mode: migrationMode,
          inputMethod,
          datasourcePath,
          mappingPath,
        }),
      });
      const responseText = await response.text();
      let payload: { error?: string; detail?: string } = {};
      try {
        payload = JSON.parse(responseText) as { error?: string; detail?: string };
      } catch {
        throw new Error(`Migration request failed with HTTP ${response.status}.`);
      }
      if (!response.ok) {
        throw new Error(
          [payload.error, payload.detail].filter(Boolean).join(' ') || 'Could not start inventory processing.'
        );
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
          Start a migration
        </CardTitle>
      </CardHeader>
      <CardContent className="upload-content">
        <div className="migration-start-grid">
          <label>
            Migration outcome
            <select
              value={migrationMode}
              onChange={(event) => {
                const nextMode = event.target.value as MigrationMode;
                onMigrationModeChange(nextMode);
                if (nextMode === 'dashboard') setInputMethod('upload');
                setSelectedFiles([]);
                setInspectedInputRoot('');
              }}
            >
              <option value="semantic_model">Migrate semantic model only</option>
              {DASHBOARD_MIGRATION_ENABLED ? <option value="dashboard">Migrate dashboards</option> : null}
            </select>
            <small>
              {migrationMode === 'semantic_model'
                ? 'Group Tableau datasources, create candidate Metric Views, evaluate, and repair.'
                : 'Inventory Tableau workbooks, approve mappings, and create AI/BI dashboards.'}
            </small>
          </label>
          <label>
            Input method
            <select
              value={inputMethod}
              onChange={(event) => {
                setInputMethod(event.target.value as 'upload' | 'volume');
                setInspectedInputRoot('');
              }}
            >
              <option value="upload">Upload files</option>
              {migrationMode === 'semantic_model' ? <option value="volume">Use existing Volume files</option> : null}
            </select>
            <small>Existing Volume files stay in place; the workflow reads them through Unity Catalog.</small>
          </label>
        </div>
        {inputMethod === 'upload' ? (
          <div className="upload-destination">
            <label>
              Migration name
              <span className="upload-destination__name">
                <input
                  value={migrationName}
                  onChange={(event) => setMigrationName(event.target.value)}
                  onBlur={() => {
                    if (migrationName.trim() && migrationName !== uploads?.migrationName) void applyMigrationName();
                  }}
                  placeholder="my-migration"
                />
              </span>
            </label>
            <div className="upload-destination__path">
              <span>Uploads go to</span>
              <code>
                {selectedVolume
                  ? `/Volumes/${selectedVolume.split('.').join('/')}/bi-migrations/${migrationName || 'migration-name'}/`
                  : 'Loading authorized Volume…'}
              </code>
            </div>
          </div>
        ) : null}
        {inputMethod === 'upload' ? (
          <div className="upload-dropzone">
            <label htmlFor="tableau-files">
              {migrationMode === 'semantic_model'
                ? 'Choose datasources and mapping evidence'
                : 'Choose workbooks and mapping evidence'}
            </label>
            <p>
              {migrationMode === 'semantic_model'
                ? 'TDS/TDSX plus table-mapping CSV or YAML, up to 100 MB each.'
                : 'TWB/TWBX plus CSV, JSON, YAML, or Markdown mappings, up to 100 MB each.'}
            </p>
            <input
              ref={fileInputRef}
              id="tableau-files"
              hidden
              type="file"
              accept={
                migrationMode === 'semantic_model'
                  ? '.tds,.tdsx,.csv,.yaml,.yml'
                  : '.twb,.twbx,.csv,.json,.yaml,.yml,.md'
              }
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
              {selectedFiles.length > 0 ? (
                <Button onClick={() => void uploadFiles()} disabled={busy || !selectedVolume}>
                  {busy
                    ? 'Uploading…'
                    : `Upload ${selectedFiles.length} ${selectedFiles.length === 1 ? 'file' : 'files'}`}
                </Button>
              ) : null}
            </div>
            {selectedFiles.length > 0 && !selectedVolume ? (
              <p className="upload-action-hint">Waiting for the authorized Volume before uploading.</p>
            ) : null}
          </div>
        ) : (
          <div className="volume-input-card">
            <div className="volume-input-card__heading">
              <FolderSearch className="size-5" aria-hidden="true" />
              <div>
                <h3>Use existing Unity Catalog files</h3>
                <p>
                  Paste the input folder (or its datasources subfolder) and the mapping file. Both must be in the same
                  input folder.
                </p>
              </div>
            </div>
            <label>
              Input folder or datasources folder
              <input
                value={datasourcePath}
                onChange={(event) => {
                  setDatasourcePath(event.target.value);
                  setInspectedInputRoot('');
                }}
                placeholder="/Volumes/catalog/schema/volume/project"
              />
            </label>
            <label>
              Mapping folder or file
              <input
                value={mappingPath}
                onChange={(event) => {
                  setMappingPath(event.target.value);
                  setInspectedInputRoot('');
                }}
                placeholder="/Volumes/catalog/schema/volume/project/mappings/table-mapping.yaml"
              />
            </label>
            <div className="volume-input-card__action">
              <Button
                variant="outline"
                onClick={() => void inspectVolumeInputs()}
                disabled={busy || !datasourcePath || !mappingPath}
              >
                Inspect paths
              </Button>
              {inspectedInputRoot ? <span>Ready: {inspectedInputRoot}</span> : <span>No files are copied.</span>}
            </div>
          </div>
        )}
        {uploadError ? (
          <Alert variant="destructive">
            <AlertCircle className="size-4" />
            <AlertTitle>Action failed</AlertTitle>
            <AlertDescription>{uploadError}</AlertDescription>
          </Alert>
        ) : null}
        {inputMethod === 'upload' ? (
          <>
            <div className="upload-status">
              <div>
                <h3>Files in this migration</h3>
                {hiddenFileCount > 0 ? (
                  <p>
                    {hiddenFileCount} {hiddenFileCount === 1 ? 'file is' : 'files are'} hidden because{' '}
                    {hiddenFileCount === 1 ? 'it is' : 'they are'} only used by{' '}
                    {migrationMode === 'semantic_model'
                      ? DASHBOARD_MIGRATION_ENABLED
                        ? 'Migrate dashboards'
                        : 'dashboard migration, which is temporarily unavailable'
                      : 'Migrate semantic model only'}
                    .
                  </p>
                ) : null}
              </div>
              <Badge variant="outline">
                {modeFiles.length} uploaded
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
              {modeFiles.length === 0 && selectedFiles.length === 0 ? (
                <p className="upload-file-list__empty">No files uploaded for this migration yet.</p>
              ) : null}
              {modeFiles.map((file) => (
                <div className="upload-file" key={file.name}>
                  <span>
                    {file.kind === 'Mapping evidence' ? (
                      <button
                        className="upload-file__preview"
                        type="button"
                        onClick={() => void previewMapping(file.name)}
                      >
                        {file.name}
                      </button>
                    ) : (
                      <strong>{file.name}</strong>
                    )}
                    <small>{file.kind}</small>
                    {migrationMode === 'semantic_model' &&
                    file.kind === 'Mapping evidence' &&
                    !isTableMappingFile(file.name) ? (
                      <small className="upload-file__warning">
                        Not used: the workflow reads only table-mapping.yaml, .yml, or .csv.
                      </small>
                    ) : null}
                    {file.volumePath ? (
                      <small className="upload-volume-path" title={file.volumePath}>
                        {file.volumePath}
                      </small>
                    ) : null}
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
            {migrationMode === 'dashboard' ? (
              <div>
                <h3>Detected target namespaces</h3>
                <p className="mapping-source-note">
                  Fully qualified Databricks tables are detected from uploaded mappings. Change the selection only to
                  inspect an additional scope.
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
            ) : null}
          </>
        ) : null}
        {migrationMode === 'semantic_model' && inputMethod === 'upload' ? (
          <ul className="readiness-checklist" aria-label="Ready to propose semantic groups">
            <li className={datasourceCount > 0 ? 'readiness-checklist__done' : undefined}>
              {datasourceCount > 0 ? <CheckCircle2 aria-hidden="true" /> : <AlertCircle aria-hidden="true" />}
              {datasourceCount > 0
                ? `${datasourceCount} Tableau ${datasourceCount === 1 ? 'datasource' : 'datasources'} (.tds/.tdsx)`
                : 'Upload at least one .tds or .tdsx datasource'}
            </li>
            <li className={hasTableMapping ? 'readiness-checklist__done' : undefined}>
              {hasTableMapping ? <CheckCircle2 aria-hidden="true" /> : <AlertCircle aria-hidden="true" />}
              {hasTableMapping
                ? 'Table mapping file'
                : 'Upload a mapping named table-mapping.yaml, table-mapping.yml, or table-mapping.csv'}
            </li>
          </ul>
        ) : null}
        <div className="upload-actions">
          <Button
            onClick={() => void processUploads()}
            disabled={busy || !readyToProcess || uploads?.processing.status === 'running'}
          >
            {migrationMode === 'semantic_model' ? 'Propose semantic groups' : 'Run inventory'}
          </Button>
          <span>
            {!uploads || uploads.processing.status === 'idle'
              ? migrationMode === 'semantic_model'
                ? 'Starts the Propose semantic groups Job. You review the proposed groups in step 2; nothing is created yet.'
                : 'Starts the inventory Job, then you review groups and mappings.'
              : uploads.processing.message}
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
          {uploads?.processing.status === 'complete' ? (
            migrationMode === 'semantic_model' ? (
              <Button
                onClick={() => onBrowseRuns(uploads.processing.runId ? String(uploads.processing.runId) : undefined)}
              >
                Review semantic run
              </Button>
            ) : (
              <Button onClick={onReview}>Review groups</Button>
            )
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

type RunFocus = { runId?: string; preferPending?: boolean; nonce: number };

function SemanticRunBrowser({
  sessionUser,
  focus,
  stage = 3,
  onSelectedRunStatusChange,
}: {
  sessionUser: { displayName: string; userName: string } | null;
  focus?: RunFocus;
  stage?: 2 | 3;
  onSelectedRunStatusChange?: (status: string | null) => void;
}) {
  const [root, setRoot] = useState('');
  const [runs, setRuns] = useState<SemanticRun[]>([]);
  const [selectedRunId, setSelectedRunId] = usePersistentState<string | null>(
    'semantic-run-id',
    null,
    (value): value is string | null => value === null || isString(value)
  );
  const [selectedGroupId, setSelectedGroupId] = useState<string | null>(null);
  const [groupReview, setGroupReview] = useState<SemanticGroupReview | null>(null);
  const [loadingRuns, setLoadingRuns] = useState(true);
  const [loadingGroup, setLoadingGroup] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [migrationRun, setMigrationRun] = useState<{
    proposalRunId: string;
    runId: number;
    runUrl?: string | null;
    approval?: 'pending' | 'approved' | 'rejected';
    approvalError?: string | null;
    lifeCycleState?: string;
    resultState?: string;
  } | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const loadRuns = async (requestedRoot?: string, options: { quiet?: boolean } = {}) => {
    if (!options.quiet) setLoadingRuns(true);
    setActionError(null);
    try {
      const query = requestedRoot ? `?root=${encodeURIComponent(requestedRoot)}` : '';
      const response = await fetch(`/api/semantic-runs${query}`);
      const payload = (await response.json()) as SemanticRunsResponse;
      if (!response.ok) throw new Error([payload.error, payload.detail].filter(Boolean).join(' '));
      setRoot(payload.root);
      writePersistedValue('semantic-output-root', payload.root);
      setRuns(payload.runs ?? []);
      setSelectedRunId((current) =>
        current && payload.runs.some((run) => run.runId === current) ? current : (payload.runs[0]?.runId ?? null)
      );
    } catch (error) {
      if (requestedRoot) setRoot(requestedRoot);
      setActionError(error instanceof Error ? error.message : 'Could not load semantic workflow runs.');
      setRuns([]);
    } finally {
      setLoadingRuns(false);
    }
  };

  useEffect(() => {
    void loadRuns(readPersistedValue('semantic-output-root', '', isString) || undefined);
  }, []);

  // Apply a navigation request: the just-proposed run, else the newest run awaiting approval.
  const appliedFocusNonce = useRef<number | null>(null);
  useEffect(() => {
    if (!focus || runs.length === 0 || (!focus.runId && !focus.preferPending)) return;
    if (appliedFocusNonce.current === focus.nonce) return;
    appliedFocusNonce.current = focus.nonce;
    const requested = focus.runId ? runs.find((run) => run.runId === focus.runId) : undefined;
    const pending = runs.find((run) => !run.supersededBy && PENDING_APPROVAL_STATUSES.has(run.status));
    const target = requested ?? (focus.preferPending ? pending : undefined);
    if (target) setSelectedRunId(target.runId);
  }, [focus?.nonce, runs]);

  const selectedRun = useMemo(() => runs.find((run) => run.runId === selectedRunId) ?? null, [runs, selectedRunId]);
  // Changes when the selected group's result lands, so its detail panel reloads during migration.
  const selectedGroupResult =
    selectedRun?.groups.find((group) => group.group_id === selectedGroupId)?.gateStatus ?? null;

  // While a run is migrating, refresh so each group's badge flips as its result lands.
  const selectedRunMigrating = Boolean(selectedRun && MIGRATION_RUNNING_STATUSES.has(selectedRun.status));
  useEffect(() => {
    if (!selectedRunMigrating || !root) return;
    const timer = window.setInterval(() => void loadRuns(root, { quiet: true }), 30000);
    return () => window.clearInterval(timer);
  }, [selectedRunMigrating, root]);

  useEffect(() => {
    const submitted =
      migrationRun && migrationRun.proposalRunId === selectedRun?.runId && migrationRun.approval !== 'rejected';
    onSelectedRunStatusChange?.(submitted ? 'MIGRATION_SUBMITTED' : (selectedRun?.status ?? null));
  }, [selectedRun?.status, selectedRun?.runId, migrationRun]);

  useEffect(() => {
    const groups = selectedRun?.groups ?? [];
    setSelectedGroupId((current) =>
      current && groups.some((group) => group.group_id === current) ? current : (groups[0]?.group_id ?? null)
    );
  }, [selectedRun]);

  useEffect(() => {
    if (!selectedRunId || !selectedGroupId || !root) {
      setGroupReview(null);
      return;
    }
    // Wait until the group selection belongs to the selected run (avoids a stale run/group pair).
    if (!selectedRun?.groups.some((group) => group.group_id === selectedGroupId)) return;
    const loadGroup = async () => {
      setLoadingGroup(true);
      setActionError(null);
      try {
        const response = await fetch(
          `/api/semantic-runs/${selectedRunId}/groups/${selectedGroupId}?root=${encodeURIComponent(root)}`
        );
        const payload = (await response.json()) as SemanticGroupReview;
        if (!response.ok) throw new Error(payload.error ?? 'Could not load semantic group review.');
        setGroupReview(payload);
      } catch (error) {
        setGroupReview(null);
        setActionError(error instanceof Error ? error.message : 'Could not load semantic group review.');
      } finally {
        setLoadingGroup(false);
      }
    };
    void loadGroup();
  }, [root, selectedRunId, selectedGroupId, selectedGroupResult]);

  const startMigration = async () => {
    if (!selectedRunId || submitting) return;
    setSubmitting(true);
    setActionError(null);
    try {
      const response = await fetch(`/api/semantic-runs/${selectedRunId}/migrate`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ root }),
      });
      const payload = (await response.json()) as { runId?: number; runUrl?: string | null; error?: string };
      if (!response.ok || !payload.runId) throw new Error(payload.error ?? 'Could not start semantic migration.');
      setMigrationRun({
        proposalRunId: selectedRunId,
        runId: payload.runId,
        runUrl: payload.runUrl,
        approval: 'pending',
      });
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Could not start semantic migration.');
    } finally {
      setSubmitting(false);
    }
  };

  const migrationRunId = migrationRun?.runId;
  const migrationFinished = migrationRun?.lifeCycleState === 'TERMINATED' || migrationRun?.approval === 'rejected';
  useEffect(() => {
    if (!migrationRunId || migrationFinished) return;
    let cancelled = false;
    const check = async () => {
      const response = await fetch(`/api/semantic-migrations/${migrationRunId}`);
      if (!response.ok || cancelled) return;
      const status = (await response.json()) as {
        approval: 'pending' | 'approved' | 'rejected';
        approvalError: string | null;
        lifeCycleState: string;
        resultState: string;
      };
      setMigrationRun((current) => {
        if (!current || current.runId !== migrationRunId) return current;
        if (current.approval !== 'approved' && status.approval === 'approved') void loadRuns(root);
        return { ...current, ...status };
      });
    };
    void check();
    const timer = window.setInterval(() => void check(), 10000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [migrationRunId, migrationFinished]);

  const migrationForSelectedRun = migrationRun && migrationRun.proposalRunId === selectedRunId ? migrationRun : null;
  const selectedRunStatus = selectedRun?.supersededBy ? 'SUPERSEDED' : selectedRun?.status;
  const awaitingApproval = Boolean(
    selectedRun && !selectedRun.supersededBy && PENDING_APPROVAL_STATUSES.has(selectedRun.status)
  );

  return (
    <section className="run-browser" aria-label="Semantic migration runs">
      <Card className="workspace-card run-browser__header">
        <CardContent className="run-browser__controls">
          <div className="run-browser__volume-row">
            <label>
              Workflow output folder
              <input
                value={root}
                onChange={(event) => setRoot(event.target.value)}
                placeholder="/Volumes/catalog/schema/volume/semantic_workflows"
              />
            </label>
            <Button
              variant="outline"
              onClick={() => void loadRuns(root)}
              disabled={loadingRuns || !root.startsWith('/Volumes/')}
            >
              {loadingRuns ? 'Loading…' : 'Load runs'}
            </Button>
          </div>
          <label className="run-browser__run-select">
            Run
            <select
              value={selectedRunId ?? ''}
              onChange={(event) => setSelectedRunId(event.target.value || null)}
              disabled={loadingRuns || runs.length === 0}
            >
              {runs.length === 0 ? <option value="">No retained runs</option> : null}
              {runs.map((run) => (
                <option key={run.runId} value={run.runId}>
                  {run.runFolder} · {statusLabel(run.supersededBy ? 'SUPERSEDED' : run.status)}
                </option>
              ))}
            </select>
          </label>
        </CardContent>
      </Card>

      {actionError ? (
        <Alert variant="destructive">
          <AlertCircle className="size-4" />
          <AlertTitle>Action failed</AlertTitle>
          <AlertDescription>{actionError}</AlertDescription>
        </Alert>
      ) : null}

      {loadingRuns ? <LoadingState /> : null}
      {!loadingRuns && runs.length === 0 ? (
        <EmptyMessage
          title="No retained runs"
          description="Check the workflow output folder or run semantic grouping first."
        />
      ) : null}
      {!loadingRuns && runs.length > 0 ? (
        <div className="run-browser__workspace">
          <aside className="run-browser__sidebar" aria-label="Selected run">
            {selectedRun ? (
              <Card className="workspace-card run-summary-card">
                <CardHeader>
                  <div className="run-summary-heading">
                    <CardTitle>Run {selectedRun.runId}</CardTitle>
                    <StatusBadge status={selectedRunStatus} />
                  </div>
                </CardHeader>
                <CardContent className="run-summary-content">
                  <p>{selectedRun.headline}</p>
                  <dl className="run-summary-list">
                    <div>
                      <dt>Started</dt>
                      <dd>
                        {selectedRun.createdAt ? new Date(selectedRun.createdAt).toLocaleString() : 'Unavailable'}
                      </dd>
                    </div>
                    <div>
                      <dt>Input</dt>
                      <dd>
                        <code>{selectedRun.inputVolumePath ?? 'Unavailable'}</code>
                      </dd>
                    </div>
                    <div>
                      <dt>Run folder</dt>
                      <dd>
                        <code>{selectedRun.runFolder}</code>
                      </dd>
                    </div>
                  </dl>
                  {selectedRun.supersededBy ? (
                    <div className="run-next-step run-next-step--muted">
                      <strong>Superseded</strong>
                      <p>
                        A newer proposal exists for the same input: <code>{selectedRun.supersededBy}</code>. Review and
                        approve that run instead.
                      </p>
                    </div>
                  ) : null}
                  {selectedRun.approval && !migrationForSelectedRun ? (
                    <div className="run-next-step run-next-step--done">
                      <strong>Approved</strong>
                      <p>
                        By {selectedRun.approval.approvedBy ?? 'unknown'}
                        {selectedRun.approval.approvedAt
                          ? ` on ${new Date(selectedRun.approval.approvedAt).toLocaleString()}`
                          : ''}
                        .
                      </p>
                      {selectedRun.approval.migrationRunId ? (
                        <small>
                          Migration run {selectedRun.approval.migrationRunId}{' '}
                          {selectedRun.approval.migrationRunUrl ? (
                            <a
                              className="job-run-link"
                              href={selectedRun.approval.migrationRunUrl}
                              target="_blank"
                              rel="noreferrer"
                            >
                              View Job run <ExternalLink aria-hidden="true" />
                            </a>
                          ) : null}
                        </small>
                      ) : null}
                    </div>
                  ) : null}
                  {stage === 3 && awaitingApproval && !migrationForSelectedRun ? (
                    <div className="run-next-step run-next-step--muted">
                      <strong>Not approved yet</strong>
                      <p>Metric Views are built after approval. Open step 2 to review and approve this run.</p>
                    </div>
                  ) : null}
                  {stage === 2 &&
                  awaitingApproval &&
                  (!migrationForSelectedRun || migrationForSelectedRun.approval === 'rejected') ? (
                    <div className="run-next-step">
                      <strong>Next step: approve</strong>
                      <p>
                        Check each group&apos;s datasources and target tables, then approve. This starts the Migrate
                        approved semantic groups Job for exactly this run.
                      </p>
                      <Button onClick={() => void startMigration()} disabled={submitting}>
                        <Play className="size-4" aria-hidden="true" />
                        {submitting
                          ? 'Starting…'
                          : `Approve and migrate ${selectedRun.groups.length} ${
                              selectedRun.groups.length === 1 ? 'group' : 'groups'
                            }`}
                      </Button>
                      <small>Approval is recorded as {sessionUser?.displayName ?? 'the signed-in user'}.</small>
                    </div>
                  ) : null}
                  {migrationForSelectedRun ? (
                    <Alert variant={migrationForSelectedRun.approval === 'rejected' ? 'destructive' : 'default'}>
                      {migrationForSelectedRun.approval === 'rejected' ? (
                        <AlertCircle className="size-4" />
                      ) : (
                        <CheckCircle2 className="size-4" />
                      )}
                      <AlertTitle>
                        {migrationForSelectedRun.approval === 'rejected'
                          ? 'Approval rejected'
                          : migrationForSelectedRun.approval === 'approved'
                            ? migrationForSelectedRun.lifeCycleState === 'TERMINATED'
                              ? `Migration finished: ${statusLabel(migrationForSelectedRun.resultState)}`
                              : 'Approved: migrating groups'
                            : 'Checking approval…'}
                      </AlertTitle>
                      <AlertDescription>
                        {migrationForSelectedRun.approvalError ? (
                          <span className="migration-run-error">{migrationForSelectedRun.approvalError}</span>
                        ) : null}
                        <span>
                          Migration run {migrationForSelectedRun.runId}{' '}
                          {migrationForSelectedRun.runUrl ? (
                            <a
                              className="job-run-link"
                              href={migrationForSelectedRun.runUrl}
                              target="_blank"
                              rel="noreferrer"
                            >
                              View Job run <ExternalLink aria-hidden="true" />
                            </a>
                          ) : null}
                        </span>
                      </AlertDescription>
                    </Alert>
                  ) : null}
                </CardContent>
              </Card>
            ) : null}

            {selectedRun?.groups.length ? (
              <Card className="workspace-card">
                <CardHeader>
                  <CardTitle>Semantic groups · {selectedRun.groups.length}</CardTitle>
                </CardHeader>
                <CardContent className="semantic-run-groups">
                  {selectedRun.groups.map((group) => (
                    <button
                      type="button"
                      key={group.group_id}
                      aria-pressed={group.group_id === selectedGroupId}
                      className={
                        group.group_id === selectedGroupId
                          ? 'semantic-run-group semantic-run-group--selected'
                          : 'semantic-run-group'
                      }
                      onClick={() => setSelectedGroupId(group.group_id)}
                    >
                      <span className="semantic-run-group__title">
                        <strong>{group.display_name}</strong>
                        <StatusBadge status={groupDisplayStatus(group, selectedRun.status)} />
                      </span>
                      <small title={group.candidate_metric_view_fqn ?? undefined}>
                        {group.candidate_metric_view_fqn?.split('.').pop() ?? 'Candidate not created'}
                      </small>
                    </button>
                  ))}
                </CardContent>
              </Card>
            ) : null}
          </aside>

          <div className="run-browser__detail">
            {loadingGroup ? <DetailLoadingState /> : null}
            {!loadingGroup && groupReview ? (
              <SemanticGroupReviewPanel
                review={groupReview}
                awaitingApproval={awaitingApproval}
                showResults={stage === 3 && !awaitingApproval}
                inProgress={groupDisplayStatus(groupReview.group, selectedRun?.status) === 'MIGRATION_IN_PROGRESS'}
              />
            ) : null}
            {!loadingGroup && !groupReview && selectedRun && selectedRun.groups.length === 0 ? (
              <EmptyMessage title="No groups yet" description="This run has not produced semantic groups." />
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function StatusBadge({ status }: { status: string | null | undefined }) {
  return (
    <Badge variant="outline" className={`status-badge status-badge--${statusTone(status)}`}>
      {statusLabel(status)}
    </Badge>
  );
}

function GroupMembership({ summary }: { summary: SemanticGroupReview['sourceSummary'] }) {
  const fileName = (sourcePath?: string) => sourcePath?.split('/').pop() ?? '';
  const rows = [
    ...(summary?.datasources ?? []).map((item) => ({ ...item, role: 'Primary' })),
    ...(summary?.supporting_datasources ?? []).map((item) => ({ ...item, role: 'Supporting' })),
  ];
  if (!rows.length && !summary?.target_tables?.length) return null;
  return (
    <div className="group-membership">
      <h4>Proposed membership</h4>
      {rows.length ? (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Tableau datasource</TableHead>
              <TableHead>File</TableHead>
              <TableHead>Role</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((item) => (
              <TableRow key={`${item.role}-${item.source_path ?? item.datasource_name}`}>
                <TableCell>{item.datasource_name ?? 'Unnamed datasource'}</TableCell>
                <TableCell>
                  <code>{fileName(item.source_path)}</code>
                </TableCell>
                <TableCell>{item.role}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ) : null}
      {summary?.target_tables?.length ? (
        <div className="group-membership__targets">
          <span>Databricks target tables</span>
          <div className="action-names">
            {summary.target_tables.map((table) => (
              <span key={table}>{table}</span>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function SemanticGroupReviewPanel({
  review,
  awaitingApproval = false,
  showResults = true,
  inProgress = false,
}: {
  review: SemanticGroupReview;
  awaitingApproval?: boolean;
  showResults?: boolean;
  inProgress?: boolean;
}) {
  const migration = review.migrationReview;
  const repair = review.repairReview;
  const gates = repair?.coverage_gates ?? [];
  const [openReport, setOpenReport] = useState<'migration' | 'repair' | null>(null);
  const reportHtml =
    openReport === 'migration' ? review.reports?.migrationReviewHtml : review.reports?.repairReviewHtml;
  const reportTitle = openReport === 'migration' ? 'Semantic migration review' : 'Metric View repair report';
  return (
    <div className="semantic-review-stack">
      <Card className="workspace-card semantic-group-overview-card">
        <CardHeader>
          <div className="semantic-group-overview-heading">
            <span>Selected semantic group</span>
            <CardTitle>{review.group.display_name}</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="semantic-review-section">
          <p>{review.sourceSummary?.grouping_rationale ?? 'Grouping rationale is unavailable.'}</p>
          <GroupMembership summary={review.sourceSummary} />
          {awaitingApproval ? (
            <p className="approval-hint">
              The candidate Metric View is built and evaluated after you approve this proposal.
            </p>
          ) : null}
          <div className="review-kpis" hidden={!showResults}>
            <div>
              <span>Datasources</span>
              <strong>{review.sourceSummary?.datasource_count ?? '—'}</strong>
            </div>
            <div>
              <span>Dimensions</span>
              <strong>{migration?.coverage?.dimensions_created ?? '—'}</strong>
            </div>
            <div>
              <span>Measures</span>
              <strong>{migration?.coverage?.measures_created ?? '—'}</strong>
            </div>
            <div>
              <span>Semantic coverage</span>
              <strong>
                {migration?.coverage?.semantic_coverage_percent !== undefined
                  ? `${migration.coverage.semantic_coverage_percent}%`
                  : '—'}
              </strong>
            </div>
          </div>
          <div className="artifact-path">
            <span>Candidate Metric View</span>
            <MetricViewName
              fullName={migration?.candidate?.metric_view_fqn ?? review.group.candidate_metric_view_fqn}
              exists={Boolean(migration?.candidate?.metric_view_fqn)}
            />
          </div>
        </CardContent>
      </Card>

      {showResults && migration?.gate ? <ReleaseGateCard gate={migration.gate} /> : null}

      {!showResults ? null : (
        <>
          <Card className="workspace-card review-evidence-card">
            <CardHeader>
              <div className="review-card-heading">
                <CardTitle>Semantic migration review</CardTitle>
                <Button
                  className="review-report-button"
                  variant="outline"
                  size="sm"
                  onClick={() => setOpenReport('migration')}
                  disabled={!review.reports?.migrationReviewHtml}
                >
                  <FileText className="size-4" aria-hidden="true" />
                  View full report
                </Button>
              </div>
            </CardHeader>
            <CardContent className="semantic-review-section">
              {migration ? (
                <>
                  <div className="review-status-line">
                    <StatusBadge status={migration.readiness ?? migration.status} />
                    <span>{migration.headline}</span>
                  </div>
                  {migration.action_groups ? (
                    <ActionGroupsView actionGroups={migration.action_groups} />
                  ) : (migration.recommended_actions ?? []).length ? (
                    <div className="review-action-list">
                      {migration.recommended_actions?.map((action) => (
                        <div key={`${action.priority}-${action.title}`}>
                          <strong>{action.title}</strong>
                          <p>{action.description}</p>
                          {action.details?.length ? (
                            <dl className="action-detail-list">
                              {action.details.map((detail) => (
                                <div key={detail.name}>
                                  <dt>{detail.name}</dt>
                                  <dd>
                                    <code>{detail.expression}</code>
                                  </dd>
                                </div>
                              ))}
                            </dl>
                          ) : (
                            <small>{action.items?.join(', ')}</small>
                          )}
                          {action.how_to_fix ? (
                            <p className="action-how-to-fix">
                              <strong>How to fix:</strong> {action.how_to_fix}
                            </p>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p>No migration actions were recorded.</p>
                  )}
                </>
              ) : (
                <EmptyMessage
                  title={inProgress ? 'Migration in progress' : 'Migration review pending'}
                  description={
                    inProgress
                      ? "This group's Metric View is being built and evaluated. Results appear here when it finishes; the page refreshes every 30 seconds."
                      : 'This group has not produced a migration review yet.'
                  }
                />
              )}
            </CardContent>
          </Card>

          <Card className="workspace-card review-evidence-card">
            <CardHeader>
              <div className="review-card-heading">
                <CardTitle className="flex items-center gap-2">
                  <Wrench className="size-5" aria-hidden="true" />
                  Metric View repair
                </CardTitle>
                <Button
                  className="review-report-button"
                  variant="outline"
                  size="sm"
                  onClick={() => setOpenReport('repair')}
                  disabled={!review.reports?.repairReviewHtml}
                >
                  <FileText className="size-4" aria-hidden="true" />
                  View full report
                </Button>
              </div>
            </CardHeader>
            <CardContent className="semantic-review-section">
              {repair ? (
                <>
                  <div className="review-status-line">
                    <StatusBadge status={repair.status} />
                    <span>{repair.headline}</span>
                  </div>
                  <ul className="repair-decisions">
                    {(repair.decision_reasons ?? []).map((reason) => (
                      <li key={reason}>{reason}</li>
                    ))}
                  </ul>
                  {gates.length ? (
                    <div className="repair-gate-table">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Gate</TableHead>
                            <TableHead>Before</TableHead>
                            <TableHead>After</TableHead>
                            <TableHead>Required</TableHead>
                            <TableHead>Result</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {gates.map((gate) => (
                            <TableRow key={gate.key ?? gate.label}>
                              <TableCell>
                                <strong>{gate.label}</strong>
                                <small>{gate.definition}</small>
                              </TableCell>
                              <TableCell>
                                {gate.before !== undefined ? `${(gate.before * 100).toFixed(1)}%` : '—'}
                              </TableCell>
                              <TableCell>
                                {gate.after !== undefined ? `${(gate.after * 100).toFixed(1)}%` : '—'}
                              </TableCell>
                              <TableCell>
                                {gate.threshold !== undefined ? `${(gate.threshold * 100).toFixed(1)}%` : '—'}
                              </TableCell>
                              <TableCell>
                                <Badge variant="outline">
                                  {gate.passed ? 'Pass' : `Fail${gate.gap_count ? ` · ${gate.gap_count} short` : ''}`}
                                </Badge>
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  ) : null}
                  {migration?.action_groups && (repair.blocking_findings ?? []).length ? (
                    <p className="approval-hint">
                      Measures that need a person are listed once, with the reason, under Action items in the semantic
                      migration review above. The full repair report keeps every per-measure detail.
                    </p>
                  ) : (repair.blocking_findings ?? []).length ? (
                    <div className="review-action-list" aria-label="Repair action items">
                      {repair.blocking_findings?.map((finding, index) => (
                        <div key={`${finding.source_name ?? 'finding'}-${finding.status ?? index}`}>
                          <strong>{finding.source_name ?? `Finding ${index + 1}`}</strong>
                          <p>{finding.status ? statusLabel(finding.status) : 'Needs review'}</p>
                          {finding.failure_details?.[0]?.meaning ? <p>{finding.failure_details[0].meaning}</p> : null}
                          {finding.target?.expr ? (
                            <code className="action-expression">{finding.target.expr}</code>
                          ) : null}
                          {finding.query_detail?.status === 'FAIL' && finding.query_detail.reason ? (
                            <small className="action-query-error">Query error: {finding.query_detail.reason}</small>
                          ) : null}
                          <small>
                            {finding.recommended_action
                              ? `How to fix: ${finding.recommended_action}`
                              : 'This run was produced by an older workflow version without fix guidance. Open the full report for details.'}
                          </small>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </>
              ) : (
                <EmptyMessage
                  title={inProgress ? 'Evaluation and repair in progress' : 'Repair report pending'}
                  description={
                    inProgress
                      ? 'Automatic evaluation and repair run after the Metric View is built.'
                      : 'Repair has not run or the latest report is not available yet.'
                  }
                />
              )}
            </CardContent>
          </Card>
        </>
      )}

      <Dialog open={openReport !== null} onOpenChange={(open) => !open && setOpenReport(null)}>
        <DialogContent className="semantic-report-dialog">
          <DialogHeader>
            <DialogTitle>{reportTitle}</DialogTitle>
            <DialogDescription>
              {review.group.display_name} · generated workflow evidence and recommended actions
            </DialogDescription>
          </DialogHeader>
          {reportHtml ? (
            <iframe
              className="semantic-report-frame"
              title={`${reportTitle} for ${review.group.display_name}`}
              srcDoc={reportHtml}
              sandbox=""
            />
          ) : (
            <EmptyMessage title="Report unavailable" description="This workflow run did not produce the HTML report." />
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpenReport(null)}>
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
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
  const [gapDecisions, setGapDecisions] = useState<
    Record<string, { disposition: 'fix_now' | 'accept' | 'defer' | 'not_applicable'; notes: string }>
  >({});
  const [remediationBusy, setRemediationBusy] = useState(false);
  const [remediationPackage, setRemediationPackage] = useState<{
    dashboardPrompt: string;
    metricPrompt: string;
    agentPrompt: string;
  } | null>(null);
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
  const migrationGaps = useMemo(() => {
    if (!semanticResults) return [];
    const dashboardGaps = (semanticResults.dashboardSummary.findings ?? []).map((finding, index) => ({
      key: `dashboard-${index}`,
      stage: 'Dashboard import',
      severity: finding.severity ?? 'info',
      type: finding.type ?? 'migration_gap',
      detail: finding.detail ?? 'Dashboard migration gap recorded.',
      resolution: finding.resolution,
      asset: finding.workbook_name,
    }));
    const metricGaps = (semanticResults.metricExceptions?.exceptions ?? []).map((finding, index) => ({
      key: finding.id ?? `metric-${index}`,
      stage: 'Metric View',
      severity: finding.severity ?? 'info',
      type: finding.type ?? 'semantic_gap',
      detail: finding.detail ?? 'Metric View gap recorded.',
      resolution: finding.resolution,
      asset: undefined,
    }));
    const agentGaps = (semanticResults.agent.exceptions ?? [])
      .filter((finding) => !finding.id?.startsWith('BF-') && !finding.id?.startsWith('PLATFORM-'))
      .map((finding, index) => ({
        key: finding.id ?? `agent-${index}`,
        stage: 'Genie Agent',
        severity: 'medium',
        type: 'agent_gap',
        detail: finding.detail ?? 'Genie Agent gap recorded.',
        resolution: undefined,
        asset: undefined,
      }));
    return [...dashboardGaps, ...metricGaps, ...agentGaps];
  }, [semanticResults]);

  useEffect(() => {
    if (!migrationGaps.length) return;
    setGapDecisions((current) => {
      const next = { ...current };
      for (const gap of migrationGaps) {
        next[gap.key] ??= {
          disposition: gap.severity === 'high' || gap.severity === 'medium' ? 'fix_now' : 'defer',
          notes: '',
        };
      }
      return next;
    });
  }, [migrationGaps]);

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
      setFinalAgentName(
        payload.promotion?.final_agent_name ??
          payload.agent.genie_agent?.name ??
          payload.manifest.genie_agent_name ??
          ''
      );
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
      setSemanticResults((current) => (current ? { ...current, promotion: payload } : current));
    } catch (error) {
      setSemanticResultsError(error instanceof Error ? error.message : 'Promotion decision could not be saved.');
    } finally {
      setPromotionBusy(false);
    }
  };

  const prepareRemediation = async () => {
    setRemediationBusy(true);
    setSemanticResultsError(null);
    try {
      const decisions = migrationGaps.map((gap) => ({
        gapKey: gap.key,
        stage: gap.stage,
        severity: gap.severity,
        type: gap.type,
        detail: gap.detail,
        resolution: gap.resolution,
        asset: gap.asset,
        disposition: gapDecisions[gap.key]?.disposition ?? 'defer',
        notes: gapDecisions[gap.key]?.notes ?? '',
      }));
      const response = await fetch(`/api/groups/${group.group_id}/remediation`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ decisions }),
      });
      const payload = (await response.json()) as {
        dashboardPrompt?: string;
        metricPrompt?: string;
        agentPrompt?: string;
        error?: string;
        detail?: string;
      };
      if (!response.ok || !payload.dashboardPrompt || !payload.metricPrompt || !payload.agentPrompt) {
        throw new Error(
          [payload.error, payload.detail].filter(Boolean).join(' ') || 'Remediation package is incomplete.'
        );
      }
      setRemediationPackage({
        dashboardPrompt: payload.dashboardPrompt,
        metricPrompt: payload.metricPrompt,
        agentPrompt: payload.agentPrompt,
      });
    } catch (error) {
      setSemanticResultsError(error instanceof Error ? error.message : 'Remediation package could not be created.');
    } finally {
      setRemediationBusy(false);
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
      if (
        payload.detail?.includes('uses local paths') ||
        payload.detail?.includes('Prepare the import package again')
      ) {
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
            {datasourceFields.length} datasource fields to review · {detail.mappingContract.kpis?.length ?? 0} workbook
            calculations and {detail.mappingContract.workbook_helpers?.length ?? 0} helper fields cataloged separately
          </p>
        </div>
      </CardHeader>
      <CardContent className="mapping-workspace-content">
        <nav className="group-workflow" aria-label={`${group.display_name} workflow`}>
          {[
            { id: 'mappings' as const, number: 3, label: 'Review mappings', disabled: false },
            { id: 'build' as const, number: 4, label: 'Build assets', disabled: false },
            {
              id: 'validate' as const,
              number: 5,
              label: 'Review results',
              disabled: semanticRun?.resultState !== 'SUCCESS',
            },
            {
              id: 'promote' as const,
              number: 6,
              label: 'Promote',
              disabled: !semanticResults?.audit.status?.startsWith('COMPLETE'),
            },
          ].map((stage) => (
            <button
              className={
                groupStage === stage.id ? 'group-workflow__step group-workflow__step--active' : 'group-workflow__step'
              }
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
              <Badge
                className={reviewMode === 'datasources' ? 'mapping-tab-count--active' : undefined}
                variant="outline"
              >
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
              <Badge
                className={reviewMode === 'relationships' ? 'mapping-tab-count--active' : undefined}
                variant="outline"
              >
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
                condition, then add any as-of predicates and current-record filters required by the target grains. Apply
                the relationship to remove the approval blocker. The approved mapping YAML is updated automatically.
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
              {(detail.mappingContract.relationships?.length ?? 0) === 0 ? (
                <p>No source relationships were found.</p>
              ) : null}
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
              <Button variant="outline" onClick={() => void openImportPackage()}>
                Open mapping package
              </Button>
            </div>
          ) : (
            <Button onClick={() => void approveMappings()} disabled={approvalBusy || totalBlockingCount > 0}>
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
            <p>
              Run Dashboard Import first. When it succeeds, run Semantic Build to create and validate the Metric View
              and Genie Agent.
            </p>
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
              <div className="workflow-job-title">
                <span>1</span>
                <div>
                  <strong>Dashboard Import</strong>
                  <p>Convert this workbook group with `/importBI`.</p>
                </div>
              </div>
              <div className="workflow-job-actions">
                {importPackage?.jobSetup.jobs[0]?.jobUrl ? (
                  <a
                    className="job-run-link"
                    href={importPackage.jobSetup.jobs[0].jobUrl ?? undefined}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open Job <ExternalLink aria-hidden="true" />
                  </a>
                ) : null}
                {dashboardRun?.runUrl ? (
                  <a className="job-run-link" href={dashboardRun.runUrl} target="_blank" rel="noreferrer">
                    View run <ExternalLink aria-hidden="true" />
                  </a>
                ) : null}
                <Button
                  onClick={() => void startDashboardImport()}
                  disabled={dashboardRunBusy || approvalStatus !== 'approved'}
                >
                  {dashboardRunBusy ? 'Starting…' : dashboardRun ? 'Run again' : 'Run Dashboard Import'}
                </Button>
              </div>
            </div>
            {importPackage?.jobSetup.jobs[0]?.tasks.map((task) => (
              <JobPrompt key={task.taskKey} task={task} />
            ))}
            {dashboardRun ? (
              <JobRunSummary run={dashboardRun} runningLabel="Import is running" />
            ) : (
              <p className="workflow-job-empty">Approve the mappings, then run Dashboard Import.</p>
            )}
          </section>
          <section className="workflow-job">
            <div className="workflow-job-heading">
              <div className="workflow-job-title">
                <span>2</span>
                <div>
                  <strong>Semantic Build</strong>
                  <p>Create the Metric View, validate it, then create the Genie Agent.</p>
                </div>
              </div>
              <div className="workflow-job-actions">
                {importPackage?.jobSetup.jobs[1]?.jobUrl ? (
                  <a
                    className="job-run-link"
                    href={importPackage.jobSetup.jobs[1].jobUrl ?? undefined}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open Job <ExternalLink aria-hidden="true" />
                  </a>
                ) : null}
                {semanticRun?.runUrl ? (
                  <a className="job-run-link" href={semanticRun.runUrl} target="_blank" rel="noreferrer">
                    View run <ExternalLink aria-hidden="true" />
                  </a>
                ) : null}
                <Button
                  onClick={() => void startSemanticWorkflow()}
                  disabled={semanticRunBusy || dashboardRun?.resultState !== 'SUCCESS'}
                >
                  {semanticRunBusy ? 'Starting…' : semanticRun ? 'Run again' : 'Run Semantic Build'}
                </Button>
              </div>
            </div>
            {importPackage?.jobSetup.jobs[1]?.tasks.map((task) => (
              <JobPrompt key={task.taskKey} task={task} />
            ))}
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
                  <MetricViewName
                    fullName={
                      semanticResults.metricView.metric_view_fqn ?? semanticResults.manifest.candidate_metric_view_fqn
                    }
                    exists={Boolean(semanticResults.metricView.metric_view_fqn)}
                  />
                  <p>
                    {semanticResults.metricView.measure_count ?? '—'} measures ·{' '}
                    {semanticResults.metricView.dimension_count ?? '—'} dimensions
                  </p>
                  {semanticResults.links?.metricView ? (
                    <a
                      className="job-run-link"
                      href={semanticResults.links.metricView}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open Metric View <ExternalLink aria-hidden="true" />
                    </a>
                  ) : null}
                </section>
                <section className="workflow-job">
                  <Badge variant="outline">{semanticResults.agent.status ?? 'UNKNOWN'}</Badge>
                  <h4>Genie Agent</h4>
                  <strong>{semanticResults.agent.genie_agent?.name}</strong>
                  <p>
                    Space ID: <code>{semanticResults.agent.genie_agent?.space_id}</code>
                  </p>
                  {semanticResults.links?.genieAgent ? (
                    <a
                      className="job-run-link"
                      href={semanticResults.links.genieAgent}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open Genie Agent <ExternalLink aria-hidden="true" />
                    </a>
                  ) : null}
                </section>
                <section className="workflow-job">
                  <Badge variant="outline">{semanticResults.audit.status ?? 'UNKNOWN'}</Badge>
                  <h4>Migration gaps</h4>
                  <strong>{migrationGaps.filter((gap) => gap.severity !== 'info').length} require review</strong>
                  <p>
                    {migrationGaps.filter((gap) => gap.severity === 'high').length} high ·{' '}
                    {migrationGaps.filter((gap) => gap.severity === 'medium').length} medium ·{' '}
                    {migrationGaps.filter((gap) => gap.severity === 'low').length} low
                  </p>
                </section>
              </div>
              <section className="workflow-job">
                <div className="section-heading">
                  <div>
                    <h4>Migrated dashboards</h4>
                    <p>Open each reconciled AI/BI dashboard in the workspace.</p>
                  </div>
                  <Badge variant="outline">{semanticResults.dashboardSummary.dashboards?.length ?? 0}</Badge>
                </div>
                <div className="semantic-dashboard-links">
                  {semanticResults.dashboardSummary.dashboards?.map((dashboard) => (
                    <a
                      className="job-run-link"
                      href={dashboard.url ?? undefined}
                      target="_blank"
                      rel="noreferrer"
                      key={dashboard.dashboard_id}
                    >
                      {dashboard.display_name ?? dashboard.workbook_name ?? dashboard.dashboard_id}
                      <ExternalLink aria-hidden="true" />
                    </a>
                  ))}
                </div>
              </section>
              {migrationGaps.length ? (
                <section className="workflow-job">
                  <h4>Migration gaps to review</h4>
                  <p>
                    Gaps identified while creating dashboards, consolidating the Metric View, and configuring the Genie
                    Agent.
                  </p>
                  <div className="benchmark-findings">
                    {migrationGaps.map((gap) => (
                      <article key={gap.key}>
                        <Badge variant="outline">{gap.severity}</Badge>
                        <strong>
                          {gap.stage}: {gap.type.replaceAll('_', ' ')}
                        </strong>
                        <p>
                          {gap.asset ? `${gap.asset}: ` : ''}
                          {gap.detail}
                        </p>
                        {gap.resolution ? <small>Resolution: {gap.resolution}</small> : null}
                        <div className="gap-decision">
                          <label>
                            <span>Disposition</span>
                            <select
                              value={gapDecisions[gap.key]?.disposition ?? 'defer'}
                              onChange={(event) =>
                                setGapDecisions((current) => ({
                                  ...current,
                                  [gap.key]: {
                                    notes: current[gap.key]?.notes ?? '',
                                    disposition: event.target.value as
                                      | 'fix_now'
                                      | 'accept'
                                      | 'defer'
                                      | 'not_applicable',
                                  },
                                }))
                              }
                            >
                              <option value="fix_now">Fix now</option>
                              <option value="accept">Accept limitation</option>
                              <option value="defer">Defer</option>
                              <option value="not_applicable">Not applicable</option>
                            </select>
                          </label>
                          <label>
                            <span>Reviewer note</span>
                            <input
                              value={gapDecisions[gap.key]?.notes ?? ''}
                              onChange={(event) =>
                                setGapDecisions((current) => ({
                                  ...current,
                                  [gap.key]: {
                                    disposition: current[gap.key]?.disposition ?? 'defer',
                                    notes: event.target.value,
                                  },
                                }))
                              }
                              placeholder="Decision rationale or repair instruction"
                            />
                          </label>
                        </div>
                      </article>
                    ))}
                  </div>
                  <div className="workflow-job-actions">
                    <Button onClick={() => void prepareRemediation()} disabled={remediationBusy}>
                      {remediationBusy ? 'Preparing…' : 'Prepare targeted repairs'}
                    </Button>
                  </div>
                </section>
              ) : null}
              {remediationPackage ? (
                <section className="workflow-job">
                  <h4>Targeted repair prompts</h4>
                  <p>
                    Run only the stages with approved fixes. Dashboard repair updates existing dashboard IDs and never
                    invokes `/importBI`.
                  </p>
                  <JobPrompt task={{ taskKey: 'repair_dashboards', prompt: remediationPackage.dashboardPrompt }} />
                  <JobPrompt task={{ taskKey: 'repair_metric_view', prompt: remediationPackage.metricPrompt }} />
                  <JobPrompt task={{ taskKey: 'repair_genie_agent', prompt: remediationPackage.agentPrompt }} />
                </section>
              ) : null}
              <div className="workflow-job-actions">
                <Button variant="outline" onClick={() => void loadSemanticResults()}>
                  Refresh results
                </Button>
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
                Keeping the current names accepts the created assets as final. Different names create an approved
                pending rename request; this step does not silently copy or rename governed assets.
              </AlertDescription>
            </Alert>
            <div className="workflow-job-actions">
              <Button
                onClick={() => void savePromotion()}
                disabled={promotionBusy || !finalMetricViewFqn || !finalAgentName}
              >
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
              <DialogDescription>
                Copy the executable Job prompt. Rendered Volume prompts are read-only references.
              </DialogDescription>
            </DialogHeader>
            <div className="import-package-content">
              <p className="package-setup-note">{importPackage?.jobSetup.instructions}</p>
              <section className="package-step">
                <div className="package-step__heading">
                  <div>
                    <span>1</span>
                    <h3>Dashboard migration</h3>
                  </div>
                  {importPackage?.jobSetup.jobs[0]?.jobUrl ? (
                    <a
                      className="job-run-link"
                      href={importPackage.jobSetup.jobs[0].jobUrl ?? undefined}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open Dashboard Import Job <ExternalLink aria-hidden="true" />
                    </a>
                  ) : null}
                </div>
                {importPackage?.jobSetup.jobs[0]?.tasks.map((task) => (
                  <JobPrompt key={task.taskKey} task={task} />
                ))}
                <ReferencePrompt
                  label="Rendered dashboard reference"
                  path={importPackage?.session1PromptPath}
                  prompt={importPackage?.prompt}
                />
              </section>
              <section className="package-step">
                <div className="package-step__heading">
                  <div>
                    <span>2</span>
                    <h3>Metric View</h3>
                  </div>
                  {importPackage?.jobSetup.jobs[1]?.jobUrl ? (
                    <a
                      className="job-run-link"
                      href={importPackage.jobSetup.jobs[1].jobUrl ?? undefined}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open Semantic Build Job <ExternalLink aria-hidden="true" />
                    </a>
                  ) : null}
                </div>
                {importPackage?.jobSetup.jobs[1]?.tasks
                  .filter((task) => task.taskKey === 'build_metric_view')
                  .map((task) => (
                    <JobPrompt key={task.taskKey} task={task} />
                  ))}
                <ReferencePrompt
                  label="Rendered Metric View reference"
                  path={importPackage?.metricViewPromptPath}
                  prompt={importPackage?.metricViewPrompt}
                />
              </section>
              <section className="package-step">
                <div className="package-step__heading">
                  <div>
                    <span>3</span>
                    <h3>Genie Agent</h3>
                  </div>
                  {importPackage?.jobSetup.jobs[1]?.jobUrl ? (
                    <a
                      className="job-run-link"
                      href={importPackage.jobSetup.jobs[1].jobUrl ?? undefined}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open Semantic Build Job <ExternalLink aria-hidden="true" />
                    </a>
                  ) : null}
                </div>
                {importPackage?.jobSetup.jobs[1]?.tasks
                  .filter((task) => task.taskKey === 'build_genie_agent')
                  .map((task) => (
                    <JobPrompt key={task.taskKey} task={task} />
                  ))}
                <ReferencePrompt
                  label="Rendered Genie Agent reference"
                  path={importPackage?.genieAgentPromptPath}
                  prompt={importPackage?.genieAgentPrompt}
                />
              </section>
              <section className="package-contract">
                <h3>Approved mapping contract</h3>
                <details className="job-prompt">
                  <summary>
                    <span>{importPackage?.mappingFileName}</span>
                    <Badge variant="outline">YAML</Badge>
                  </summary>
                  <div className="job-prompt__content">
                    <pre>{importPackage?.contractYaml}</pre>
                    <div className="mapping-draft-action">
                      <CopyButton value={importPackage?.contractYaml ?? ''} label="Copy YAML" />
                      <Button size="sm" onClick={downloadContract}>
                        Download YAML
                      </Button>
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
        <span>
          {run.resultState || runningLabel} · Run {run.databricksRunId}
        </span>
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
  const targetTables = Array.from(
    new Set(fields.map((field) => field.target_table).filter(Boolean) as string[])
  ).sort();
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
        <text className="mapping-graph__column-title" x="40" y="28">
          Source
        </text>
        <text className="mapping-graph__column-title" x="700" y="28">
          Databricks target
        </text>
        {Array.from(mappingEdges.values()).map((edge) => {
          const startY = (sourceY.get(edge.source) ?? 0) + 23;
          const endY = (targetY.get(edge.target) ?? 0) + 23;
          return (
            <g key={`${edge.source}-${edge.target}`}>
              <path
                className={
                  edge.unresolved ? 'mapping-graph__edge mapping-graph__edge--unresolved' : 'mapping-graph__edge'
                }
                d={`M 280 ${startY} C 430 ${startY}, 560 ${endY}, 700 ${endY}`}
              />
              <text className="mapping-graph__edge-label" x="490" y={(startY + endY) / 2 - 4}>
                {edge.count} fields
              </text>
            </g>
          );
        })}
        {relationships.flatMap((relationship, index) => {
          const left =
            relationship.target.left_table_candidates.length === 1 ? relationship.target.left_table_candidates[0] : '';
          const right =
            relationship.target.right_table_candidates.length === 1
              ? relationship.target.right_table_candidates[0]
              : '';
          if (!targetY.has(left) || !targetY.has(right)) return [];
          const leftY = (targetY.get(left) ?? 0) + 46;
          const rightY = targetY.get(right) ?? 0;
          return [
            <path
              key={`relationship-${index}`}
              className={`mapping-graph__relationship mapping-graph__relationship--${relationship.status}`}
              d={`M 940 ${leftY} C 980 ${leftY}, 980 ${rightY}, 940 ${rightY}`}
            >
              <title>{relationship.target.condition}</title>
            </path>,
          ];
        })}
        {sourceTables.map((table) => (
          <g key={table} transform={`translate(40 ${sourceY.get(table)})`}>
            <rect className="mapping-graph__node mapping-graph__node--source" width="240" height="46" rx="6" />
            <text x="12" y="28">
              <title>{table}</title>
              {shortName(table)}
            </text>
          </g>
        ))}
        {targetTables.map((table) => (
          <g key={table} transform={`translate(700 ${targetY.get(table)})`}>
            <rect className="mapping-graph__node mapping-graph__node--target" width="240" height="46" rx="6" />
            <text x="12" y="28">
              <title>{table}</title>
              {shortName(table)}
            </text>
          </g>
        ))}
      </svg>
      <div className="mapping-graph__legend">
        <span>Field mapping</span>
        <span>Target relationship</span>
        <span>Red requires review</span>
      </div>
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
  const [leftTable, setLeftTable] = useState(
    relationship.target.left_table_candidates.length === 1 ? relationship.target.left_table_candidates[0] : ''
  );
  const [rightTable, setRightTable] = useState(
    relationship.target.right_table_candidates.length === 1 ? relationship.target.right_table_candidates[0] : ''
  );
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
        temporalPredicates: temporalPredicates
          .split('\n')
          .map((value) => value.trim())
          .filter(Boolean),
        recordFilters: recordFilters
          .split('\n')
          .map((value) => value.trim())
          .filter(Boolean),
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
        <div>
          <h3>
            {relationship.source.left_table || 'Source table'} → {relationship.source.right_table}
          </h3>
          <p>{relationship.source.condition || 'Source join condition unavailable'}</p>
        </div>
        <Badge variant="outline">{saved ? 'Updated' : relationship.status}</Badge>
      </div>
      <div className="relationship-editor-grid">
        <label>
          Left Databricks table
          <select value={leftTable} onChange={(event) => setLeftTable(event.target.value)}>
            <option value="">Select table</option>
            {targetTables.map((table) => (
              <option key={table}>{table}</option>
            ))}
          </select>
        </label>
        <label>
          Right Databricks table
          <select value={rightTable} onChange={(event) => setRightTable(event.target.value)}>
            <option value="">Select table</option>
            {targetTables.map((table) => (
              <option key={table}>{table}</option>
            ))}
          </select>
        </label>
        <label>
          Join type
          <select value={joinType} onChange={(event) => setJoinType(event.target.value)}>
            {['inner', 'left', 'right', 'full', 'relationship'].map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <label>
          Grain / cardinality
          <select value={cardinality} onChange={(event) => setCardinality(event.target.value)}>
            {['one_to_one', 'one_to_many', 'many_to_one', 'many_to_many', 'unknown'].map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <label className="relationship-editor-grid__wide">
          Target join condition
          <input value={condition} onChange={(event) => setCondition(event.target.value)} />
        </label>
        <label className="relationship-editor-grid__wide">
          Temporal predicates
          <textarea
            value={temporalPredicates}
            onChange={(event) => setTemporalPredicates(event.target.value)}
            placeholder="One predicate per line"
          />
        </label>
        <label className="relationship-editor-grid__wide">
          Current-record filters
          <textarea
            value={recordFilters}
            onChange={(event) => setRecordFilters(event.target.value)}
            placeholder="One filter per line"
          />
        </label>
      </div>
      <div className="relationship-card__actions">
        <Button
          size="sm"
          onClick={() => void save()}
          disabled={!leftTable || !rightTable || !condition || cardinality === 'unknown' || saveState === 'saving'}
        >
          {saveState === 'saving' ? 'Applying…' : 'Apply relationship'}
        </Button>
        {cardinality === 'unknown' ? <span>Choose the target grain/cardinality to continue.</span> : null}
        {saveState === 'error' ? <span>Update failed</span> : null}
      </div>
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
