# Regulatory basis for protecting grid data

This is a practitioner summary in our own words, not legal advice. Release decisions belong
to the utility's privacy officer, CIP compliance lead, or counsel. The skill's decision
points exist to route those decisions to them.

## CEII: Critical Energy/Electric Infrastructure Information (US)

- **What.** The FAST Act (2015) §61003, codified at 16 U.S.C. 824o-1, defines CEII. FERC's
  rules are at **18 CFR 388.113**. CEII covers specific engineering, vulnerability, or
  detailed design information about proposed or existing critical electric infrastructure
  that could be useful to a person planning an attack and that goes beyond location alone.
- **In utility data, typically:** one-line diagrams, substation and feeder topology and
  connectivity, transformer/breaker inventories tied to locations, protection and relay
  settings, SCADA point lists and network addressing, and planning-model files.
- **How the skill handles it.** Topology and settings columns are classed `CEII_TOPOLOGY` /
  `CEII_SETTINGS`. Internally they are masked for anyone outside the privileged group.
  Aggregate releases drop settings always, and public releases cannot group by topology.

## NERC CIP: BES Cyber System Information

- **CIP-011** (Information Protection) requires entities to identify BES Cyber System
  Information (BCSI) and protect it in storage, transit, and use. **CIP-004** governs who is
  authorized to access it.
- SCADA addressing, network diagrams, and security configurations are typical BCSI. The
  skill's `privileged_group` should map to the CIP-004 access list, not an ad-hoc group.

## Customer energy-usage data: the 15/15 aggregation rule (California)

- The **CPUC** adopted privacy rules for customer energy-usage data (smart-meter
  "Customer Data Access" proceeding, Decisions **D.11-07-056** and **D.14-05-016**). For
  releases of aggregated usage without customer consent, the commonly applied standard is
  the **15/15 rule**: each aggregate must include at least **15 customers**, and no single
  customer may account for more than **15 %** of the aggregate's load. The rule was first
  used in CPUC direct-access proceedings (D.97-10-031).
- Other jurisdictions use variants: different k (e.g. 4, 5, 10, 100), share caps, or
  rate-class-specific rules. That is why `aggregation_rule='k_only'` with a custom `k_min`
  exists. Check your commission's rules.
- **Record-level** customer data shared with third parties generally needs customer
  authorization (e.g. Green Button Connect / Click-Through). This skill only produces
  record-level outputs for `internal_need_to_know`.

## Smart-meter data as personal data (EU / UK)

- The Article 29 Working Party (now EDPB) **Opinion 12/2011 on smart metering (WP183)**
  treats household consumption data as personal data. Fine-grained load shapes can reveal
  occupancy, routines, and appliance use.
- **Commission Recommendation 2014/724/EU** sets out a Data Protection Impact Assessment
  template for smart grid and smart metering systems.
- **GDPR Art. 4(5) / Recital 26.** Pseudonymized data (tokens) is still personal data;
  only properly anonymized aggregates fall outside GDPR.

## Sources

- 18 CFR 388.113: https://www.ecfr.gov/current/title-18/chapter-I/subchapter-X/part-388/subpart-B/section-388.113
- FERC CEII guidance: https://www.ferc.gov/ceii
- NERC CIP standards (CIP-004, CIP-011): https://www.nerc.com/pa/Stand/Pages/ReliabilityStandards.aspx
- CPUC energy data access and privacy: https://www.cpuc.ca.gov/industries-and-topics/electrical-energy/infrastructure/energy-data-access
- Article 29 WP Opinion 12/2011 (WP183): https://ec.europa.eu/justice/article-29/documentation/opinion-recommendation/files/2011/wp183_en.pdf
- Commission Recommendation 2014/724/EU: https://eur-lex.europa.eu/eli/reco/2014/724/oj
