import { describe, expect, it } from 'vitest';
import { catalogExplorerUrl } from './catalog-links';

describe('catalogExplorerUrl', () => {
  it('links a three-part name to Catalog Explorer', () => {
    expect(catalogExplorerUrl('https://example.cloud.databricks.com/', 'main.bi_migration.bim_sales_candidate')).toBe(
      'https://example.cloud.databricks.com/explore/data/main/bi_migration/bim_sales_candidate'
    );
  });

  it('strips backticks and encodes unusual characters', () => {
    expect(catalogExplorerUrl('https://w.example', '`my-catalog`.`gold`.`sales view`')).toBe(
      'https://w.example/explore/data/my-catalog/gold/sales%20view'
    );
  });

  it('returns null when the workspace or name is unusable', () => {
    expect(catalogExplorerUrl(null, 'a.b.c')).toBeNull();
    expect(catalogExplorerUrl('https://w.example', 'a.b')).toBeNull();
    expect(catalogExplorerUrl('https://w.example', undefined)).toBeNull();
  });
});
