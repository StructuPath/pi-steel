# Data Provenance

This file records the evidence and release decision for datasets shipped by
pi-steel. [`DATA_PROVENANCE.json`](DATA_PROVENANCE.json) is the machine-readable
release record checked against the shipped bytes.

## StructuPath Structural Shapes Database

| Field | Recorded value |
| --- | --- |
| Dataset name | StructuPath Structural Shapes Database |
| Shipped file | `skills/steel-takeoff/assets/aisc-shapes-database.json` |
| Source | Original StructuPath dataset created from StructuPath's internal structural-shape records |
| Rows in shipped JSON | 477 |
| SHA-256 | `5a7c975c4c290c34df6f7df3b4d0d0d13a00ef7c2b1f45097a49a78d245dcc91` |
| Repository introduction | Initial repository commit |
| Copyright holder | StructuPath |
| Redistribution permission | Authorized |
| Authorization | Authorized by StructuPath for public redistribution in @structupath/pi-steel under the MIT license on 2026-07-28 |
| License | MIT |
| Release gate | Ready |

StructuPath confirms that it created this database from its own internal
structural-shape records and that the dataset is not sourced from AISC. StructuPath owns the
dataset and has authorized its public redistribution in `@structupath/pi-steel`
under the MIT license.

The dataset uses standard structural-shape designations and property names.
Those references identify industry-standard members; they do not imply that the
shipped database was copied, transformed, or licensed from AISC.

The release check verifies the recorded path, row count, required fields,
designation uniqueness, SHA-256 digest, ownership, license, authorization, and
release decision. Any change to the shipped bytes or provenance record requires
a new review.
