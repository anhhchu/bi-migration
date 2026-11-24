import { ArrowRight, History, LayoutDashboard, Layers3 } from 'lucide-react';
import { Button } from '@databricks/appkit-ui/react';
import { DASHBOARD_MIGRATION_ENABLED } from '@/lib/features';

type StartOption = 'semantic' | 'runs' | 'dashboard';

const OPTIONS: Array<{
  key: StartOption;
  title: string;
  body: string;
  action: string;
  icon: typeof Layers3;
  primary?: boolean;
}> = [
  {
    key: 'semantic',
    title: 'Migrate semantic models',
    body: 'Tableau .tds/.tdsx + table-mapping.yaml → grouped, evaluated Metric Views.',
    action: 'Start',
    icon: Layers3,
    primary: true,
  },
  {
    key: 'runs',
    title: 'Review previous runs',
    body: 'Reopen a run to approve groups or check Metric View results.',
    action: 'Open runs',
    icon: History,
  },
  {
    key: 'dashboard',
    title: 'Migrate dashboards',
    body: 'Tableau .twb/.twbx → AI/BI dashboards, Metric View and Genie Agent.',
    action: 'Start',
    icon: LayoutDashboard,
  },
];

const STEPS = [
  ['Propose', 'Point to your datasources and mapping. The workflow groups them into semantic domains.'],
  ['Approve', 'Check each group’s datasources and target tables, then approve.'],
  ['Review', 'Each group gets a Metric View, a release gate, and a short list of action items.'],
];

const STAGES = [
  ['Translation', 'Every Tableau measure is migrated, or left out with a reason.'],
  ['Contract', 'Grain of each table, and how each measure can be totalled.'],
  ['Design', 'Each measure’s SQL is checked and queried. Fixable issues are repaired automatically.'],
  ['Parity', 'Numbers match trusted Tableau values. Needs your expected values.'],
  ['Performance', 'Query speed on real query patterns. Not measured yet.'],
  ['Certify', 'An accountable owner approves it for production.'],
];

const STATUSES = [
  ['Blocked', 'danger', 'Something must be fixed before the Metric View can be used.'],
  ['Needs review', 'warning', 'Works, but a person must confirm a few decisions.'],
  ['Ready for parity', 'success', 'Checks pass. Next, compare numbers with Tableau.'],
];

const HUMAN_ONLY = [
  'Missing or ambiguous table mappings',
  'Business decisions (e.g. accept a Tableau feature that can’t migrate)',
  'Expressions automatic repair could not fix',
  'Permission or warehouse problems',
  'Expected numbers from Tableau',
  'Production sign-off',
];

export function HomePage({ onStart }: { onStart: (option: StartOption) => void }) {
  return (
    <div className="home">
      <section className="home-hero">
        <h2>Migrate Tableau semantic models to Databricks Metric Views</h2>
        <p>Grouped, evaluated, and repaired automatically. You only review what truly needs a person.</p>
      </section>

      <section aria-labelledby="home-start">
        <h3 id="home-start">Get started</h3>
        <div className="home-options">
          {OPTIONS.filter((option) => DASHBOARD_MIGRATION_ENABLED || option.key !== 'dashboard').map(
            ({ key, title, body, action, icon: Icon, primary }) => (
              <article key={key} className={primary ? 'home-option home-option--primary' : 'home-option'}>
                <Icon className="size-5" aria-hidden="true" />
                <h4>{title}</h4>
                <p>{body}</p>
                <Button variant={primary ? 'default' : 'outline'} onClick={() => onStart(key)}>
                  {action} <ArrowRight className="size-4" aria-hidden="true" />
                </Button>
              </article>
            )
          )}
        </div>
      </section>

      <section aria-labelledby="home-how">
        <h3 id="home-how">How it works</h3>
        <ol className="home-steps">
          {STEPS.map(([title, body], index) => (
            <li key={title}>
              <span>{index + 1}</span>
              <div>
                <strong>{title}</strong>
                <p>{body}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="home-eval" className="home-eval">
        <div>
          <h3 id="home-eval">How Metric Views are evaluated</h3>
          <ol className="home-stages">
            {STAGES.map(([title, body]) => (
              <li key={title}>
                <strong>{title}</strong>
                <span>{body}</span>
              </li>
            ))}
          </ol>
          <h4>What the status means</h4>
          <ul className="home-statuses">
            {STATUSES.map(([label, tone, body]) => (
              <li key={label}>
                <span className={`status-badge status-badge--${tone}`}>{label}</span>
                <span>{body}</span>
              </li>
            ))}
          </ul>
          <h4>A person is needed only for</h4>
          <ul className="home-human">
            {HUMAN_ONLY.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
        <figure className="home-figure">
          <img
            src="/metric-view-report-example.png"
            alt="Semantic group review: run status, group list, membership, Metric View link, and release gate stages"
          />
          <figcaption>Step 3: each group shows its status, membership, Metric View link, and release gate.</figcaption>
        </figure>
      </section>
    </div>
  );
}
