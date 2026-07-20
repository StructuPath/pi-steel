---
name: steel-rfq
description: "Generate standardized Request for Quotation (RFQ) spreadsheets from steel estimate takeoff files. Use this skill whenever someone mentions RFQ, request for quote, vendor quote, material quote, sending a material list to vendors, quoting steel, or getting pricing from a supplier. Also trigger when someone uploads a steel estimate or takeoff spreadsheet and wants to send it out for pricing. Even if they just say 'I need to send this to my vendor' or 'get me prices on this material' — that's an RFQ."
---

# Steel RFQ Generator

## What This Skill Does

This skill takes a steel estimate/takeoff spreadsheet (.xlsx) and produces a clean, standardized RFQ spreadsheet that can be sent directly to steel vendors. The output is always an Excel file with a consistent layout so every vendor gets the same professional format regardless of who creates it.

The RFQ format was designed around how steel vendors actually work — materials grouped by type (W-shapes, plates, flat bar) so vendors can quickly identify what they have in stock, quote pricing, and flag what they don't carry.

## Company Profile (required setup)

The RFQ carries the requesting company's identity. Load it from
`assets/company-profile.json` in this skill's directory (copy
`company-profile.example.json` and edit). If the file is missing, ask the
user for their company name, city/state, and payment terms before
generating, and offer to save the answers as `company-profile.json` for
next time.

Profile fields:
- `company_name` — appears in the header and terms & conditions
- `city_state` — appears in the header (e.g., "Denver, CO")
- `payment_terms` — default "Net 30 from date of delivery"
- `quote_validity_days` — default 30
- `logo` — optional filename in `assets/` to embed top-left

Never invent company details. If the profile is incomplete, ask.

## Input

Always a steel estimate spreadsheet (.xlsx). These files typically have:
- A "Steel Takeoff" sheet (or similar) with line items for structural members, plates, and connection hardware
- Item numbers (A-01, B-01, C-01, etc.), categories, descriptions, sizes, quantities, stock lengths, and weights
- Items marked "BY OTHERS" (typically purlins) that are NOT part of the fabricator's scope

The first step is always to read and understand the takeoff data before generating the RFQ.

## Reading the Estimate

1. Use pandas to read all sheets: `pd.ExcelFile(path)` then inspect sheet names
2. Find the takeoff sheet (look for "Takeoff", "Steel Takeoff", "Material List", "BOM", or the sheet with item-level steel data)
3. Read the full sheet with `header=None` to capture all rows including section headers
4. Identify the data structure:
   - Section headers (e.g., "A. MAIN BUILDING — W-SHAPES")
   - Column headers (Item, Category, Description, Size, Qty, Length, Weight, Stock Purchase, Purchase Wt, Notes)
   - Line items with actual material data
   - Items with "BY OTHERS" in the description — these get **excluded**
   - Subtotal and total rows

## RFQ Output Format

The output is always a single .xlsx file with this exact structure:

### Header Block (Rows 1–3)
- **Row 1**: "REQUEST FOR QUOTATION — Structural Steel" — dark blue background (#1F3864), white bold Arial 14pt, merged across all columns
- **Row 2**: "[Project Name] | [Company Name] — [City, ST]" — same dark blue, white bold Arial 11pt
- **Row 3**: "Date Issued: [today] | Response Requested By: _______________ | Project Location: [location]" — same dark blue, white Arial 10pt

### Vendor Info Block (Rows 4–6)
Fillable fields for the vendor:
- Row 5: Company Name (merged A–B, input in C–E yellow) | Contact Name (merged F–G, input in H–J yellow)
- Row 6: Phone/Email (merged A–B, input in C–E yellow) | Quote Valid Until (merged F–G, input in H–J yellow)

### Instructions Row (Row 7)
Single merged row with italic gray text explaining how to fill out the yellow columns. Text:
> "Instructions: Please fill in the YELLOW columns (Unit Price, Total Price, Availability, Lead Time, Alternate Size, Notes). Mark Availability as 'In Stock', 'Lead Time', or 'Unavailable'. If suggesting an alternate size, list it and adjust pricing accordingly."

### Column Headers (Row 8)
14 columns with medium blue background (#2E75B6), white bold Arial 10pt:

| Column | Header | Width | Purpose |
|--------|--------|-------|---------|
| A | Item | 7 | Item number from estimate (A-01, C-02, E-01, etc.) |
| B | Category | 13 | Columns, Girders, Plate, Flat Bar, etc. |
| C | Description | 38 | Full description including which structure it belongs to |
| D | Size / Designation | 22 | AISC shape or plate dimensions |
| E | Grade | 12 | A992 Gr.50, A572 Gr.50, A36, etc. |
| F | Qty | 6 | Number of pieces or sticks needed |
| G | Stock Length / Size | 20 | How it's being purchased (e.g., "3 sticks × 30′") |
| H | Est. Purchase Wt (lbs) | 20 | Weight from the estimate |
| I | Unit Price ($) | 14 | **VENDOR FILLS** — yellow background |
| J | Total Price ($) | 14 | **VENDOR FILLS** — yellow background |
| K | Availability | 14 | **VENDOR FILLS** — yellow background |
| L | Lead Time (days) | 14 | **VENDOR FILLS** — yellow background |
| M | Alternate Size | 18 | **VENDOR FILLS** — yellow background |
| N | Notes | 30 | **VENDOR FILLS** — yellow background |

Vendor columns (I–N) get a darker gold header (#BF8F00) to distinguish them from the material data columns.

### Material Data Rows

**Grouping**: Always group by material type, not by structure. The three groups are:
1. **W-SHAPES — [Grade]** (columns and girders from all structures combined)
2. **PLATE STOCK — [Grade]** (all plate material)
3. **FLAT BAR STOCK — [Grade]** (all flat bar material)

Each group gets a section header row: merged across all columns, medium blue background, white bold text.

**Data rows**:
- Alternate row shading: light blue (#D6E4F0) and white
- Vendor columns (I–N) always have yellow background (#FFF2CC) regardless of row
- Weight column (H) formatted as `#,##0`
- Price columns (I–J) formatted as `$#,##0.00`
- All cells have thin borders

**Filtering rules**:
- EXCLUDE any item where the description contains "BY OTHERS" (purlins, etc.)
- EXCLUDE any item where Qty = 0
- If the estimate has a "Stock Purchase" section (Section E or similar) with consolidated purchase items for plates/flat bar, use those instead of the individual connection plate items. The stock purchase items represent what's actually being ordered (full sheets, full bars), which is what the vendor needs to quote.
- Keep individual W-shape items because each shape/length combination matters for vendor stock

### Totals Row
- "TOTAL PURCHASE WEIGHT / PRICE" label merged A–G, right-aligned bold
- Column H: `=SUM(H[first]:H[last])` formula for total weight, green background (#E2EFDA)
- Column J: `=SUM(J[first]:J[last])` formula for total price, green background

### Nesting / Drop Reference Table
Below the totals (skip a row), add a reference section:
- Header: "NESTING / DROP REFERENCE (For Fabricator Use)" — dark blue bold text
- Three columns: Material | Nesting Plan | Drop Notes
- Column headers with medium blue background
- One row per material showing the nesting layout and expected drop from the estimate
- This helps cross-check vendor stock lengths against the cutting plan

### Standard Terms & Conditions
Below the nesting table (skip a row), add:
- Header: "TERMS & CONDITIONS" — dark blue bold text
- Include these standard terms, each on its own row, substituting the company name and payment terms from the company profile:

1. **Delivery**: All material to be delivered FOB jobsite unless otherwise agreed. Vendor to confirm freight costs separately.
2. **Mill Certifications**: Mill test reports (MTRs) required for all structural steel per AISC/AWS standards. Certs must accompany delivery.
3. **Payment Terms**: [payment_terms from profile] unless otherwise negotiated in writing.
4. **Material Standards**: All wide-flange shapes to meet ASTM A992. All plate and bar to meet grade specified on this RFQ (A572 Gr.50 or A36).
5. **Substitutions**: No substitutions without prior written approval from [Company Name]. If quoting alternate sizes, clearly note in the "Alternate Size" column.
6. **Quote Validity**: Quoted prices to remain firm for [quote_validity_days] days from date of quote unless otherwise stated.
7. **Inspection**: [Company Name] reserves the right to inspect material upon delivery and reject material not meeting specifications.
8. **Cancellation**: Orders may be cancelled without penalty if material has not shipped. Restocking fees, if any, to be stated in quote.

### Branding / Logo
If the company profile names a logo file and it exists in the skill's `assets/` directory, insert it in cell A1 area (top-left) and adjust the header text to not overlap. Otherwise use the text header as described above.

## Print Setup
- Orientation: Landscape
- Fit to width: 1 page
- Fit to height: 0 (auto)
- Print title rows: Row 8 (column headers repeat on each page)

## File Naming
Output file: `[ProjectName]_RFQ_Material_List.xlsx`
- Extract project name from the estimate file (look in "Project Info" sheet or the first rows of the takeoff)
- Replace spaces with underscores
- Example: `Cherokee_Boys_RFQ_Material_List.xlsx`

## Step-by-Step Workflow

1. Load the company profile (or collect it from the user — see Company Profile above)
2. Read the uploaded estimate file with pandas to understand its structure
3. Identify the takeoff sheet and parse all line items
4. Filter out "BY OTHERS" items and zero-quantity items
5. Group remaining items by material type (W-shapes → Plates → Flat Bar)
6. If there's a stock purchase section, use those for plates/flat bar instead of individual pieces
7. Build the RFQ spreadsheet using openpyxl following the format above
8. Add formulas for totals and verify the SUM ranges cover exactly the data rows
9. Add nesting/drop reference from the estimate notes — or, if the `steel-nest` skill has been run for this job, read its `rfq_nesting.json` output straight into the table
10. Add standard terms & conditions with profile values substituted
11. Insert logo if configured
12. Save the file, then run `python3 scripts/recalc.py <output.xlsx>` so formula values are computed (openpyxl writes formulas but never calculates them)
13. Verify no formula errors and present the file to the user

## Common Variations

**Multiple structures in one project**: Combine all materials into one RFQ, but note which structure each item belongs to in the Description column (e.g., "W12×65 Columns (Bldg A)").

**Plate stock with nesting**: When plates are purchased as full sheets and then cut, show the full sheet as the line item (that's what the vendor ships) and put the cutting plan in the nesting reference table.

**Mixed grades**: Group by material type first, then note the grade in each row. If a project has A992, A572, and A36, they all appear in the appropriate material type section with grade clearly marked.
