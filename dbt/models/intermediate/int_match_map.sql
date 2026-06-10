-- Grain: one row per API fixture (fixture_id), mapping it to its seed match_no.
-- Output columns: (fixture_id, match_no). This is the single reconciliation
-- point between the live football-data.org feed and the authoritative schedule
-- seed, and it replaces the old fragile (home_team, away_team) name-pair join.
--
-- Two strategies are unioned, one per match category:
--
-- GROUP matches: join the API (stage = 'GROUP_STAGE') to the seed
--   (stage = 'group') on the unordered team SET, i.e. match when
--   {api home, api away} equals {seed home, seed away} in EITHER orientation.
--   Matching on the set (not the ordered pair) also fixes the old
--   orientation-sensitivity bug. Names are already crosswalk-canonicalized by
--   stg_matches, so they line up with the seed's canonical names.
--
-- KNOCKOUT matches: pre-resolution, the API knockout objects have NULL team
--   names and no venue, so there is nothing to join on by value. BUT both the
--   seed and the API order knockout matches chronologically within each stage,
--   and there is exactly one seed row per API fixture per stage. We therefore
--   match by POSITION: map the API stage to the seed stage, row_number() the
--   API fixtures within the stage by (utcDate, fixture_id) and row_number() the
--   seed rows within the stage by (match_date, kickoff_et, match_no), then join
--   on (stage, row_number).
--   ASSUMPTION (positional match): the chronological order of knockout fixtures
--   in the API equals the chronological order of the seed rows within each
--   stage. This holds because the official schedule fixes both. If the
--   provider reorders fixtures within a stage, this mapping would drift; the
--   match_map_is_one_to_one singular test guards the 1:1 invariant.

with api_matches as (

    select
        fixture_id,
        kickoff_utc,
        stage,
        home_team,
        away_team
    from {{ ref('stg_matches') }}

),

seed as (

    select
        match_no,
        match_date,
        kickoff_et,
        stage,
        home_team,
        away_team
    from {{ ref('stg_schedule') }}

),

-- ---- GROUP: unordered team-set match in either orientation ----
group_map as (

    select
        a.fixture_id,
        s.match_no
    from api_matches a
    join seed s
        on s.stage = 'group'
       and (
            (a.home_team = s.home_team and a.away_team = s.away_team)
            or (a.home_team = s.away_team and a.away_team = s.home_team)
       )
    where a.stage = 'GROUP_STAGE'

),

-- ---- KNOCKOUT: positional match within each stage ----
stage_xwalk as (

    -- map API stage -> seed stage for the knockout rounds
    select * from (
        values
            ('LAST_32',        'r32'),
            ('LAST_16',        'r16'),
            ('QUARTER_FINALS', 'qf'),
            ('SEMI_FINALS',    'sf'),
            ('THIRD_PLACE',    'third'),
            ('FINAL',          'final')
    ) as x(api_stage, seed_stage)

),

api_knockout_ranked as (

    select
        a.fixture_id,
        x.seed_stage,
        row_number() over (
            partition by x.seed_stage
            order by a.kickoff_utc, a.fixture_id
        ) as stage_rn
    from api_matches a
    join stage_xwalk x
        on a.stage = x.api_stage

),

seed_knockout_ranked as (

    select
        s.match_no,
        s.stage as seed_stage,
        row_number() over (
            partition by s.stage
            order by s.match_date, s.kickoff_et, s.match_no
        ) as stage_rn
    from seed s
    where s.stage in ('r32', 'r16', 'qf', 'sf', 'third', 'final')

),

knockout_map as (

    select
        a.fixture_id,
        s.match_no
    from api_knockout_ranked a
    join seed_knockout_ranked s
        on a.seed_stage = s.seed_stage
       and a.stage_rn = s.stage_rn

)

select fixture_id, match_no from group_map
union all
select fixture_id, match_no from knockout_map
