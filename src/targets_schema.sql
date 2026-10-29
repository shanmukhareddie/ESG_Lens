-- Climate targets (ESRS E1-4): absolute cuts in a company's own emissions.
CREATE TABLE IF NOT EXISTS Targets (
  target_id serial PRIMARY KEY,
  company_id int REFERENCES Companies(company_id) NOT NULL,
  scope varchar NOT NULL,
  CONSTRAINT chk_scope CHECK (scope IN ('1', '2', '1+2', '3', '1+3', '1+2+3')),
  base_year int,
  target_year int NOT NULL,
  reduction_pct decimal NOT NULL,
  CONSTRAINT chk_pct CHECK (reduction_pct > 0 AND reduction_pct <= 100),
  source varchar NOT NULL,
  CONSTRAINT chk_target_source CHECK (source IN ('labelled', 'extracted')),
  page_number int,
  quoted_sentence varchar,
  pdf_url varchar,
  loaded_at timestamp,
  CONSTRAINT one_target UNIQUE (company_id, scope, target_year)
);
