const TABLE_MAPPING_FILE = /\/table-mapping\.(csv|ya?ml)$/i;

function normalize(value: string) {
  return value.trim().replace(/\/+$/, '');
}

/**
 * Resolve the workflow's input root from the two paths a user enters.
 *
 * The datasource path may be the input folder itself or its `datasources/` subfolder.
 * The mapping path may be the `mappings/` folder or the table-mapping file inside it.
 */
export function semanticInputRoot(datasourcePath: string, mappingPath: string): string {
  const datasource = normalize(datasourcePath);
  const mapping = normalize(mappingPath);
  const mappingDirectory = TABLE_MAPPING_FILE.test(mapping) ? mapping.slice(0, mapping.lastIndexOf('/')) : mapping;
  if (!mappingDirectory.endsWith('/mappings')) {
    throw new Error(
      'Mapping path must be the mappings folder or the table-mapping.yaml, .yml, or .csv file inside it.'
    );
  }
  const mappingRoot = mappingDirectory.slice(0, -'/mappings'.length);
  const datasourceRoot = datasource.endsWith('/datasources') ? datasource.slice(0, -'/datasources'.length) : datasource;
  if (datasourceRoot !== mappingRoot) {
    throw new Error(
      `Datasources and mappings must be in the same input folder. Expected ${mappingRoot}/datasources for this mapping.`
    );
  }
  return datasourceRoot;
}
