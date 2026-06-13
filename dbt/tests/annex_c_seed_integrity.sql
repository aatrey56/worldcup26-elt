-- Guards the committed Annexe C third-place seeding reference data (the FIFA
-- 495-combination table, parsed from the regulations PDF). The live projected
-- bracket resolves through the Python resolver + annex_c_map.json, but the seed
-- is the canonical SQL-side copy; this test fails the build if it is ever
-- truncated or corrupted. Returns a row (fails) for any violation:
--   - the long table must have exactly 495 distinct combo_keys, 8 rows each
--     (3960 rows total)
--   - the R32 structure must have exactly 16 matches, 8 of them third-place slots
with combo_counts as (

    select
        combo_key,
        count(*) as n_slots
    from {{ ref('annex_c_third_place_seeding') }}
    group by combo_key

),

annex_violations as (

    select 'wrong combo count' as issue
    from combo_counts
    having count(*) != 495

    union all

    select 'combo with wrong slot count' as issue
    from combo_counts
    where n_slots != 8

),

structure_violations as (

    select 'wrong r32 match count' as issue
    from {{ ref('r32_match_structure') }}
    having count(*) != 16

    union all

    select 'wrong third-slot count' as issue
    from {{ ref('r32_match_structure') }}
    having sum(away_is_third) != 8

)

select issue from annex_violations
union all
select issue from structure_violations
