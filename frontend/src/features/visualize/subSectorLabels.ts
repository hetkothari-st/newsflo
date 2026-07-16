// Kept in sync manually with backend/app/companies/sub_sectors.py's
// SUB_SECTOR_TAXONOMY -- frontend can't import backend Python, same
// "duplicated on purpose" tradeoff already used for SECTOR_LABEL/RULE_LABELS.

const SUB_SECTOR_LABEL: Record<string, string> = {
  upstream_exploration: 'Upstream & Exploration',
  refining_marketing: 'Refining & Marketing',
  gas_distribution: 'Gas Distribution',
  oil_gas_other: 'Other Oil & Gas',

  private_bank: 'Private Bank',
  psu_bank: 'PSU Bank',
  nbfc: 'NBFC',
  housing_finance: 'Housing Finance',
  insurance: 'Insurance',
  asset_management: 'Asset Management',
  banking_other: 'Other Banking',

  passenger_vehicle: 'Passenger Vehicles',
  two_wheeler: 'Two-Wheelers',
  commercial_vehicle: 'Commercial Vehicles',
  auto_component: 'Auto Components',
  auto_other: 'Other Auto',

  it_services_large_cap: 'IT Services (Large Cap)',
  it_services_mid_small_cap: 'IT Services (Mid/Small Cap)',
  product_saas: 'Product / SaaS',
  it_other: 'Other IT',

  generics_formulations: 'Generics & Formulations',
  specialty_pharma: 'Specialty Pharma',
  hospital_diagnostics: 'Hospitals & Diagnostics',
  api_cdmo: 'API / CDMO',
  pharma_other: 'Other Pharma',

  staples_food: 'Staples & Food',
  personal_care: 'Personal Care',
  beverages: 'Beverages',
  retail: 'Retail',
  fmcg_other: 'Other FMCG',

  steel: 'Steel',
  non_ferrous: 'Non-Ferrous Metals',
  mining_coal: 'Mining & Coal',
  metals_other: 'Other Metals',

  telecom_operator: 'Telecom Operator',
  telecom_infrastructure: 'Telecom Infrastructure',
  telecom_other: 'Other Telecom',

  construction_engineering: 'Construction & Engineering',
  power_utilities: 'Power & Utilities',
  capital_goods: 'Capital Goods',
  cement: 'Cement',
  infra_other: 'Other Infrastructure',
};

const UNCLASSIFIED_KEY = '__unclassified';

export function subSectorKey(subSector: string | null | undefined): string {
  return subSector ?? UNCLASSIFIED_KEY;
}

export function subSectorLabel(subSector: string | null | undefined): string {
  if (subSector == null) return 'Unclassified';
  return SUB_SECTOR_LABEL[subSector] ?? subSector;
}

export { UNCLASSIFIED_KEY };
