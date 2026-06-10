-- FIX 2: knockout positional-map misalignment guard.
-- int_match_map maps knockout fixtures to seed match_no by chronological
-- POSITION within each stage. If the API and the seed disagree on chronological
-- order (e.g. a postponement) or a date is null, the positional join can
-- silently misalign. This singular test joins each KNOCKOUT (non-group) row in
-- int_match_map back to the API utcDate (stg_matches) and the seed match_date
-- (stg_schedule) and RETURNS ROWS (fails) when the two dates differ by more
-- than one day. A 1-day gap is tolerated because the seed's local (ET) date can
-- differ from the API's UTC date; a larger gap signals a real reschedule-induced
-- misalignment and fails the build, alerting us.

with knockout_map as (

    select mm.fixture_id, mm.match_no
    from {{ ref('int_match_map') }} mm
    join {{ ref('stg_schedule') }} sch
        on mm.match_no = sch.match_no
    where sch.stage != 'group'

),

api_dates as (

    select fixture_id, kickoff_utc
    from {{ ref('stg_matches') }}

),

seed_dates as (

    select match_no, match_date
    from {{ ref('stg_schedule') }}

)

select
    km.fixture_id,
    km.match_no,
    a.kickoff_utc,
    s.match_date
from knockout_map km
join api_dates a
    on km.fixture_id = a.fixture_id
join seed_dates s
    on km.match_no = s.match_no
-- fail when the dates diverge by more than a day OR when either date is null
-- (a null date means the positional map cannot be date-validated, which is the
-- very misalignment case this test exists to catch).
where a.kickoff_utc is null
   or s.match_date is null
   or abs(date_diff('day', cast(a.kickoff_utc as date), s.match_date)) > 1
