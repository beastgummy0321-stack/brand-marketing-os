-- Module: brand_intelligence
-- Drop brand.industry column (ticket 03). Only reader was the holiday-relevance calendar
-- matcher (ADR 0036), which was deleted in ticket 02; set_brand_industry() function removed here.

ALTER TABLE brand DROP COLUMN industry;
