-- F31-I05 Contract O: the workbench outputs that went out with an ad. Written at launch approval
-- (every approved launch version rewrites it for the ads in its batch), read by the ads learning
-- readers instead of the set's current selection. Shape:
--   {"change_set_id": text, "set_id": text | null, "outputs": {part: output row | null}}
-- NULL = no approved launch has carried this ad yet.
ALTER TABLE ads_ad ADD COLUMN live_creative_json jsonb;
