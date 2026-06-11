-- Grain: one row per FIFA fixture (fifa_match_id), mapping it to its seed
-- match_no. Output columns: (fifa_match_id, match_no). This is the FIFA-side
-- analogue of int_match_map: FIFA uses its OWN match ids and its OWN team-name
-- spellings (canonicalized here via fifa_team_name_crosswalk), so it needs a
-- separate reconciliation to the schedule seed.
--
-- Two strategies are unioned, one per match category:
--
-- GROUP matches: join FIFA First-Stage matches to the seed (stage = 'group') on
--   the unordered team SET, i.e. match when {fifa home, fifa away} equals
--   {seed home, seed away} in EITHER orientation, AND both rows share the same
--   group_letter. FIFA's group letter is derived from GroupName ('Group A' ->
--   'A'); the seed's is group_letter. Constraining to the same group_letter
--   prevents a (rare) identical team-set in two groups from cross-mapping.
--   FIFA names are crosswalk-canonicalized (coalesce crosswalk seed_name else
--   the FIFA name) so they line up with the seed's canonical names.
--
-- KNOCKOUT matches: pre-resolution the FIFA knockout objects carry placeholder
--   teams (and FIFA group_name is null), so there is nothing to join on by
--   value. Both the seed and FIFA order knockout matches chronologically within
--   each stage, with exactly one seed row per FIFA fixture per stage, so we
--   match by POSITION: map the FIFA stage to the seed stage, row_number() the
--   FIFA fixtures within the stage by (match_date, fifa_match_id) and the seed
--   rows within the stage by (match_date, kickoff_et, match_no), then join on
--   (stage, row_number). Same positional ASSUMPTION as int_match_map; the
--   fifa_match_map_is_one_to_one singular test guards the 1:1 invariant.

with fifa_matches as (

    select
        match_id as fifa_match_id,
        match_date,
        status,
        stage_name,
        group_name,
        home_team_name,
        away_team_name
    from {{ ref('stg_fifa_matches') }}

),

crosswalk as (

    select
        fifa_name,
        seed_name
    from {{ ref('fifa_team_name_crosswalk') }}

),

-- canonicalize FIFA team names to seed names and derive the FIFA group letter
fifa_canon as (

    select
        f.fifa_match_id,
        f.match_date,
        f.status,
        f.stage_name,
        -- 'Group A' -> 'A'; null for knockout (GroupName null there)
        nullif(trim(replace(f.group_name, 'Group', '')), '') as group_letter,
        coalesce(hx.seed_name, f.home_team_name) as home_team,
        coalesce(ax.seed_name, f.away_team_name) as away_team
    from fifa_matches as f
    left join crosswalk as hx
        on f.home_team_name = hx.fifa_name
    left join crosswalk as ax
        on f.away_team_name = ax.fifa_name

),

seed as (

    select
        match_no,
        match_date,
        kickoff_et,
        stage,
        group_letter,
        home_team,
        away_team
    from {{ ref('stg_schedule') }}

),

-- ---- GROUP: unordered team-set match in either orientation, same group ----
group_map as (

    select
        f.fifa_match_id,
        s.match_no
    from fifa_canon as f
    join seed as s
        on
            s.stage = 'group'
            and f.group_letter = s.group_letter
            and (
                (f.home_team = s.home_team and f.away_team = s.away_team)
                or (f.home_team = s.away_team and f.away_team = s.home_team)
            )
    where f.stage_name = 'First Stage'

),

-- ---- KNOCKOUT: positional match within each stage ----
stage_xwalk as (

    -- map FIFA StageName -> seed stage for the knockout rounds
    select * from (
        values
        ('Round of 32', 'r32'),
        ('Round of 16', 'r16'),
        ('Quarter-final', 'qf'),
        ('Semi-final', 'sf'),
        ('Play-off for third place', 'third'),
        ('Final', 'final')
    ) as x (fifa_stage, seed_stage)

),

fifa_knockout_ranked as (

    select
        f.fifa_match_id,
        x.seed_stage,
        row_number() over (
            partition by x.seed_stage
            order by f.match_date, f.fifa_match_id
        ) as stage_rn
    from fifa_canon as f
    join stage_xwalk as x
        on f.stage_name = x.fifa_stage

),

seed_knockout_ranked as (

    select
        s.match_no,
        s.stage as seed_stage,
        row_number() over (
            partition by s.stage
            order by s.match_date, s.kickoff_et, s.match_no
        ) as stage_rn
    from seed as s
    where s.stage in ('r32', 'r16', 'qf', 'sf', 'third', 'final')

),

knockout_map as (

    select
        f.fifa_match_id,
        s.match_no
    from fifa_knockout_ranked as f
    join seed_knockout_ranked as s
        on
            f.seed_stage = s.seed_stage
            and f.stage_rn = s.stage_rn

)

select
    fifa_match_id,
    match_no
from group_map
union all
select
    fifa_match_id,
    match_no
from knockout_map
