CREATE TABLE borrowers (borrower_id TEXT PRIMARY KEY, name TEXT, credit_grade TEXT);
CREATE TABLE accounts (account_id TEXT PRIMARY KEY, borrower_id TEXT, balance REAL, opened_at TEXT);
CREATE TABLE loans (loan_id TEXT PRIMARY KEY, borrower_id TEXT, account_id TEXT, principal REAL, rate REAL,
                    loan_status TEXT, opened_at TEXT);

INSERT INTO borrowers VALUES ('B01', '정하린', 'A'), ('B02', '최민준', 'C'), ('B03', '한유나', 'B');
INSERT INTO accounts VALUES ('A01', 'B01', 1200000, '2025-03-02T09:00:00'), ('A02', 'B02', 80000, '2024-11-20T09:00:00'),
                            ('A03', 'B03', 540000, '2026-01-15T09:00:00');
INSERT INTO loans VALUES
  ('L1', 'B01', 'A01', 30000000, 4.2, 'ACTIVE', '2025-03-02T10:00:00'),
  ('L2', 'B02', 'A02', 12000000, 7.9, 'OVERDUE', '2024-11-20T10:00:00'),
  ('L3', 'B03', 'A03', 5000000, 5.1, 'CLOSED', '2026-01-15T10:00:00'),
  ('L4', 'B02', 'A02', 3000000, 8.4, 'ACTIVE', '2026-10-05T10:00:00');
