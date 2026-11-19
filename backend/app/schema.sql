-- Raw evidence tables are written only by ingest and never edited afterwards.
-- Derived knowledge lives in `facts`; corrections supersede facts, they never overwrite them.

CREATE TABLE IF NOT EXISTS documents (
    id            TEXT PRIMARY KEY,          -- D-001 .. D-030
    path          TEXT NOT NULL,             -- repo-relative PDF path
    subsystem     TEXT,
    distribution  TEXT,                      -- clean | degraded-only
    role          TEXT,
    source_path   TEXT,
    source_url    TEXT,
    title         TEXT,                      -- derived from upstream filename
    pages         INTEGER,
    sha256        TEXT,
    derivation    TEXT                       -- JSON, present for degraded scans
);

CREATE TABLE IF NOT EXISTS drawing_pages (
    document_id     TEXT NOT NULL REFERENCES documents(id),
    page            INTEGER NOT NULL,        -- 1-based
    width           REAL,
    height          REAL,
    has_text_layer  INTEGER NOT NULL,        -- 0 for rasterized / degraded scans
    text            TEXT,
    PRIMARY KEY (document_id, page)
);

CREATE TABLE IF NOT EXISTS bom_rows (
    row_index      INTEGER PRIMARY KEY,      -- line number in the CSV (header = 1)
    name           TEXT,
    part_family    TEXT,
    type           TEXT,
    design         TEXT,
    order_state    TEXT,
    vv             TEXT,
    notes          TEXT,
    design_intent  TEXT,
    material       TEXT,
    product_name   TEXT,
    supplier_order TEXT,
    interface_with TEXT,
    link           TEXT,
    supplier       TEXT,
    datasheet      TEXT,
    amount         TEXT,
    cost_raw       TEXT,
    total_cost_raw TEXT,
    raw_json       TEXT NOT NULL             -- the untouched CSV row
);

-- What the vision pass read from each sheet: overall legibility plus every dimension / callout,
-- each with its location on the sheet so answers can cite a region.
CREATE TABLE IF NOT EXISTS drawing_quality (
    document_id  TEXT NOT NULL REFERENCES documents(id),
    page         INTEGER NOT NULL,
    legibility   TEXT,                       -- clear | partly_legible | mostly_illegible
    issues       TEXT,
    extractor    TEXT,                       -- model + prompt version + date
    PRIMARY KEY (document_id, page)
);

CREATE TABLE IF NOT EXISTS drawing_annotations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id  TEXT NOT NULL REFERENCES documents(id),
    page         INTEGER NOT NULL,
    kind         TEXT NOT NULL,              -- dimension | callout
    feature      TEXT,                       -- what it measures / refers to, as read
    text         TEXT,                       -- exactly as written on the sheet ('' if illegible)
    legibility   TEXT,                       -- clear | partial | illegible
    box_2d       TEXT                        -- JSON [y0, x0, y1, x1] on a 0-1000 grid
);

-- Candidate links between a drawing and BOM rows, with how they were found.
CREATE TABLE IF NOT EXISTS doc_bom_links (
    document_id  TEXT NOT NULL REFERENCES documents(id),
    row_index    INTEGER NOT NULL REFERENCES bom_rows(row_index),
    score        REAL,
    method       TEXT,                       -- e.g. filename-fuzzy, title-block, reviewed
    status       TEXT NOT NULL DEFAULT 'candidate',  -- candidate | confirmed | rejected
    PRIMARY KEY (document_id, row_index, method)
);

-- One claim about one subject, with its source. Exactly one active fact per
-- (subject, predicate, source_type) is the normal case; conflicts are kept, not merged.
CREATE TABLE IF NOT EXISTS facts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_type   TEXT NOT NULL,            -- bom_row | document
    subject_id     TEXT NOT NULL,
    predicate      TEXT NOT NULL,            -- material, supplier, cost_dkk, ...
    value          TEXT,
    source_type    TEXT NOT NULL,            -- bom | drawing | correction
    source_ref     TEXT NOT NULL,            -- "BOM row 12", "D-004 p1", "correction 3"
    confidence     REAL,
    status         TEXT NOT NULL DEFAULT 'active',  -- active | superseded
    superseded_by  INTEGER REFERENCES facts(id),
    evidence       TEXT,                     -- JSON: page, box_2d (0-1000, y0 x0 y1 x1), legibility, extractor
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_facts_subject ON facts(subject_type, subject_id, predicate);

CREATE TABLE IF NOT EXISTS corrections (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    proposed_via  TEXT NOT NULL,             -- chat | api
    subject_type  TEXT NOT NULL,
    subject_id    TEXT NOT NULL,
    predicate     TEXT NOT NULL,
    old_value     TEXT,                      -- value(s) active when proposed
    new_value     TEXT NOT NULL,
    rationale     TEXT,
    check_report  TEXT,                      -- JSON produced when the proposal was checked
    status        TEXT NOT NULL DEFAULT 'pending',  -- pending | accepted | rejected
    reviewed_at   TEXT,
    reviewer_note TEXT,
    new_fact_id   INTEGER REFERENCES facts(id)
);

CREATE TABLE IF NOT EXISTS models3d (
    document_id  TEXT PRIMARY KEY REFERENCES documents(id),
    path         TEXT NOT NULL,              -- repo-relative .glb
    method       TEXT NOT NULL,
    spec_json    TEXT NOT NULL,              -- the dimensions + evidence used to build it
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL DEFAULT (datetime('now')),
    action     TEXT NOT NULL,
    entity     TEXT NOT NULL,
    entity_id  TEXT,
    detail     TEXT
);
