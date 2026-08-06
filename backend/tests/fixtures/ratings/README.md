# BSE rating-announcements fixtures

Recorded 2026-08-06 against the live BSE API using
`app.companies.universe.fetchers.fetch_bytes` (already carries the browser
headers BSE requires — no code was written for this task, it is pure
investigation).

## Working query

Endpoint: `https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w`

```
GET /BseIndiaAPI/api/AnnSubCategoryGetData/w
    ?pageno=1
    &strCat=Company+Update
    &subcategory=Credit+Rating
    &strPrevDate=20260707
    &strToDate=20260806
    &strScrip=
    &strSearch=P
    &strType=C
```

The rating-related category is **not** its own top-level category. `strCat=
Credit+Rating` (the literal spelling one would guess) returns `{"Table": [],
"Table1": [{"ROWCNT": 0}]}` — a genuinely empty result, not an error; it is
simply the wrong bucket. Rating actions are filed under the broad
`strCat=Company+Update` category, disambiguated by `subcategory=Credit+
Rating`. Confirmed: 279 rows (`Table1[0].ROWCNT`) in the 30-day window above,
all with `SUBCATNAME` = `"Credit Rating"` and `NEWSSUB` carrying the generic
LODR boilerplate (e.g. `"Welspun Corp Ltd - 532144 - Announcement under
Regulation 30 (LODR)-Credit Rating"`) — the `"-Credit Rating"` suffix
confirms the subcategory, but `NEWSSUB` never names the rating agency. The
agency name (and often the action — reaffirm/upgrade/downgrade — and the
resulting grade) lives in `HEADLINE` instead, e.g. `"Care Ratings Reaffirms
its rating on the Company''s Long Term Facilities and Non-Convertible
Debentures to ''CARE AA+; Stable''"` for that same Welspun row. 18 of the 50
rows in the fixture have an agency name (CRISIL/ICRA/CARE/India Ratings)
directly in `HEADLINE`; the rest use generic phrasing ("as per enclosed
letter.", "has informed the Exchange about the credit rating.") and require
opening the PDF to identify the agency — see Task 3/4.

The category-list endpoints named in the brief both 404 (return BSE's
generic "page has been moved" HTML shell, HTTP 200, not JSON):
`ddlcategorys/w`, `AnnGetCat/w`, `AnnGetCategory/w`, `AnnGetSubCategory/w`.
The (strCat, subcategory) pair above was found by brute-forcing candidate
`strCat` values against the confirmed-working `AnnSubCategoryGetData/w`
endpoint, reading the `SUBCATNAME` field back out of `strCat=Company+Update&
subcategory=-1` results, and then re-querying with that subcategory pinned.

**Surprise — undocumented date-range cap.** `AnnSubCategoryGetData/w` silently
enforces a maximum `strPrevDate`..`strToDate` span. Empirically: a 30-day
window (`20260707`..`20260806`) succeeds; anything wider (tested 35, 45, 66
days) returns `{"Status": false, "Message": "Date range exceeded
threshold."}` — HTTP 200, so a caller that only checks `Table` (defaulting
to `[]` on a missing key, as an early version of this probe did) will
silently misread "date range rejected" as "no rating actions in this
period." **Task 3's fetcher must check `Status`/`Message` (or the presence
of `Table1`) before trusting an empty `Table` as a true zero, and must
paginate across sequential ≤30-day windows to cover any wider lookback.**
The brief's own worked example (`strPrevDate=20260601&strToDate=20260806`,
a 66-day span) is itself over this cap and fails today with the same
message — it happened to return 50 rows for `Corp. Action` at some earlier
point in this same session, which is hard to reconcile except as a fluke of
a since-tightened or inconsistently-enforced threshold; treat 30 days as the
safe upper bound and do not rely on wider single-shot windows.

No rate-limit (HTTP 429) or WAF block was hit in ~35 requests spaced ≥1.5s
apart.

## Observed row keys

Each row in `Table` (see `announcements_page.json`) has:

```
NEWSID, SCRIP_CD, XML_NAME, NEWSSUB, DT_TM, NEWS_DT, CRITICALNEWS,
ANNOUNCEMENT_TYPE, QUARTER_ID, FILESTATUS, ATTACHMENTNAME, MORE, HEADLINE,
CATEGORYNAME, OLD, RN, PDFFLAG, NSURL, SLONGNAME, AGENDA_ID,
News_submission_dt, DissemDT, TimeDiff, Fld_Attachsize, SUBCATNAME,
BSENewsid, Investor_Presentation, AUDIO_VIDEO_FILE
```

Fields relevant to extraction: `SCRIP_CD` (BSE scrip code, int), `SLONGNAME`
(company name), `NEWSSUB` (subject line — generic LODR boilerplate only,
`"<Company> - <scrip code> - Announcement under Regulation 30
(LODR)-Credit Rating"`; useful for confirming the subcategory via its
`"-Credit Rating"` suffix, but never names the agency), `HEADLINE` (the
agency-bearing field — free text written per-filing, e.g. `"Credit rating by
ICRA Limited"` for the Avenue Supermarts Ltd row, or `"Care Ratings
Reaffirms its rating on the Company''s Long Term Facilities and
Non-Convertible Debentures to ''CARE AA+; Stable''"` for Welspun Corp Ltd;
present but generic ("as per enclosed letter.") on rows where the filer
didn't restate the agency in the headline), `ATTACHMENTNAME` (bare filename,
always seen as `.pdf` here — no non-PDF attachments observed among the 50
rows on this page), `NEWS_DT` (ISO timestamp string), `Fld_Attachsize`
(bytes, matches the fetched PDF size exactly), `SUBCATNAME` (`"Credit
Rating"` for every row on this page, confirming the subcategory filter
worked), `CATEGORYNAME` (`"Company Update"`, confirming the category).

`Table1` is a single-row sidecar carrying `ROWCNT`, the total row count for
the query (`279` here) — needed for pagination in Task 3, distinct from the
50 rows returned per page.

## Attachment URL pattern

```
https://www.bseindia.com/xml-data/corpfiling/AttachLive/{ATTACHMENTNAME}
```

`ATTACHMENTNAME` is the bare value from the row (a GUID + `.pdf`, e.g.
`5b4c8c09-5df9-486f-929c-4d770d7dd78c.pdf`); no encoding or prefix needed.
Fetched with the same `fetch_bytes` (browser headers apply to the PDF host
too — plain `urllib` without them was not tried, so it's unconfirmed whether
the attachment host actually requires them, but there is no reason to strip
them).

## Fixture provenance

- **`announcements_page.json`** — verbatim page-1 response (50 rows) of the
  working query above, fetched 2026-08-06. Window: `strPrevDate=20260707`,
  `strToDate=20260806`.
- **`rationale_sample.pdf`** — company **Transrail Lighting Ltd** (BSE scrip
  `544317`), agency **India Ratings & Research** (Ind-Ra), fetched from
  `https://www.bseindia.com/xml-data/corpfiling/AttachLive/5b4c8c09-5df9-486f-929c-4d770d7dd78c.pdf`
  (400,861 bytes — matches `Fld_Attachsize` exactly; under the 500 KB cap).
  `NEWS_DT` `2026-08-04T17:47:01.793`. `pypdf` (6.14.2, installed for this
  probe) extracts 8 pages / 21,588 characters of clean text — confirms the
  library works on a real BSE attachment.

  This one was picked over several smaller (~150-320 KB) candidates
  (Ambuja Cements/ICRA, Mawana Sugars/ICRA, GIC Housing Finance, Adani
  Energy Solutions, Hindustan Composites, NRB Bearings, KNR Constructions,
  B.D. Industries, Aditya Birla Money, Panchmahal Steel) because those are
  all single-page company transmittal letters that only state the rating
  action ("ICRA has assigned/reaffirmed rating X to facility Y") with no
  business description or named counterparty — they carry the company's
  covering letter but not the agency's actual rationale text. Transrail's
  attachment (400 KB, 8 pages) includes the company's one-page covering
  letter *followed by* Ind-Ra's full rationale press release, which is the
  shape Task 4's extraction targets.

  Verbatim sentences naming a counterparty / describing the business (seed
  material for Task 3/4's evidence-gate tests):

  > "TLL is a leading engineering procurement & construction company, with
  > over three decades of experience and a presence across the power T&D,
  > lighting infrastructure, substations, railways and civil construction
  > sectors."

  > "In October 2016, the T&D business division of Gammon India Ltd. was
  > transferred to TLL through a business transfer agreement. Gammon India
  > transferred its 75% equity in TLL to Ajanma Holdings Private Limited."

  > "The company manages the working capital cycle through its strong
  > supplier network and LC, which have a usance period of 120-150 days."

  The second quote is the strongest counterparty-evidence candidate: it
  names **Gammon India Ltd.** as a specific corporate counterparty (business
  transfer + former majority shareholder), verbatim-quotable and
  substring-matchable against the extracted PDF text.

## Other surprises

- Several rows on the sample page repeat the same `SLONGNAME` with two
  different `ATTACHMENTNAME`s and identical `Fld_Attachsize` (B. D.
  Industries (Pune) Ltd; ZF Steering Gear India Ltd-$) — apparently
  duplicate filings (e.g. one to BSE, one to NSE, both disseminated through
  BSE) rather than a fetch bug. Task 3/5 dedup logic should not assume
  `ATTACHMENTNAME` uniqueness per company per day.
- `QUARTER_ID`, `BSENewsid`, `Investor_Presentation`, `AUDIO_VIDEO_FILE` are
  `null` on every row seen — not populated for this category.
- No empty/zero-byte attachments and no non-PDF (`.zip`, `.xml`, `.docx`)
  attachments were observed among the 50 rows fetched for the JSON fixture,
  though only a handful of the 50 attachments were actually downloaded and
  inspected (see provenance list above) — this is not an exhaustive claim
  about the full 279-row window.
