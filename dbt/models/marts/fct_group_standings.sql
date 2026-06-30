-- Grain: one row per (group_letter, team). Sourced from the recomputed
-- int_group_table, joined to dim_team for the team surrogate key.
--
-- FIX 4: qualification for the 2026 format. 32 of 48 teams advance:
--   the top 2 of every group (24 teams), PLUS the 8 best third-placed teams
--   across all 12 groups. Per FIFA Art. 13 the 8 best thirds are ranked across
--   groups by points DESC, overall gd DESC, overall gf DESC, then conduct score
--   (cards, not ingested -> skipped), then the FIFA World Ranking
--   (fifa_world_ranking seed, ASC), with team_name as a deterministic final
--   tiebreaker. Head-to-head does NOT apply to the cross-group third-place
--   ranking; the top 8 qualify.
--
-- COMPLETENESS GATING: qualified_flag stays FALSE until the relevant group(s)
-- finish, so it never asserts a qualification the data cannot yet support. A
-- group is "complete" when all 4 of its teams have played 3 group matches.
--   - rank <= 2 qualifies a team only once ITS OWN group is complete.
--   - the rank = 3 best-8 path applies only once ALL 12 groups are complete
--     (the cross-group ranking is meaningless until every third-placed team is
--     final).
-- Before those conditions hold, qualified_flag = false. It therefore resolves
-- to its final value only post-group-stage; mid-tournament it is conservatively
-- false rather than a premature/unstable guess.

with standings as (

    select *
    from {{ ref('int_group_table') }}

),

teams as (

    select
        team_key,
        team_name
    from {{ ref('dim_team') }}

),

-- A group is complete when all 4 teams have each played 3 group matches.
group_completeness as (

    select
        group_letter,
        (count(*) = 4 and min(played) = 3 and max(played) = 3) as group_complete
    from standings
    group by group_letter

),

all_groups_complete as (

    -- true only when all 12 groups are complete (controls the best-third path)
    select bool_and(group_complete) as all_complete
    from group_completeness

),

best_thirds as (

    -- rank the third-placed team of each group across all groups; top 8 qualify.
    -- FIFA Art. 13 order: points, overall gd, overall gf, then conduct (cards,
    -- not ingested) and the seeded FIFA World Ranking; team_name is the
    -- deterministic final tiebreaker. No head-to-head across groups.
    select
        group_letter,
        team_name,
        row_number() over (
            order by points desc, gd desc, gf desc, fifa_rank asc nulls last, team_name asc
        ) as third_rank
    from standings
    where rank = 3

)

select
    s.group_letter,
    t.team_key,
    s.played,
    s.won,
    s.drawn,
    s.lost,
    s.gf,
    s.ga,
    s.gd,
    s.points,
    s.rank,
    (
        (s.rank <= 2 and gc.group_complete)
        or (
            s.rank = 3
            and agc.all_complete
            and bt.third_rank is not null
            and bt.third_rank <= 8
        )
    ) as qualified_flag
from standings as s
left join teams as t
    on s.team_name = t.team_name
left join group_completeness as gc
    on s.group_letter = gc.group_letter
cross join all_groups_complete as agc
left join best_thirds as bt
    on
        s.group_letter = bt.group_letter
        and s.team_name = bt.team_name
