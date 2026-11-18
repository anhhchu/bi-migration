import { createApp, files, getExecutionContext, jobs, server } from '@databricks/appkit';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { parse as parseYaml } from 'yaml';
import { stringify as stringifyYaml } from 'yaml';
import { z } from 'zod';
import type { Request } from 'express';

type GroupSummary = {
  group_id: string;
  coverage_signature: string;
  assets: string[];
  field_count: number;
  mapped_fields: number;
  unresolved_fields: number;
  mapping_percentage: number;
  contract_status: string;
  ready: boolean;
  output_path: string;
};

type SemanticGroup = {
  group_id: string;
  assets: string[];
  shared_dependencies: string[];
  dependencies: string[];
  similarity_edges?: Array<{
    left: string;
    right: string;
    shared_field_count: number;
    jaccard: number;
    containment: number;
  }>;
  coverage_signature: string;
};

type SourceAsset = {
  asset_id: string;
  source_file: string;
  dashboards: Array<{ name: string }>;
  worksheets: Array<unknown>;
  datasources: Array<unknown>;
};

const projectRoot = path.resolve(process.cwd(), '../..');
let activeMigrationName = process.env.BI_MIGRATION_NAME ?? 'superstore-migration';
const defaultTargetCatalog = process.env.BI_MIGRATION_TARGET_CATALOG ?? 'main';
const defaultTargetSchema = process.env.BI_MIGRATION_TARGET_SCHEMA ?? 'superstore';
const volumeRoot = process.env.DATABRICKS_VOLUME_FILES?.replace(/\/$/, '') ?? '';
let activeVolumeRoot = volumeRoot;
const namespaceSchema = z.string().min(1).max(255);
const migrationNameSchema = z.string().trim().min(2).max(64).transform((value) =>
  value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
).refine(Boolean, 'Enter a migration name using letters or numbers.');
const uploadExtensions = new Set(['.twb', '.twbx', '.csv', '.json', '.yaml', '.yml', '.md']);
const mappingUpdateSchema = z.object({
  corpusId: z.enum(['downloaded', 'synthetic', 'uploaded']),
  datasource: z.string().min(1),
  legacy: z.string().min(1),
  targetTable: z.string().min(1),
  targetExpression: z.string().min(1),
  conversion: z.enum(['direct', 'renamed', 'calculated', 'joined', 'temporal', 'skipped', 'redesign']),
});
const relationshipUpdateSchema = z.object({
  corpusId: z.literal('uploaded'),
  relationshipIndex: z.number().int().nonnegative(),
  leftTable: z.string().min(1),
  rightTable: z.string().min(1),
  joinType: z.enum(['inner', 'left', 'right', 'full', 'relationship']),
  condition: z.string().min(1),
  cardinality: z.enum(['one_to_one', 'one_to_many', 'many_to_one', 'many_to_many', 'unknown']),
  temporalPredicates: z.array(z.string()),
  recordFilters: z.array(z.string()),
});

const SESSION_1_PROMPT_VERSION = '1.1.0';
const METRIC_VIEW_PROMPT_VERSION = '1.1.0';
const GENIE_AGENT_PROMPT_VERSION = '1.1.0';
const JOB_TASK_PROMPTS = {
  importDashboard: [
    '/importBI',
    '',
    'Migrate this Tableau workbook:',
    '`{{input.workbook_path}}`',
    '',
    'Use this approved mapping contract as authoritative context:',
    '`{{input.approved_mapping_path}}`',
    '',
    'Requirements:',
    '- Import this workbook only.',
    '- Use only physical Databricks targets declared in the contract.',
    '- Do not substitute compatibility views or unrelated tables.',
    '- Apply approved datasource mappings and relationship rules before deriving calculations or UI behavior.',
    '- Include this tag exactly once in the dashboard display name:',
    '  `{{input.dashboard_tag}}`',
    '- A Databricks-generated timestamp elsewhere in the display name is acceptable; do not spend time removing it.',
    '- Record unsupported features, degraded behavior, and validation gaps.',
    '- Do not invent missing data, joins, calculations, or mappings.',
  ].join('\n'),
  buildMetricView: [
    '# Genie Code — Build and validate a governed Metric View',
    '',
    '- Run ID: `{{run_id}}`',
    '- Semantic group: `{{group_id}}`',
    '- Group run directory: `{{group_run_path}}`',
    '',
    'Read `{{group_run_path}}/group-migration-manifest.json` to resolve the approved mapping contract, dashboard import summary, dashboard configuration directory, KPI inventory, target Metric View FQN, and semantic artifact directory.',
    '',
    'Requirements:',
    '1. Confirm every dashboard import completed successfully; identify and record partial imports.',
    '2. Inspect the approved datasource mappings, relationships, grains, temporal rules, dashboard configurations, calculations, filters, parameters, formats, widget queries, and local Metric Views created by `/importBI`.',
    '3. Consolidate reusable business dimensions and KPIs across the dashboards.',
    '4. Resolve Tableau calculation dependencies before translating KPIs.',
    '5. Treat the approved mapping as authoritative for physical tables, joins, grain, and bitemporal behavior.',
    '6. Merge measures only when formula, aggregation, grain, filters, units, and temporal semantics are compatible.',
    '7. Exclude UI-only helpers, layout calculations, unsupported calculations, and ambiguous business logic.',
    '8. Do not invent fields, joins, data, formulas, currency, or temporal rules.',
    '9. Create or replace only the candidate Metric View declared in the manifest. Do not overwrite a promoted Metric View.',
    '10. Add comments, display names, formats, and synonyms when supported by evidence.',
    '11. Run basic `MEASURE()` queries and validate that joins preserve the declared fact grain.',
    '12. Write dashboard-semantic-inventory.json, cross-dashboard-metric-matrix.json, metric-view-proposal.yaml, metric-view-result.json, and metric-view-exceptions.json beneath the semantic artifact directory.',
    '',
    'Fail if no valid Metric View can be created. Otherwise report SUCCESS or PARTIAL with explicit unresolved items. Do not create a Genie Agent in this task.',
  ].join('\n'),
  buildGenieAgent: [
    '# Genie Code — Create and evaluate a governed Genie Agent',
    '',
    '- Run ID: `{{run_id}}`',
    '- Semantic group: `{{group_id}}`',
    '- Group run directory: `{{group_run_path}}`',
    '',
    'Read `{{group_run_path}}/group-migration-manifest.json` to resolve the validated Metric View FQN, dashboard configuration directory, Genie Agent name, and semantic artifact directory. Read the Metric View validation artifact first and stop unless its status is PASS.',
    '',
    'Requirements:',
    '1. Use the validated Metric View as the Agent\'s only governed data source.',
    '2. Inspect dashboard titles, descriptions, filters, parameters, visualizations, and KPI usage to derive business context.',
    '3. Configure concise business instructions, relevant synonyms, and 5–8 visible sample questions.',
    '4. Add at least 12 benchmark questions to the Agent evaluation configuration.',
    '5. Each benchmark must include its expected metric, dimensions, filters, time grain, and validation SQL or deterministic answer rule.',
    '6. Keep benchmark questions distinct from visible sample questions and ordinary conversation context.',
    '7. Remove or flag questions requiring unsupported, skipped, or ambiguous dashboard logic.',
    '8. Execute the benchmark set and record answerability and SQL-generation results.',
    '9. Write genie-agent-result.json, benchmark-results.json, and unresolved-agent-items.json beneath the semantic artifact directory.',
    '',
    'Fail if the Agent cannot be created. Otherwise report SUCCESS or PARTIAL with explicit benchmark failures.',
  ].join('\n'),
};

function jobSetup() {
  const workspaceUrl = (process.env.DATABRICKS_WORKSPACE_URL || process.env.DATABRICKS_HOST)?.replace(/\/$/, '');
  const dashboardJobId = process.env.DATABRICKS_JOB_DASHBOARD_IMPORT;
  const semanticJobId = process.env.DATABRICKS_JOB_SEMANTIC;
  return {
    instructions: 'In Dashboard Import, open the import_dashboards For each task and change its nested import_dashboard placeholder to Genie Code. Paste the prompt and save. Configure the two Semantic Build placeholders the same way.',
    jobs: [
      {
        label: 'Dashboard Import',
        jobId: dashboardJobId,
        jobUrl: workspaceUrl && dashboardJobId ? `${workspaceUrl}/jobs/${dashboardJobId}` : null,
        tasks: [{ taskKey: 'import_dashboard', prompt: JOB_TASK_PROMPTS.importDashboard }],
      },
      {
        label: 'Semantic Build',
        jobId: semanticJobId,
        jobUrl: workspaceUrl && semanticJobId ? `${workspaceUrl}/jobs/${semanticJobId}` : null,
        tasks: [
          { taskKey: 'build_metric_view', prompt: JOB_TASK_PROMPTS.buildMetricView },
          { taskKey: 'build_genie_agent', prompt: JOB_TASK_PROMPTS.buildGenieAgent },
        ],
      },
    ],
  };
}

function sha256(value: string) {
  return createHash('sha256').update(value).digest('hex');
}

function renderMetricViewPrompt(input: {
  runId: string;
  groupId: string;
  approvedMappingPath: string;
  dashboardManifestPath: string;
  dashboardConfigDirectory: string;
  kpiInventoryPath: string;
  metricViewFqn: string;
  artifactDirectory: string;
}) {
  return [
    '# Genie Code — Build candidate Metric View',
    '',
    'You are running after `/importBI` completed in Session 1. Do not recreate or modify the dashboards.',
    '',
    '## Inputs',
    `- Run ID: ${input.runId}`,
    `- Semantic group: ${input.groupId}`,
    `- Approved mapping contract: ${input.approvedMappingPath}`,
    `- Session 1 dashboard manifest: ${input.dashboardManifestPath}`,
    `- Extracted dashboard configurations: ${input.dashboardConfigDirectory}`,
    `- KPI inventory: ${input.kpiInventoryPath}`,
    `- Candidate UC Metric View: ${input.metricViewFqn}`,
    `- Output artifact directory: ${input.artifactDirectory}`,
    '',
    '## Objective',
    '',
    'Inspect the persisted dashboard configurations and local Metric Views created by `/importBI`. Reconcile them with the approved field, relationship, grain, and temporal mappings. Create only the candidate governed UC Metric View.',
    '',
    '## Requirements',
    '',
    '1. Fail clearly if a dashboard ID, dashboard configuration, approved mapping, or KPI inventory is missing.',
    '2. Inventory datasets, local Metric Views, dimensions, measures, joins, filters, parameters, formats, and widget queries from every dashboard configuration.',
    '3. Treat the approved mapping contract as authoritative for physical tables, joins, grain, and bitemporal behavior.',
    '4. Merge measures only when formula, aggregation, grain, filters, units, and temporal semantics are compatible.',
    '5. Record every conflict or exclusion. Never invent fields, joins, return data, formulas, currency, or temporal rules.',
    `6. Create or replace the candidate Metric View ${input.metricViewFqn}; do not overwrite an existing promoted Metric View.`,
    '7. Add comments, display names, formats, and synonyms when supported by extracted evidence.',
    '8. Run basic `MEASURE()` queries, but leave the authoritative validation decision to the downstream deterministic notebook.',
    '',
    '## Required Outputs',
    '',
    `Write structured outputs beneath ${input.artifactDirectory}:`,
    '- dashboard-semantic-inventory.json',
    '- cross-dashboard-metric-matrix.json',
    '- metric-view-proposal.yaml',
    '- metric-view-result.json',
    '- metric-view-exceptions.json',
    '',
    'Return the Metric View FQN, metric disposition counts, creation status, and unresolved exceptions.',
  ].join('\n');
}

function renderGenieAgentPrompt(input: {
  runId: string;
  groupId: string;
  metricViewFqn: string;
  metricViewValidationPath: string;
  dashboardConfigDirectory: string;
  agentName: string;
  artifactDirectory: string;
}) {
  return [
    '# Genie Code — Create governed Genie Agent',
    '',
    `- Run ID: ${input.runId}`,
    `- Semantic group: ${input.groupId}`,
    `- Validated Metric View: ${input.metricViewFqn}`,
    `- Metric View validation: ${input.metricViewValidationPath}`,
    `- Dashboard configurations: ${input.dashboardConfigDirectory}`,
    `- Genie Agent name: ${input.agentName}`,
    `- Output artifact directory: ${input.artifactDirectory}`,
    '',
    'Read the validation artifact first and stop if its status is not PASS.',
    `Create the Genie Agent named ${input.agentName} using ${input.metricViewFqn} as its only governed data source.`,
    'Configure concise business instructions and 5–8 visible sample questions derived from the dashboard configurations.',
    'Add at least 12 benchmark questions to the Genie Agent benchmark/evaluation configuration. Each benchmark must include its expected metric, dimensions, filters, time grain, and validation SQL or deterministic answer rule.',
    'Benchmarks must be registered with the Agent but remain distinct from visible sample questions and ordinary conversation context.',
    'Write genie-agent-result.json containing the Agent/Space ID, Metric View FQN, visible sample questions, the complete benchmark configuration, status, and exceptions.',
    'Do not create the Agent if Metric View validation failed, and do not add any other table or Metric View.',
  ].join('\n');
}

function groupingReason(group: SemanticGroup) {
  if (group.assets.length === 1) {
    return 'This workbook forms its own group because the inventory found no reusable datasource or table dependency shared with another workbook in this run.';
  }
  if (group.similarity_edges?.length) {
    const strongest = [...group.similarity_edges].sort(
      (left, right) => right.shared_field_count - left.shared_field_count
    )[0];
    return `These ${group.assets.length} workbooks are grouped because their packaged local extracts share a strong physical schema: up to ${strongest.shared_field_count} fields with ${Math.round(strongest.jaccard * 100)}% field-set overlap. Their opaque extract names are not used as business identifiers.`;
  }
  const sharedCount = group.shared_dependencies.length;
  return `These ${group.assets.length} workbooks are grouped because they are connected by ${sharedCount} shared datasource or table ${sharedCount === 1 ? 'dependency' : 'dependencies'}.`;
}

function groupDisplayName(group: SemanticGroup) {
  if (group.assets.length === 1) {
    const name = group.assets[0].replace(/[_-]+/g, ' ').trim();
    return `${name.charAt(0).toUpperCase()}${name.slice(1)}`;
  }
  return `${group.assets[0]} and ${group.assets.length - 1} related workbooks`;
}

function groupDirectoryName(group: SemanticGroup) {
  const ignoredWords = new Set([
    'analytics',
    'dashboard',
    'dashboards',
    'insight',
    'insights',
    'report',
    'reports',
    'sample',
    'tableau',
    'workbook',
    'workbooks',
  ]);
  const tokensFor = (asset: string) =>
    asset
      .replace(/([a-z])([A-Z])/g, '$1 $2')
      .toLowerCase()
      .replace(/superstores?/g, 'super store')
      .replace(/[^a-z0-9]+/g, ' ')
      .trim()
      .split(/\s+/)
      .map((token) => (token === 'stores' ? 'store' : token))
      .filter((token) => token.length > 2 && !ignoredWords.has(token));
  const tokenCounts = new Map<string, number>();
  for (const asset of group.assets) {
    for (const token of new Set(tokensFor(asset))) {
      tokenCounts.set(token, (tokenCounts.get(token) ?? 0) + 1);
    }
  }
  const requiredCount = Math.max(2, Math.ceil(group.assets.length * 0.75));
  const firstAssetTokens = [...new Set(tokensFor(group.assets[0] ?? ''))];
  const sharedTokens = firstAssetTokens
    .filter((token) => (tokenCounts.get(token) ?? 0) >= requiredCount)
    .slice(0, 3)
  const fallbackTokens = firstAssetTokens.slice(0, 3);
  return (sharedTokens.length ? sharedTokens : fallbackTokens).join('-').slice(0, 40) || group.group_id;
}

let processingStatus: 'idle' | 'running' | 'complete' | 'failed' = 'idle';
let processingMessage = '';
let inventoryRunId: number | null = null;

await createApp({
  plugins: [
    server(),
    files({
      maxUploadSize: 100 * 1024 * 1024,
      volumes: {
        files: {
          auth: 'on-behalf-of-user',
          policy: files.policy.allowAll(),
        },
      },
    }),
    jobs({
      jobs: {
        inventory: {
          taskType: 'notebook',
          params: z.object({
            input_path: z.string().startsWith('/Volumes/'),
            mapping_docs_path: z.string().startsWith('/Volumes/'),
            target_metadata_path: z.string().startsWith('/Volumes/'),
            output_path: z.string().startsWith('/Volumes/'),
            run_id: z.string().min(1),
            source_base_uri: z.string().startsWith('/Volumes/'),
          }),
        },
        semantic: {
          params: z.object({
            job_parameters: z.object({
              run_id: z.string().min(1),
              group_id: z.string().regex(/^group-\d{3}$/),
              group_run_path: z.string().startsWith('/Volumes/'),
              requested_by: z.string().min(1),
            }),
          }),
        },
        dashboard_import: {
          params: z.object({
            job_parameters: z.object({
              run_id: z.string().min(1),
              group_id: z.string().regex(/^group-\d{3}$/),
              group_run_path: z.string().startsWith('/Volumes/'),
              requested_by: z.string().min(1),
            }),
          }),
        },
      },
    }),
  ],
  onPluginsReady(appkit) {
    appkit.server.extend((app) => {
      const volumeHandle = (request: Request) =>
        process.env.NODE_ENV === 'development' ? appkit.files('files') : appkit.files('files').asUser(request);
      const volumePathFromName = (name: string) =>
        /^([A-Za-z_][\w-]*)\.([A-Za-z_][\w-]*)\.([A-Za-z_][\w-]*)$/.test(name)
          ? `/Volumes/${name.split('.').join('/')}`
          : '';
      const volumeNameFromPath = (volumePath: string) => {
        const match = volumePath.match(/^\/Volumes\/([^/]+)\/([^/]+)\/([^/]+)$/);
        return match ? `${match[1]}.${match[2]}.${match[3]}` : volumePath;
      };
      const migrationRoot = (root: string) => `${root}/bi-migrations/${activeMigrationName}`;
      const uploadManifestPath = (root: string) => `${migrationRoot(root)}/control/uploads.json`;
      const slugify = (value: string) => value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 64);
      const groupWorkspacePath = async (request: Request, root: string, groupId: string) => {
        const groups = JSON.parse(await volumeHandle(request).read(`${migrationRoot(root)}/inventory/groups.json`)) as SemanticGroup[];
        const group = groups.find((item) => item.group_id === groupId);
        if (!group) return `${migrationRoot(root)}/groups/${groupId}`;
        const baseName = groupDirectoryName(group);
        const hasCollision = groups.some(
          (candidate) => candidate.group_id !== groupId && groupDirectoryName(candidate) === baseName
        );
        const directoryName = hasCollision ? `${baseName}-${group.coverage_signature.slice(0, 6)}` : baseName;
        return `${migrationRoot(root)}/groups/${slugify(directoryName) || groupId}`;
      };
      const readUploadManifest = async (request: Request, root: string) => {
        if (!root) return [];
        return volumeHandle(request)
          .read(uploadManifestPath(root))
          .then(
            (contents) =>
              JSON.parse(contents) as Array<{
                name: string;
                sizeBytes: number;
                status: string;
                kind: string;
                volumePath: string;
              }>
          )
          .catch(() => []);
      };
      app.post('/api/migration-context', (request, response) => {
        const parsed = migrationNameSchema.safeParse(request.body?.name);
        if (!parsed.success) {
          response.status(400).json({ error: parsed.error.issues[0]?.message ?? 'Enter a valid migration name.' });
          return;
        }
        activeMigrationName = parsed.data;
        processingStatus = 'idle';
        processingMessage = 'Ready to upload migration assets.';
        inventoryRunId = null;
        response.json({ name: activeMigrationName, root: activeVolumeRoot ? migrationRoot(activeVolumeRoot) : null });
      });
      app.get('/api/review', async (request, response) => {
        try {
          if (!activeVolumeRoot) throw new Error('Choose the run Volume on Upload assets first.');
          const outputRoot = `${migrationRoot(activeVolumeRoot)}/inventory`;
          const volume = volumeHandle(request);
          const readOutputJson = async <T,>(relativePath: string) =>
            JSON.parse(await volume.read(`${outputRoot}/${relativePath}`)) as T;
          const [groupSummaries, semanticGroups, manifest, inventoryErrors] = await Promise.all([
            readOutputJson<GroupSummary[]>('group_readiness.json'),
            readOutputJson<SemanticGroup[]>('groups.json'),
            readOutputJson<Array<{ status: string }>>('artifact_manifest.json'),
            readOutputJson<Array<unknown>>('inventory_errors.json'),
          ]);
          const inventories = await Promise.all(
            groupSummaries.map((group) =>
              readOutputJson<SourceAsset[]>(`groups/${group.group_id}/source_inventory.json`)
            )
          );
          const groups = groupSummaries.map((group) => ({
            ...group,
            display_name: groupDisplayName(
              semanticGroups.find((semanticGroup) => semanticGroup.group_id === group.group_id) ?? {
                ...group,
                shared_dependencies: [],
                dependencies: [],
              }
            ),
            corpus_id: 'uploaded' as const,
            corpus_label: 'User upload',
            selection_id: `uploaded:${group.group_id}`,
          }));
          response.json({
            run: {
              kind: 'test_portfolio',
              label: `Migration ${activeMigrationName}`,
              description: 'Production Volume-backed Tableau inventory and semantic migration run.',
            },
            journey: ['Inventory', 'Group', 'Map', 'Prepare package', 'Build assets', 'Validate', 'Promote'],
            groups,
            summary: {
              artifacts: manifest.length,
              workbooks: groups.reduce((total, group) => total + group.assets.length, 0),
              dashboards: inventories.reduce(
                (total, inventory) => total + inventory.reduce((count, asset) => count + asset.dashboards.length, 0),
                0
              ),
              groups: groups.length,
              readyGroups: groups.filter((group) => group.ready).length,
              mappedFields: groups.reduce((total, group) => total + group.mapped_fields, 0),
              unresolvedFields: groups.reduce((total, group) => total + group.unresolved_fields, 0),
              quarantined: manifest.filter((artifact) => artifact.status === 'quarantined').length,
              inventoryErrors: inventoryErrors.length,
            },
            groupEvidence: Object.fromEntries(
              semanticGroups.map((group) => [
                `uploaded:${group.group_id}`,
                {
                  reason: groupingReason(group),
                  dependencies: group.dependencies,
                  sharedDependencies: group.shared_dependencies,
                },
              ])
            ),
            corpora: [{ id: 'uploaded', label: 'User upload' }],
          });
        } catch (error) {
          response.status(409).json({
            error: 'No completed inventory is available for this run.',
            detail: 'Run inventory successfully before reviewing semantic groups.',
          });
        }
      });

      app.get('/api/uploads', async (request, response) => {
        const requestedVolume = typeof request.query.volume === 'string' ? volumePathFromName(request.query.volume) : '';
        const selectedVolume = requestedVolume || activeVolumeRoot;
        if (selectedVolume) activeVolumeRoot = selectedVolume;
        const files = await readUploadManifest(request, selectedVolume);
        const namespaces = new Map<string, { catalog: string; schema: string }>();
        for (const file of files.filter((item) => item.kind === 'Mapping evidence')) {
          const contents = await volumeHandle(request).read(file.volumePath).catch(() => '');
          for (const match of contents.matchAll(/\b([A-Za-z_][\w-]*)\.([A-Za-z_][\w-]*)\.([A-Za-z_][\w-]*)\b/g)) {
            const [, catalog, schema] = match;
            namespaces.set(`${catalog}.${schema}`, { catalog, schema });
          }
        }
        if (inventoryRunId && processingStatus === 'running') {
          const runResult = await appkit.jobs('inventory').getRun(inventoryRunId);
          if (runResult.ok) {
            const lifeCycleState = String(runResult.data.state?.life_cycle_state ?? '');
            const resultState = String(runResult.data.state?.result_state ?? '');
            if (lifeCycleState === 'TERMINATED') {
              processingStatus = resultState === 'SUCCESS' ? 'complete' : 'failed';
              processingMessage =
                resultState === 'SUCCESS'
                  ? `Inventory job run ${inventoryRunId} completed.`
                  : `Inventory job run ${inventoryRunId} finished with ${resultState || 'an error'}.`;
            }
          }
        }
        response.json({
          migrationName: activeMigrationName,
          migrationRoot: selectedVolume ? migrationRoot(selectedVolume) : null,
          storage: selectedVolume ? `Unity Catalog Volume: ${selectedVolume}` : 'Choose a Unity Catalog Volume',
          uploadDestination: selectedVolume
            ? { fullName: volumeNameFromPath(selectedVolume), path: selectedVolume }
            : null,
          files,
          detectedNamespaces: Array.from(namespaces.values()),
          processing: {
            status: processingStatus,
            message: processingMessage,
            runId: inventoryRunId,
            runUrl:
              inventoryRunId && process.env.DATABRICKS_WORKSPACE_URL && process.env.DATABRICKS_JOB_ID
                ? `${process.env.DATABRICKS_WORKSPACE_URL.replace(/\/$/, '')}/jobs/${process.env.DATABRICKS_JOB_ID}/runs/${inventoryRunId}`
                : null,
          },
        });
      });

      app.get('/api/docs/project-plan', async (_request, response) => {
        response.type('text/markdown').send(await readFile(path.join(projectRoot, 'PROJECT_PLAN.md'), 'utf8'));
      });

      app.get('/api/docs/mapping-guide', async (_request, response) => {
        response
          .type('text/markdown')
          .send(await readFile(path.join(projectRoot, 'skills/extract-bi-mappings/SKILL.md'), 'utf8'));
      });

      app.get('/api/session', async (request, response) => {
        try {
          const user = await appkit.asUser(request).run(async () =>
            getExecutionContext().client.currentUser.me()
          );
          response.json({
            displayName: user.displayName || user.userName || 'Databricks user',
            userName: user.userName || '',
          });
        } catch {
          response.json({ displayName: 'Signed-in Databricks user', userName: '' });
        }
      });

      app.get('/api/uploads/:fileName/content', async (request, response) => {
        const fileName = request.params.fileName;
        const extension = path.extname(fileName).toLowerCase();
        if (
          path.basename(fileName) !== fileName ||
          !['.csv', '.json', '.yaml', '.yml', '.md'].includes(extension)
        ) {
          response.status(400).json({ error: 'Only uploaded mapping evidence can be previewed.' });
          return;
        }
        try {
          const record = (await readUploadManifest(request, activeVolumeRoot)).find((item) => item.name === fileName);
          if (!record) throw new Error('Mapping evidence was not found.');
          const content = await volumeHandle(request).read(record.volumePath);
          response.json({ name: fileName, content });
        } catch {
          response.status(404).json({ error: 'Mapping evidence was not found.' });
        }
      });

      app.get('/api/databricks/targets', async (request, response) => {
        try {
          const catalog = namespaceSchema.parse(request.query.catalog ?? defaultTargetCatalog);
          const schema = namespaceSchema.parse(request.query.schema ?? defaultTargetSchema);
          const tables = await appkit.asUser(request).run(async () => {
            const client = getExecutionContext().client.toLegacyWorkspaceClient();
            const values = [];
            for await (const table of client.tables.list({
              catalog_name: catalog,
              schema_name: schema,
              max_results: 0,
              omit_properties: true,
              omit_username: true,
            })) {
              if (!table.full_name) continue;
              values.push({
                fullName: table.full_name,
                name: table.name ?? table.full_name,
                tableType: table.table_type ?? 'UNKNOWN',
                comment: table.comment,
                columns: (table.columns ?? []).flatMap((column) =>
                  column.name ? [{ name: column.name, type: column.type_text ?? String(column.type_name ?? '') }] : []
                ),
              });
            }
            return values.sort((left, right) => left.name.localeCompare(right.name));
          });
          response.json({
            catalog,
            schema,
            identity: 'signed-in Databricks user',
            tables,
          });
        } catch (error) {
          response.status(502).json({
            error: 'Unity Catalog targets are unavailable.',
            detail: error instanceof Error ? error.message : 'Unknown Databricks error',
          });
        }
      });

      app.get('/api/databricks/catalogs', async (request, response) => {
        try {
          const catalogs = await appkit.asUser(request).run(async () => {
            const client = getExecutionContext().client.toLegacyWorkspaceClient();
            const values: Array<{ name: string; comment?: string }> = [];
            for await (const catalog of client.catalogs.list({ max_results: 0, include_browse: false })) {
              if (catalog.name) values.push({ name: catalog.name, comment: catalog.comment });
            }
            return values.sort((left, right) => left.name.localeCompare(right.name));
          });
          response.json({ defaultCatalog: defaultTargetCatalog, catalogs });
        } catch (error) {
          response.status(502).json({
            error: 'Unity Catalog catalogs are unavailable.',
            detail: error instanceof Error ? error.message : 'Unknown Databricks error',
          });
        }
      });

      app.get('/api/databricks/schemas', async (request, response) => {
        try {
          const catalog = namespaceSchema.parse(request.query.catalog);
          const schemas = await appkit.asUser(request).run(async () => {
            const client = getExecutionContext().client.toLegacyWorkspaceClient();
            const values: Array<{ name: string; fullName: string; comment?: string }> = [];
            for await (const schema of client.schemas.list({ catalog_name: catalog, max_results: 0 })) {
              if (schema.name && schema.full_name) {
                values.push({ name: schema.name, fullName: schema.full_name, comment: schema.comment });
              }
            }
            return values.sort((left, right) => left.name.localeCompare(right.name));
          });
          response.json({
            catalog,
            defaultSchema: catalog === defaultTargetCatalog ? defaultTargetSchema : '',
            schemas,
          });
        } catch (error) {
          response.status(502).json({
            error: 'Unity Catalog schemas are unavailable.',
            detail: error instanceof Error ? error.message : 'Unknown Databricks error',
          });
        }
      });

      app.get('/api/databricks/volumes', async (request, response) => {
        try {
          const catalog = namespaceSchema.parse(request.query.catalog);
          const schema = namespaceSchema.parse(request.query.schema);
          const volumes = await appkit.asUser(request).run(async () => {
            const client = getExecutionContext().client.toLegacyWorkspaceClient();
            const values: Array<{ name: string; fullName: string; comment?: string }> = [];
            for await (const volume of client.volumes.list({
              catalog_name: catalog,
              schema_name: schema,
              max_results: 0,
            })) {
              if (volume.name && volume.full_name) {
                values.push({ name: volume.name, fullName: volume.full_name, comment: volume.comment });
              }
            }
            return values.sort((left, right) => left.name.localeCompare(right.name));
          });
          response.json({ catalog, schema, volumes });
        } catch (error) {
          response.status(502).json({
            error: 'Unity Catalog volumes are unavailable.',
            detail: error instanceof Error ? error.message : 'Unknown Databricks error',
          });
        }
      });

      app.put('/api/groups/:groupId/mappings/draft', async (request, response) => {
        const { groupId } = request.params;
        const parsed = mappingUpdateSchema.safeParse(request.body);
        if (!/^group-\d{3}$/.test(groupId) || !parsed.success) {
          response.status(400).json({ error: 'The mapping update is invalid.' });
          return;
        }
        const update = parsed.data;
        try {
          if (update.corpusId !== 'uploaded' || !activeVolumeRoot) {
            throw new Error('Only Volume-backed migration runs can be updated.');
          }
          const mappingPath = `${migrationRoot(activeVolumeRoot)}/inventory/groups/${groupId}/mappings/domains/uploaded-${groupId}.yaml`;
          const volume = volumeHandle(request);
          const contract = parseYaml(await volume.read(mappingPath)) as {
            fields: Array<Record<string, unknown>>;
            relationships?: Array<Record<string, unknown>>;
          };
          const field = contract.fields.find(
            (candidate) => candidate.datasource === update.datasource && candidate.legacy === update.legacy
          );
          if (!field) throw new Error('The Tableau field was not found in this contract.');
          field.target_table = update.targetTable;
          field.target_expression = update.targetExpression;
          field.conversion = update.conversion;
          field.status = 'proposed';
          field.evidence = ['user_updated_mapping_evidence'];
          const contractYaml = stringifyYaml(contract);
          await volume.upload(mappingPath, contractYaml, { overwrite: true });
          response.json({ success: true, field });
        } catch (error) {
          response.status(400).json({
            error: 'Mapping draft was not saved.',
            detail: error instanceof Error ? error.message : 'Unknown mapping error',
          });
        }
      });

      app.put('/api/groups/:groupId/relationships/draft', async (request, response) => {
        const { groupId } = request.params;
        const parsed = relationshipUpdateSchema.safeParse(request.body);
        if (!/^group-\d{3}$/.test(groupId) || !parsed.success) {
          response.status(400).json({ error: 'The relationship update is invalid.' });
          return;
        }
        try {
          if (!activeVolumeRoot) throw new Error('Only Volume-backed migration runs can be updated.');
          const mappingPath = `${migrationRoot(activeVolumeRoot)}/inventory/groups/${groupId}/mappings/domains/uploaded-${groupId}.yaml`;
          const volume = volumeHandle(request);
          const contract = parseYaml(await volume.read(mappingPath)) as { relationships?: Array<Record<string, unknown>> };
          const relationship = contract.relationships?.[parsed.data.relationshipIndex];
          if (!relationship) throw new Error('The relationship was not found in this contract.');
          relationship.target = {
            left_table_candidates: [parsed.data.leftTable],
            right_table_candidates: [parsed.data.rightTable],
            join_type: parsed.data.joinType,
            condition: parsed.data.condition,
            cardinality: parsed.data.cardinality,
            temporal_predicates: parsed.data.temporalPredicates.filter(Boolean),
            record_filters: parsed.data.recordFilters.filter(Boolean),
          };
          relationship.status = 'proposed';
          relationship.confidence = 1;
          relationship.evidence = ['user_reviewed_relationship'];
          await volume.upload(mappingPath, stringifyYaml(contract), { overwrite: true });
          response.json({ success: true, relationship });
        } catch (error) {
          response.status(400).json({
            error: 'Relationship update was not saved.',
            detail: error instanceof Error ? error.message : 'Unknown relationship error',
          });
        }
      });

      app.post('/api/groups/:groupId/mappings/approve', async (request, response) => {
        const { groupId } = request.params;
        const parsed = z.object({ corpusId: z.literal('uploaded') }).safeParse(request.body);
        if (!/^group-\d{3}$/.test(groupId) || !parsed.success) {
          response.status(400).json({ error: 'The mapping approval request is invalid.' });
          return;
        }
        try {
          if (!activeVolumeRoot) throw new Error('The run Volume is not selected.');
          const volume = volumeHandle(request);
          const outputRoot = `${migrationRoot(activeVolumeRoot)}/inventory`;
          const mappingFile = `uploaded-${groupId}.yaml`;
          const mappingPath = `${outputRoot}/groups/${groupId}/mappings/domains/${mappingFile}`;
          const contract = parseYaml(await volume.read(mappingPath)) as {
            status: string;
            sources?: string[];
            kpis?: Array<{ legacy_name?: string; legacy_expression?: string; assets?: string[] }>;
            fields: Array<Record<string, unknown>>;
            relationships?: Array<Record<string, unknown>>;
          };
          const datasourceFields = contract.fields.filter(
            (field) =>
              field.datasource !== 'Parameters' &&
              !field.calculation &&
              field.datatype !== 'table' &&
              !/^\[.*\]$/.test(typeof field.legacy === 'string' ? field.legacy : '')
          );
          const invalidFields = datasourceFields.filter(
            (field) =>
              typeof field.target_table !== 'string' ||
              field.target_table.length === 0 ||
              typeof field.target_expression !== 'string' ||
              field.target_expression.length === 0
          );
          if (invalidFields.length > 0) {
            throw new Error(`${invalidFields.length} datasource mappings do not have a complete target.`);
          }
          const unresolvedRelationships = (contract.relationships ?? []).filter(
            (relationship) => relationship.status !== 'proposed' && relationship.status !== 'approved'
          );
          if (unresolvedRelationships.length > 0) {
            throw new Error(`${unresolvedRelationships.length} relationships require mapping evidence or review.`);
          }
          contract.status = 'approved';
          for (const field of datasourceFields) field.status = 'approved';
          for (const relationship of contract.relationships ?? []) relationship.status = 'approved';
          const contractYaml = stringifyYaml(contract);
          await volume.upload(mappingPath, contractYaml, { overwrite: true });

          const contextFileName = 'importbi-prompt.md';
          const selectedVolume = activeVolumeRoot;
          if (!selectedVolume) throw new Error('Choose a Unity Catalog Volume before preparing the import.');
          const uploadedFiles = await readUploadManifest(request, selectedVolume);
          const workbookPaths = uploadedFiles
            .filter((file) => file.kind === 'Tableau workbook')
            .map((file) => file.volumePath);
          if (workbookPaths.length === 0) throw new Error('No Volume-hosted Tableau workbooks were found.');
          const groupRunPath = await groupWorkspacePath(request, selectedVolume, groupId);
          const volumeContractPath = `${groupRunPath}/mapping/approved.yaml`;
          const prompt = [
            '/importBI',
            '',
            `Migrate these Tableau workbooks: ${workbookPaths.join(', ') || (contract.sources ?? []).join(', ') || groupId}.`,
            `Use the approved mapping contract ${volumeContractPath} as authoritative context.`,
            'Use only the physical Databricks targets declared in the contract.',
            'Do not substitute compatibility views or unrelated tables.',
            'Derive workbook calculations and UI behavior only after applying the approved datasource mappings.',
            'Record unsupported features and validation gaps instead of inventing data or mappings.',
          ].join('\n');
          const context = `# /importBI migration context\n\n${prompt}\n`;

          const session1Path = `${groupRunPath}/import`;
          const semanticBasePath = `${groupRunPath}/semantic`;
          const session1PromptPath = `${session1Path}/prompt.md`;
          const metricViewPromptPath = `${groupRunPath}/mapping/prompts/metric-view-prompt.md`;
          const genieAgentPromptPath = `${groupRunPath}/mapping/prompts/genie-agent-prompt.md`;
          const dashboardManifestPath = `${session1Path}/summary.json`;
          const dashboardConfigDirectory = `${session1Path}/workbooks`;
          const kpiInventoryPath = `${outputRoot}/groups/${groupId}/reports/kpi_candidates.csv`;
          const safeRunId = activeMigrationName.replace(/[^a-zA-Z0-9_]/g, '_');
          const safeGroupId = groupId.replace(/[^a-zA-Z0-9_]/g, '_');
          const metricViewFqn = `${defaultTargetCatalog}.${defaultTargetSchema}.bi_migration_${safeGroupId}_candidate_${safeRunId}`;
          const agentName = `BI migration analytics ${activeMigrationName} ${groupId}`;
          const preflightPath = `${semanticBasePath}/deterministic-preflight.json`;
          const metricViewPath = `${semanticBasePath}/metric-view-proposal.yaml`;
          const genieAgentPath = `${semanticBasePath}/genie-agent-proposal.json`;
          const benchmarkPath = `${semanticBasePath}/benchmark-questions.json`;
          const metricViewPrompt = renderMetricViewPrompt({
            runId: activeMigrationName,
            groupId,
            approvedMappingPath: volumeContractPath,
            dashboardManifestPath,
            dashboardConfigDirectory,
            kpiInventoryPath,
            metricViewFqn,
            artifactDirectory: semanticBasePath,
          });
          const genieAgentPrompt = renderGenieAgentPrompt({
            runId: activeMigrationName,
            groupId,
            metricViewFqn,
            metricViewValidationPath: `${semanticBasePath}/metric-view-validation.json`,
            dashboardConfigDirectory,
            agentName,
            artifactDirectory: semanticBasePath,
          });
          const groupMigrationManifest = {
            manifest_version: '1.0',
            run_id: activeMigrationName,
            semantic_group: groupId,
            workbook_paths: workbookPaths,
            workbooks: workbookPaths.map((workbookPath, index) => {
              const parts = workbookPath.split('/');
              const workbookName = parts[parts.length - 1];
              const workbookId = `${String(index + 1).padStart(3, '0')}-${sha256(workbookPath).slice(0, 10)}`;
              return {
                workbook_id: workbookId,
                workbook_name: workbookName,
                workbook_path: workbookPath,
                dashboard_tag: `[bi-migration:${activeMigrationName}:${groupRunPath.split('/').pop()}:${workbookId}]`,
                output_path: `${session1Path}/workbooks/${workbookId}`,
              };
            }),
            approved_mapping_path: volumeContractPath,
            prompts: {
              session_1: {
                version: SESSION_1_PROMPT_VERSION,
                path: session1PromptPath,
                sha256: sha256(context),
              },
              metric_view: {
                version: METRIC_VIEW_PROMPT_VERSION,
                path: metricViewPromptPath,
                sha256: sha256(metricViewPrompt),
              },
              genie_agent: {
                version: GENIE_AGENT_PROMPT_VERSION,
                path: genieAgentPromptPath,
                sha256: sha256(genieAgentPrompt),
              },
            },
            dashboard_manifest_path: dashboardManifestPath,
            dashboard_config_directory: dashboardConfigDirectory,
            kpi_inventory_path: kpiInventoryPath,
            candidate_metric_view_fqn: metricViewFqn,
            genie_agent_name: agentName,
          };
          await Promise.all([
            volume.upload(volumeContractPath, contractYaml, {
              overwrite: true,
            }),
            volume.upload(session1PromptPath, context, { overwrite: true }),
            volume.upload(metricViewPromptPath, metricViewPrompt, { overwrite: true }),
            volume.upload(genieAgentPromptPath, genieAgentPrompt, { overwrite: true }),
            volume.upload(`${groupRunPath}/group-migration-manifest.json`, JSON.stringify(groupMigrationManifest, null, 2), {
              overwrite: true,
            }),
            volume.upload(`${groupRunPath}/group.json`, JSON.stringify({
              group_id: groupId,
              name: groupRunPath.split('/').pop(),
              migration: activeMigrationName,
              manifest_path: `${groupRunPath}/group-migration-manifest.json`,
            }, null, 2), { overwrite: true }),
          ]);

          const readinessPath = `${outputRoot}/groups/${groupId}/readiness_report.json`;
          const readiness = JSON.parse(await volume.read(readinessPath)) as {
            ready: boolean;
            contract_status: string;
            issues: Array<{ code: string; count: number; severity: string }>;
          };
          readiness.contract_status = 'approved';
          readiness.issues = (readiness.issues ?? []).filter((issue) => issue.code !== 'contract_not_approved');
          readiness.ready = readiness.issues.length === 0;
          await volume.upload(readinessPath, JSON.stringify(readiness, null, 2), { overwrite: true });

          const groupReadinessPath = `${outputRoot}/group_readiness.json`;
          const groupReadiness = JSON.parse(await volume.read(groupReadinessPath)) as GroupSummary[];
          const summary = groupReadiness.find((group) => group.group_id === groupId);
          if (summary) {
            summary.contract_status = 'approved';
            summary.ready = readiness.ready;
            await volume.upload(groupReadinessPath, JSON.stringify(groupReadiness, null, 2), { overwrite: true });
          }
          response.json({
            success: true,
            status: 'approved',
            contextFileName,
            context,
            prompt,
            session1PromptPath,
            metricViewPrompt,
            metricViewPromptPath,
            genieAgentPrompt,
            genieAgentPromptPath,
            mappingFileName: mappingFile,
            contractYaml,
            volumeContractPath,
            semanticArtifacts: {
              preflightPath,
              session1PromptPath,
              metricViewPromptPath,
              genieAgentPromptPath,
              metricViewPath,
              genieAgentPath,
              benchmarkPath,
            },
            jobSetup: jobSetup(),
          });
        } catch (error) {
          response.status(400).json({
            error: 'Mappings could not be approved.',
            detail: error instanceof Error ? error.message : 'Unknown approval error',
          });
        }
      });

      app.get('/api/groups/:groupId/import-package', async (request, response) => {
        const { groupId } = request.params;
        const corpusId = request.query.corpus;
        if (
          !/^group-\d{3}$/.test(groupId) ||
          (corpusId !== 'downloaded' && corpusId !== 'synthetic' && corpusId !== 'uploaded')
        ) {
          response.status(400).json({ error: 'A valid group and corpus are required.' });
          return;
        }
        try {
          if (!activeVolumeRoot) throw new Error('The run Volume is not selected.');
          const volume = volumeHandle(request);
          const mappingFileName = `uploaded-${groupId}.yaml`;
          const groupRunPath = await groupWorkspacePath(request, activeVolumeRoot, groupId);
          const approvedMappingPath = `${groupRunPath}/mapping/approved.yaml`;
          const contextPath = `${groupRunPath}/import/prompt.md`;
          const semanticBasePath = `${groupRunPath}/semantic`;
          const metricViewPromptPath = `${groupRunPath}/mapping/prompts/metric-view-prompt.md`;
          const genieAgentPromptPath = `${groupRunPath}/mapping/prompts/genie-agent-prompt.md`;
          const [contractYaml, context] = await Promise.all([
            volume.read(approvedMappingPath),
            volume.read(contextPath),
          ]);
          const contract = parseYaml(contractYaml) as { status?: string };
          if (contract.status !== 'approved') throw new Error('Approve the mappings before preparing the import.');
          if (!context.includes('/Volumes/')) {
            throw new Error('This package uses local paths. Prepare it again after uploading every workbook to a Volume.');
          }
          const selectedVolume = activeVolumeRoot;
          if (!selectedVolume) throw new Error('The package has no Unity Catalog Volume destination.');
          response.json({
            mappingFileName,
            contractYaml,
            prompt: context.replace(/^# \/importBI migration context\s*/u, '').trim(),
            session1PromptPath: contextPath,
            metricViewPrompt: JOB_TASK_PROMPTS.buildMetricView,
            metricViewPromptPath,
            genieAgentPrompt: JOB_TASK_PROMPTS.buildGenieAgent,
            genieAgentPromptPath,
            semanticArtifacts: {
              preflightPath: `${semanticBasePath}/deterministic-preflight.json`,
              session1PromptPath: contextPath,
              metricViewPromptPath,
              genieAgentPromptPath,
              metricViewPath: `${semanticBasePath}/metric-view-proposal.yaml`,
              genieAgentPath: `${semanticBasePath}/genie-agent-proposal.json`,
              benchmarkPath: `${semanticBasePath}/benchmark-questions.json`,
            },
            jobSetup: jobSetup(),
          });
        } catch (error) {
          response.status(404).json({
            error: 'Import package is unavailable.',
            detail: error instanceof Error ? error.message : 'Unknown import package error',
          });
        }
      });

      app.post('/api/groups/:groupId/dashboard-import-run', async (request, response) => {
        const { groupId } = request.params;
        if (!/^group-\d{3}$/.test(groupId) || !activeVolumeRoot) {
          response.status(400).json({ error: 'A valid Volume-backed semantic group is required.' });
          return;
        }
        try {
          const volume = volumeHandle(request);
          const jobDefinition = await appkit.jobs('dashboard_import').getJob();
          if (!jobDefinition.ok || JSON.stringify(jobDefinition.data).includes('genie_task_not_configured')) {
            throw new Error('Configure import_dashboard as a Genie Code task once in the Dashboard Import Job UI.');
          }
          const groupRunPath = await groupWorkspacePath(request, activeVolumeRoot, groupId);
          await volume.read(`${groupRunPath}/group-migration-manifest.json`);
          const user = await appkit.asUser(request).run(async () => getExecutionContext().client.currentUser.me());
          const requestedBy = user.userName || user.displayName || 'signed-in-user';
          const workflowRunId = `${activeMigrationName}-${groupId}-import-${Date.now()}`;
          const result = await appkit.jobs('dashboard_import').runNow({
            job_parameters: { run_id: workflowRunId, group_id: groupId, group_run_path: groupRunPath, requested_by: requestedBy },
          });
          if (!result.ok || !result.data.run_id) throw new Error(result.ok ? 'The workflow returned no run ID.' : String(result.error));
          const state = {
            groupId,
            workflowRunId,
            databricksRunId: result.data.run_id,
            requestedBy,
            status: 'PENDING',
            submittedAt: new Date().toISOString(),
          };
          await volume.upload(`${groupRunPath}/import/workflow-run.json`, JSON.stringify(state, null, 2), {
            overwrite: true,
          });
          const jobId = process.env.DATABRICKS_JOB_DASHBOARD_IMPORT;
          response.status(202).json({
            ...state,
            runUrl: jobId && (process.env.DATABRICKS_WORKSPACE_URL || process.env.DATABRICKS_HOST)
              ? `${(process.env.DATABRICKS_WORKSPACE_URL || process.env.DATABRICKS_HOST)?.replace(/\/$/, '')}/jobs/${jobId}`
              : null,
          });
        } catch (error) {
          response.status(400).json({
            error: 'Dashboard Import Job could not be started.',
            detail: error instanceof Error ? error.message : 'Unknown workflow error',
          });
        }
      });

      app.get('/api/groups/:groupId/dashboard-import-run', async (request, response) => {
        const { groupId } = request.params;
        if (!/^group-\d{3}$/.test(groupId) || !activeVolumeRoot) {
          response.status(400).json({ error: 'A valid Volume-backed semantic group is required.' });
          return;
        }
        try {
          const volume = volumeHandle(request);
          const groupRunPath = await groupWorkspacePath(request, activeVolumeRoot, groupId);
          const state = JSON.parse(await volume.read(`${groupRunPath}/import/workflow-run.json`)) as {
            workflowRunId: string; databricksRunId: number; requestedBy: string; submittedAt: string;
          };
          const run = await appkit.jobs('dashboard_import').getRun(state.databricksRunId);
          if (!run.ok) throw new Error(String(run.error));
          const summary = await volume.read(`${groupRunPath}/import/summary.json`).then((text) => JSON.parse(text) as { status?: string }).catch(() => null);
          const jobId = process.env.DATABRICKS_JOB_DASHBOARD_IMPORT;
          response.json({
            ...state,
            lifeCycleState: String(run.data.state?.life_cycle_state ?? 'PENDING'),
            resultState: summary?.status === 'SUCCESS' ? 'SUCCESS' : String(run.data.state?.result_state ?? ''),
            tasks: (run.data.tasks ?? []).map((task) => ({ taskKey: task.task_key, lifeCycleState: String(task.state?.life_cycle_state ?? 'PENDING'), resultState: String(task.state?.result_state ?? '') })),
            artifactPaths: {
              dashboardResult: `${groupRunPath}/import/summary.json`,
              dashboardConfig: `${groupRunPath}/import/workbooks`,
              audit: `${groupRunPath}/import/summary.json`,
            },
            runUrl: jobId && (process.env.DATABRICKS_WORKSPACE_URL || process.env.DATABRICKS_HOST)
              ? `${(process.env.DATABRICKS_WORKSPACE_URL || process.env.DATABRICKS_HOST)?.replace(/\/$/, '')}/jobs/${jobId}`
              : null,
          });
        } catch (error) {
          response.status(404).json({ error: 'No Dashboard Import Job run is available for this group.' });
        }
      });

      app.post('/api/groups/:groupId/semantic-run', async (request, response) => {
        const { groupId } = request.params;
        if (!/^group-\d{3}$/.test(groupId) || !activeVolumeRoot) {
          response.status(400).json({ error: 'A valid Volume-backed semantic group is required.' });
          return;
        }
        try {
          const volume = volumeHandle(request);
          const jobDefinition = await appkit.jobs('semantic').getJob();
          if (!jobDefinition.ok || JSON.stringify(jobDefinition.data).includes('genie_task_not_configured')) {
            throw new Error(
              'Configure build_metric_view and build_genie_agent as Genie Code tasks once in the Jobs UI.'
            );
          }
          const groupRunPath = await groupWorkspacePath(request, activeVolumeRoot, groupId);
          const manifestPath = `${groupRunPath}/group-migration-manifest.json`;
          await volume.read(manifestPath);
          const importSummary = JSON.parse(await volume.read(`${groupRunPath}/import/summary.json`)) as { status?: string };
          if (importSummary.status !== 'SUCCESS') throw new Error('Dashboard reconciliation must pass before Semantic Build.');
          const [metricPrompt, agentPrompt] = await Promise.all([
            volume.read(`${groupRunPath}/mapping/prompts/metric-view-prompt.md`),
            volume.read(`${groupRunPath}/mapping/prompts/genie-agent-prompt.md`),
          ]);
          await Promise.all([
            volume.upload(`${groupRunPath}/semantic/metric-view-prompt.md`, metricPrompt, { overwrite: true }),
            volume.upload(`${groupRunPath}/semantic/genie-agent-prompt.md`, agentPrompt, { overwrite: true }),
          ]);
          const user = await appkit.asUser(request).run(async () => getExecutionContext().client.currentUser.me());
          const requestedBy = user.userName || user.displayName || 'signed-in-user';
          const workflowRunId = `${activeMigrationName}-${groupId}-${Date.now()}`;
          const result = await appkit.jobs('semantic').runNow({
            job_parameters: {
              run_id: workflowRunId,
              group_id: groupId,
              group_run_path: groupRunPath,
              requested_by: requestedBy,
            },
          });
          if (!result.ok || !result.data.run_id) {
            throw new Error(result.ok ? 'The workflow returned no run ID.' : String(result.error));
          }
          const state = {
            groupId,
            workflowRunId,
            databricksRunId: result.data.run_id,
            requestedBy,
            status: 'PENDING',
            submittedAt: new Date().toISOString(),
          };
          await volume.upload(`${groupRunPath}/semantic/workflow-run.json`, JSON.stringify(state, null, 2), {
            overwrite: true,
          });
          const jobId = process.env.DATABRICKS_JOB_SEMANTIC;
          response.status(202).json({
            ...state,
            runUrl:
              jobId && process.env.DATABRICKS_WORKSPACE_URL
                ? `${process.env.DATABRICKS_WORKSPACE_URL.replace(/\/$/, '')}/jobs/${jobId}/runs/${result.data.run_id}`
                : null,
          });
        } catch (error) {
          response.status(400).json({
            error: 'Semantic workflow could not be started.',
            detail: error instanceof Error ? error.message : 'Unknown workflow error',
          });
        }
      });

      app.get('/api/groups/:groupId/semantic-run', async (request, response) => {
        const { groupId } = request.params;
        if (!/^group-\d{3}$/.test(groupId) || !activeVolumeRoot) {
          response.status(400).json({ error: 'A valid Volume-backed semantic group is required.' });
          return;
        }
        try {
          const volume = volumeHandle(request);
          const groupRunPath = await groupWorkspacePath(request, activeVolumeRoot, groupId);
          const statePath = `${groupRunPath}/semantic/workflow-run.json`;
          const state = JSON.parse(await volume.read(statePath)) as {
            workflowRunId: string;
            databricksRunId: number;
            requestedBy: string;
            submittedAt: string;
          };
          const run = await appkit.jobs('semantic').getRun(state.databricksRunId);
          if (!run.ok) throw new Error(String(run.error));
          const tasks = (run.data.tasks ?? []).map((task) => ({
            taskKey: task.task_key,
            lifeCycleState: String(task.state?.life_cycle_state ?? 'PENDING'),
            resultState: String(task.state?.result_state ?? ''),
          }));
          const lifeCycleState = String(run.data.state?.life_cycle_state ?? 'PENDING');
          const resultState = String(run.data.state?.result_state ?? '');
          const artifactPaths = {
            metricViewResult: `${groupRunPath}/semantic/metric-view-result.json`,
            genieAgentResult: `${groupRunPath}/semantic/genie-agent-result.json`,
            audit: `${groupRunPath}/semantic/semantic-audit.json`,
          };
          const artifactAvailability = Object.fromEntries(
            await Promise.all(
              Object.entries(artifactPaths).map(async ([key, artifactPath]) => [
                key,
                await volume.exists(artifactPath).catch(() => false),
              ])
            )
          );
          const jobId = process.env.DATABRICKS_JOB_SEMANTIC;
          response.json({
            ...state,
            lifeCycleState,
            resultState,
            tasks,
            artifactPaths,
            artifactAvailability,
            runUrl:
              jobId && process.env.DATABRICKS_WORKSPACE_URL
                ? `${process.env.DATABRICKS_WORKSPACE_URL.replace(/\/$/, '')}/jobs/${jobId}/runs/${state.databricksRunId}`
                : null,
          });
        } catch (error) {
          response.status(404).json({
            error: 'No semantic workflow run is available for this group.',
            detail: error instanceof Error ? error.message : 'Unknown workflow error',
          });
        }
      });

      app.post('/api/uploads', async (request, response) => {
        const encodedName = request.header('x-file-name');
        const fileName = encodedName ? decodeURIComponent(encodedName) : '';
        const extension = path.extname(fileName).toLowerCase();
        const storageFileName = `${path
          .basename(fileName, extension)
          .replace(/[^A-Za-z0-9 _.-]/g, '')
          .replace(/\s+/g, ' ')
          .trim()}${extension}`;
        const volumeName = request.header('x-volume-name') ?? '';
        const selectedVolume = /^([A-Za-z_][\w-]*)\.([A-Za-z_][\w-]*)\.([A-Za-z_][\w-]*)$/.test(volumeName)
          ? `/Volumes/${volumeName.split('.').join('/')}`
          : '';
        if (
          !fileName ||
          !path.basename(storageFileName, extension) ||
          !uploadExtensions.has(extension) ||
          path.basename(fileName) !== fileName
        ) {
          response.status(400).json({ error: 'Choose a supported workbook or mapping file.' });
          return;
        }
        const chunks: Buffer[] = [];
        let size = 0;
        for await (const chunk of request as AsyncIterable<Uint8Array>) {
          const buffer = Buffer.from(chunk);
          size += buffer.length;
          if (size > 100 * 1024 * 1024) {
            response.status(413).json({ error: 'Files must be 100 MB or smaller for local testing.' });
            return;
          }
          chunks.push(buffer);
        }
        const contents = Buffer.concat(chunks);
        const volumeRelativePath = `bi-migrations/${activeMigrationName}/inputs/${['.twb', '.twbx'].includes(extension) ? 'workbooks' : 'mappings'}/${storageFileName}`;
        if (!selectedVolume) {
          response.status(400).json({ error: 'Choose a writable Unity Catalog Volume before uploading.' });
          return;
        }
        const volume = volumeHandle(request);
        await volume.upload(`${selectedVolume}/${volumeRelativePath}`, contents, { overwrite: true });
        activeVolumeRoot = selectedVolume;
        const uploadedFiles = await readUploadManifest(request, selectedVolume);
        const record = {
          name: storageFileName,
          sizeBytes: contents.length,
          status: 'uploaded',
          kind: ['.twb', '.twbx'].includes(extension) ? 'Tableau workbook' : 'Mapping evidence',
          volumePath: `${selectedVolume}/${volumeRelativePath}`,
        };
        const nextFiles = [...uploadedFiles.filter((item) => item.name !== storageFileName), record];
        await volume.upload(uploadManifestPath(selectedVolume), JSON.stringify(nextFiles, null, 2), { overwrite: true });
        response.status(201).json({
          name: storageFileName,
          originalName: fileName,
          sizeBytes: contents.length,
          checksum: createHash('sha256').update(contents).digest('hex'),
          status: 'uploaded',
          storage: 'unity_catalog_volume',
          volumePath: `${selectedVolume}/${volumeRelativePath}`,
        });
      });

      app.post('/api/uploads/process', async (request, response) => {
        const parsedRequest = z.object({ volume: z.string().min(1) }).safeParse(request.body);
        const selectedVolume = parsedRequest.success ? volumePathFromName(parsedRequest.data.volume) : activeVolumeRoot;
        const files = await readUploadManifest(request, selectedVolume);
        if (files.length === 0) {
          response.status(400).json({ error: 'Upload at least one Tableau workbook first.' });
          return;
        }
        if (processingStatus === 'running') {
          response.status(409).json({ error: 'Inventory processing is already running.' });
          return;
        }
        const namespaces = new Map<string, { catalog: string; schema: string }>();
        for (const file of files.filter((item) => item.kind === 'Mapping evidence')) {
          const contents = await volumeHandle(request).read(file.volumePath);
          for (const match of contents.matchAll(/\b([A-Za-z_][\w-]*)\.([A-Za-z_][\w-]*)\.([A-Za-z_][\w-]*)\b/g)) {
            const [, catalog, schema] = match;
            namespaces.set(`${catalog}.${schema}`, { catalog, schema });
          }
        }
        if (namespaces.size === 0) {
          response.status(400).json({
            error: 'No fully qualified Databricks tables were found. Add an optional discovery catalog and schema.',
          });
          return;
        }
        const targetMetadata = {
          tables: [],
          source: 'uploaded_mapping_evidence',
          namespaces: Array.from(namespaces.values()),
        };
        if (!selectedVolume) {
          response.status(400).json({ error: 'Upload assets to a Unity Catalog Volume before running inventory.' });
          return;
        }
        const runRoot = migrationRoot(selectedVolume);
        const targetMetadataPath = `${runRoot}/control/target-metadata.json`;
        await volumeHandle(request).upload(targetMetadataPath, JSON.stringify(targetMetadata, null, 2), {
          overwrite: true,
        });
        const jobResult = await appkit.jobs('inventory').runNow({
          input_path: `${runRoot}/inputs`,
          mapping_docs_path: `${runRoot}/inputs/mappings`,
          target_metadata_path: targetMetadataPath,
          output_path: `${runRoot}/inventory`,
          run_id: activeMigrationName,
          source_base_uri: `${runRoot}/inputs`,
        });
        if (!jobResult.ok || !jobResult.data.run_id) {
          processingStatus = 'failed';
          processingMessage = 'Inventory job submission failed.';
          response.status(502).json({ error: processingMessage });
          return;
        }
        processingStatus = 'running';
        inventoryRunId = jobResult.data.run_id;
        processingMessage = `Inventory job run ${jobResult.data.run_id} submitted.`;
        response.status(202).json({
          status: processingStatus,
          message: processingMessage,
          runId: jobResult.data.run_id,
          runUrl:
            process.env.DATABRICKS_WORKSPACE_URL && process.env.DATABRICKS_JOB_ID
              ? `${process.env.DATABRICKS_WORKSPACE_URL.replace(/\/$/, '')}/jobs/${process.env.DATABRICKS_JOB_ID}/runs/${jobResult.data.run_id}`
              : null,
        });
      });

      app.get('/api/groups/:groupId', async (request, response) => {
        const { groupId } = request.params;
        const corpusId = request.query.corpus;
        if (!/^group-\d{3}$/.test(groupId)) {
          response.status(400).json({ error: 'Invalid semantic group identifier.' });
          return;
        }
        if (corpusId !== 'uploaded') {
          response.status(400).json({ error: 'A valid test corpus is required.' });
          return;
        }
        try {
          if (!activeVolumeRoot) throw new Error('The run Volume is not selected.');
          const outputRoot = `${migrationRoot(activeVolumeRoot)}/inventory`;
          const volume = volumeHandle(request);
          const readRunJson = async <T,>(relativePath: string) =>
            JSON.parse(await volume.read(`${outputRoot}/${relativePath}`)) as T;
          const mappingFile = `uploaded-${groupId}.yaml`;
          const [readiness, sourceInventory, groups, mappingContract] = await Promise.all([
            readRunJson<{
              ready: boolean;
              contract_status: string;
              coverage: {
                total_fields: number;
                mapped_fields: number;
                dispositioned_fields: number;
                unresolved_fields: number;
                mapping_percentage: number;
              };
              issues: Array<{ code: string; count: number; severity: string }>;
              unresolved: Array<{ datasource: string; legacy: string; assets: string[] }>;
            }>(`groups/${groupId}/readiness_report.json`),
            readRunJson<SourceAsset[]>(`groups/${groupId}/source_inventory.json`),
            readRunJson<SemanticGroup[]>('groups.json'),
            volume
              .read(`${outputRoot}/groups/${groupId}/mappings/domains/${mappingFile}`)
              .then(
                (contents) =>
                    parseYaml(contents) as {
                      status: string;
                      kpis?: Array<{
                        legacy_name: string;
                        legacy_expression: string;
                        aliases?: string[];
                        assets?: string[];
                      }>;
                      workbook_helpers?: Array<{ name: string; assets?: string[]; datasources?: string[] }>;
                      relationships?: Array<Record<string, unknown>>;
                      fields: Array<{
                        datasource: string;
                        legacy: string;
                        datatype: string;
                        target_table?: string;
                        target_expression?: string;
                        source_table?: string;
                        conversion?: string;
                        confidence?: number;
                        status: string;
                        evidence?: string[];
                      }>;
                    }
              ),
          ]);
          const semanticGroup = groups.find((group) => group.group_id === groupId);
          response.json({
            groupId,
            readiness,
            sourceInventory,
            mappingContract,
            grouping: semanticGroup
              ? {
                  reason: groupingReason(semanticGroup),
                  dependencies: semanticGroup.dependencies,
                  sharedDependencies: semanticGroup.shared_dependencies,
                }
              : null,
          });
        } catch (error) {
          response.status(404).json({
            error: 'Semantic group output was not found.',
            detail: error instanceof Error ? error.message : 'Unknown read error',
          });
        }
      });
    });
  },
});
