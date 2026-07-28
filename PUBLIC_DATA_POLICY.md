# Public Data Policy

This repository is public. Source code, documentation, tests, fixtures, generated
goldens, commit metadata, issue text, and release artifacts must be safe for public
distribution.

## Allowed

- Clearly labeled synthetic projects, customers, vendors, people, and identifiers.
- Published standards data whose source, edition, license, and redistribution rights
  are documented.
- Invented dimensions and quantities that do not reproduce a private project.
- Placeholder configuration such as `Example Fabricator` and `Example City, ST`.
- Product behavior and generic steel-domain terminology.

## Prohibited

- Private company names or identifiers other than the public StructuPath product
  identity.
- Customer, vendor, employee, subcontractor, or project names and contact details.
- Real job numbers, drawing references, addresses, schedules, quotes, bids, rates,
  margins, payroll, costs, terms, or contract language.
- Production drawings, takeoffs, BOMs, nests, RFQs, quotes, reports, screenshots, or
  generated artifacts, including "anonymized" copies derived from them.
- Company profiles, logos, signatures, credentials, tokens, local absolute paths, or
  exported cloud files.
- Facts that link this product to a private operating company, facility, customer, or
  internal workflow unless separately approved for publication.

## Fixture Rules

1. Create fixtures from scratch; do not sanitize production files for public use.
2. Prefix project-like identifiers with `SYNTHETIC-` or `EXAMPLE-`.
3. Use `Example Customer`, `Example Vendor`, `Example Fabricator`, and
   `Example City, ST` unless a test requires another obviously fictional value.
4. Omit prices and commercial terms unless the test specifically requires them. When
   required, label values as synthetic in the same fixture.
5. Keep private inputs and generated outputs outside the repository in ignored
   directories such as `private/`, `local-data/`, `customer-data/`, or `outputs/`.
6. Run `python3 scripts/check-public-data.py` before every commit and release.
7. Put private names and identifiers, one per line, in the ignored local file
   `.pi-steel/private-terms.txt`; the scanner checks them without committing the
   denylist or echoing matched text.

Git history is public too. Removing a value from the current tree does not remove it
from prior commits; history cleanup requires an explicit coordinated rewrite.
