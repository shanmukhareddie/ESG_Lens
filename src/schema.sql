CREATE TABLE Companies (
  company_id serial PRIMARY KEY,
  isin char(12) unique not null,
  name varchar,
  sector varchar,
  subsector varchar,
  employees int,
  revenue numeric(16,4),
  revenue_year int,
  market_cap numeric(16,4),
  currency varchar,
  country varchar
);

CREATE TABLE Metrics(
  serial_number serial Primary key,
  company_id int REFERENCES Companies(company_id) not null,
  metric_name varchar not null,
  year int,
  value decimal,
  unit varchar,
  source varchar NOT NULL,
  CONSTRAINT chk_source CHECK (source IN ('reported', 'estimated')),
  page_number int,
  quoted_sentence varchar,
  pdf_url varchar,
  confidence_low decimal,
  confidence_high decimal,
  extracted_at timestamp,
  CONSTRAINT duplicate_find UNIQUE (company_id, metric_name, year)
);
