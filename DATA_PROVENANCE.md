# Data Provenance

This file records the evidence and release decision for third-party datasets
shipped by pi-steel. The repository's MIT license covers StructuPath-authored
code and documentation; it must not be interpreted as granting rights in
third-party data.

[`DATA_PROVENANCE.json`](DATA_PROVENANCE.json) is the machine-readable release
record checked against the shipped bytes. This document provides the supporting
human-readable evidence and decision rationale.

## AISC shapes database

| Field | Recorded value |
| --- | --- |
| Shipped file | `skills/steel-takeoff/assets/aisc-shapes-database.json` |
| Claimed edition | AISC Shapes Database v16.0, consistent with the 16th Edition Steel Construction Manual |
| Rows in shipped JSON | 477 |
| SHA-256 | `5a7c975c4c290c34df6f7df3b4d0d0d13a00ef7c2b1f45097a49a78d245dcc91` |
| Upstream description | [AISC Shapes Database v16.0](https://www.aisc.org/aisc/publications/steel-construction-manual/aisc-shapes-database-v160/) |
| Release evidence | [AISC's August 14, 2023 companion-material announcement](https://www.aisc.org/news/aisc-releases-complementary-materials-for-the-16th-edition-steel-construction-manual/) |
| Repository introduction | Initial repository commit |
| Transformation history | Unknown; no source workbook, conversion script, field map, or contemporaneous checksum is present in repository history |
| Upstream file checksum | Not recorded; the checked-in JSON cannot currently be byte- or row-reconciled to a preserved source workbook |
| Redistribution permission | Unverified |
| Release gate | Blocked pending affirmative redistribution evidence or replacement with a dataset whose redistribution terms are documented |

The upstream pages establish that AISC publishes the v16.0 spreadsheet as a
downloadable digital supplement and describe its relationship to the 16th
Edition Manual. They do not, based on the evidence recorded here, grant
permission to redistribute a transformed copy in another public package.
Availability without charge is not treated as redistribution permission.

Until the release gate is resolved:

- Do not claim that the repository's MIT license covers the shapes data.
- Do not claim that the checked-in JSON is an independently reproducible
  transformation of the official workbook.
- Do not publish a new release containing this file without documented approval
  or a documented replacement decision.
- Continue verifying the recorded checksum so an unexplained data change cannot
  pass unnoticed.
