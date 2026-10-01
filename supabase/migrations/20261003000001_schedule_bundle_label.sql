-- Module: schedule. Ticket: F44-I06 (feature F44, outcome 5 "the `bundle` offer reads 組合優惠").
--
-- Since F43 a multi-unit price (三盒價) is a `bundle` offer, and it gives no gift, so the seeded
-- label 「組合加贈」 said the wrong thing. Rows that still carry the seeded label follow the new
-- one; a brand that renamed its own row keeps its wording. New brands get the new label from
-- `ensure_coordinates_seeded`.
UPDATE brand_coordinate
   SET label = '組合優惠',
       updated_at = now()
 WHERE dimension = 'offer'
   AND key = 'bundle'
   AND label = '組合加贈';
