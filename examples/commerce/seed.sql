CREATE TABLE customers (customer_id TEXT PRIMARY KEY, name TEXT, grade TEXT);
CREATE TABLE categories (category_id TEXT PRIMARY KEY, name TEXT, parent_id TEXT, returnable INTEGER);
CREATE TABLE products (product_id TEXT PRIMARY KEY, name TEXT, category_id TEXT, brand TEXT);
CREATE TABLE skus (sku_id TEXT PRIMARY KEY, product_id TEXT, size TEXT, color TEXT, price REAL, stock INTEGER,
                   material TEXT, season TEXT);
CREATE TABLE orders (order_id TEXT PRIMARY KEY, customer_id TEXT, ordered_at TEXT, status TEXT);
CREATE TABLE order_items (item_id TEXT PRIMARY KEY, order_id TEXT, sku_id TEXT, quantity INTEGER,
                          unit_price REAL, delivered_at TEXT, item_status TEXT,
                          gift_wrap INTEGER DEFAULT 0);
CREATE TABLE claims (claim_id TEXT PRIMARY KEY, item_id TEXT, kind TEXT, reason TEXT, claimed_at TEXT,
                     claim_status TEXT);
CREATE TABLE wishlists (customer_id TEXT, product_id TEXT);

INSERT INTO customers VALUES ('C001', '김하늘', 'VIP'), ('C002', '이도윤', 'BASIC'), ('C003', '박서연', 'SILVER');
INSERT INTO categories VALUES ('K1', '의류', NULL, 1), ('K2', '상의', 'K1', 1), ('K3', '니트', 'K2', 1),
                              ('K4', '속옷', 'K1', 0);
INSERT INTO products VALUES ('P1', '울 니트 스웨터', 'K3', '하늘섬유'), ('P2', '면 티셔츠', 'K2', '하늘섬유'),
                            ('P3', '기본 속옷 세트', 'K4', '바람직물');
INSERT INTO skus VALUES ('S1', 'P1', 'M', '네이비', 59000, 3, '울', 'FW'), ('S2', 'P1', 'L', '네이비', 59000, 12, '울', 'FW'),
                        ('S3', 'P2', 'M', '화이트', 19000, 2, '면', 'ALL'), ('S4', 'P3', 'L', '블랙', 15000, 40, '면', 'ALL');
INSERT INTO orders VALUES ('O1', 'C001', '2026-10-20T10:00:00', 'DELIVERED'),
                          ('O2', 'C001', '2026-10-27T09:30:00', 'SHIPPED'),
                          ('O3', 'C002', '2026-10-15T14:00:00', 'DELIVERED'),
                          ('O4', 'C002', '2026-10-28T11:00:00', 'CANCELLED');
INSERT INTO order_items (item_id, order_id, sku_id, quantity, unit_price, delivered_at, item_status) VALUES
  ('I1001', 'O1', 'S1', 1, 59000, '2026-10-25T15:00:00', 'NORMAL'),
  ('I1002', 'O1', 'S3', 2, 19000, '2026-10-25T15:00:00', 'RETURN_REQUESTED'),
  ('I1003', 'O3', 'S2', 1, 59000, '2026-10-18T10:00:00', 'NORMAL'),
  ('I1004', 'O3', 'S4', 1, 15000, '2026-10-18T10:00:00', 'NORMAL'),
  ('I1005', 'O2', 'S2', 1, 59000, NULL, 'NORMAL'),
  ('I1006', 'O4', 'S3', 1, 19000, NULL, 'NORMAL');
UPDATE order_items SET gift_wrap = 1 WHERE item_id = 'I1001';
INSERT INTO claims VALUES ('CL1', 'I1002', 'RETURN', '사이즈가 맞지 않음', '2026-10-26T09:00:00', 'OPEN');
INSERT INTO wishlists VALUES ('C001', 'P2'), ('C001', 'P3'), ('C002', 'P1');
