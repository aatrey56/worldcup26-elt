-- Grain: one row per shot (from stg_fifa_shots), scored with xG in PURE SQL.
--
-- xG SCORING: the model coefficients live in the xg_model seed (fitted offline by
-- ml/train_xg.py on FIFA 2022 shots; scikit-learn is dev-only, scoring is SQL).
-- We cross join the single-row pivoted seed and apply the model verbatim:
--   * penalty            -> penalty_xg (empirical conversion rate constant)
--   * open-play w/ coords -> logistic: 1/(1+exp(-(intercept
--                            + distance_coef*shot_distance + angle_coef*shot_angle)))
--   * open-play, null coords -> null xG (no geometry, not scorable)
-- The geometry (shot_distance, shot_angle) is computed identically at ingest and
-- at training (include/extract/load_fifa.enrich_event), so train == serve.
-- Empty-safe: with no shots this is an empty table. NO SELECT * (marts rule).

with shots as (

    select
        match_id,
        player_id,
        team_id,
        minute,
        x,
        y,
        shot_distance,
        shot_angle,
        is_goal,
        is_penalty
    from {{ ref('stg_fifa_shots') }}

),

model as (

    -- Pivot the (param, value) seed to a single row of named coefficients so the
    -- cross join below attaches one set of parameters to every shot.
    select
        max(case when param = 'intercept' then value end) as intercept,
        max(case when param = 'distance_coef' then value end) as distance_coef,
        max(case when param = 'angle_coef' then value end) as angle_coef,
        max(case when param = 'penalty_xg' then value end) as penalty_xg
    from {{ ref('xg_model') }}

)

select
    s.match_id,
    s.player_id,
    s.team_id,
    s.minute,
    s.x,
    s.y,
    s.shot_distance,
    s.shot_angle,
    s.is_goal,
    s.is_penalty,
    case
        when s.is_penalty then m.penalty_xg
        when s.shot_distance is null or s.shot_angle is null then null
        else 1.0 / (
            1.0 + exp(
                -(
                    m.intercept
                    + m.distance_coef * s.shot_distance
                    + m.angle_coef * s.shot_angle
                )
            )
        )
    end as xg
from shots as s
cross join model as m
