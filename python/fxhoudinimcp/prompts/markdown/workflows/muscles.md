You are setting up muscles and tissue in Houdini.

Goal: {description}

`muscles/overview` describes the current system, `muscles/musclesetup`,
`muscles/tissues`, `muscles/fasciatissuesetup`, `muscles/geopreparation`,
`muscles/propertyassignments`, `muscles/skinpostprocessing`,
`muscles/otissimulation`, `muscles/forces`, `muscles/muscletransfer`,
`muscles/frankenmuscle` and `muscles/troubleshooting` cover the stages.
`muscles/differences`, `muscles/overviewvellum` and `muscles/workflowvellum`
describe the older Vellum path. Read with get_help_page.

## Two systems, and which one you want

**Otis Muscle and Tissue** is the current framework, built on the Otis solver
(Vertex Block Descent architecture). The distinction that matters:

- The previous **Vellum** muscle system was **multi-pass**: muscle, then tissue, then skin, simulated in stages.
- **Otis is single-pass**: every layer simulates at the same time, which is what gives it more robust collisions and better anatomical accuracy.

So do not port a Vellum-era multi-pass mental model onto Otis. If a plan has you
simulating muscle, caching, then simulating tissue on top, that is the old system's
shape. `muscles/differences` is the page that spells out the change.

## The five stages

Otis work is staged, and `muscles/overview` names them starting with geometry
preparation: muscles, rest and animated bones, and the renderable skin. Everything
downstream assumes that preparation is correct, which is why
`muscles/geopreparation` is worth reading before building anything.

## Judgement

- Anatomical accuracy comes from the input geometry and property assignment, not from solver settings. Tuning the solver to fix bad muscle geometry does not work.
- Rest bones and animated bones are separate inputs and confusing them produces motion that looks like a solver failure.
- `muscles/troubleshooting` is a real page; read it before inventing a diagnosis.
- Muscle sims are expensive. Cache, and do skin post-processing downstream of the cache.

## Order of work

1. Prepare geometry: muscles, rest bones, animated bones, renderable skin. Verify each with get_geometry_info.
2. Muscle setup, then tissue, then fascia where the anatomy needs it.
3. Property assignments, which is where material behaviour actually lives.
4. Short-range Otis simulation, `capture_screenshot`, and check against anatomy rather than against expectation.
5. Cache.
6. Skin post-processing downstream.

{network_housekeeping}
