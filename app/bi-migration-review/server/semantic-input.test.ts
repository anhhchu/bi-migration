import { describe, expect, it } from 'vitest';
import { semanticInputRoot } from './semantic-input';

const root = '/Volumes/main/bi_migration/tableau_datasources';

describe('semanticInputRoot', () => {
  it('accepts the input folder or its datasources subfolder', () => {
    expect(semanticInputRoot(root, `${root}/mappings/table-mapping.yaml`)).toBe(root);
    expect(semanticInputRoot(`${root}/datasources/`, `${root}/mappings`)).toBe(root);
  });

  it('rejects a mapping outside a mappings folder', () => {
    expect(() => semanticInputRoot(root, `${root}/table-mapping.yaml`)).toThrow(/mappings folder/);
    expect(semanticInputRoot(root, `${root}/mappings/my tables.csv`)).toBe(root);
  });

  it('rejects datasources and mappings from different input folders', () => {
    expect(() => semanticInputRoot('/Volumes/main/bi/other', `${root}/mappings`)).toThrow(
      `Expected ${root}/datasources`
    );
  });
});
