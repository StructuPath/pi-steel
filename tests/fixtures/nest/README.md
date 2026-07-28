# Synthetic Nest Fixtures

The files in this directory were created from scratch for pi-steel tests. They
are not copied, transformed, rounded, renamed, or anonymized from production,
customer, vendor, drawing, takeoff, inventory, or commercial data.

`irregular-reference-only.json` uses invented geometry to prove that an
unresolved irregular outline remains reference-only and cannot produce a burn
DXF. It establishes no compatibility claim for any CAM product or version.

`grouped-engine.json` uses invented plate and part dimensions to exercise
material/grade/thickness segregation, finite and unlimited stock, and
same-display-name stock identities. It contains no pricing.
