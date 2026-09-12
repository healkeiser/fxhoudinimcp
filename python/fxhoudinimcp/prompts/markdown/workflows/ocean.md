You are building an ocean or water surface in Houdini.

Goal: {description}

`ocean/index` is a hub, and it deliberately points elsewhere, which tells you
something: an ocean is assembled from three different toolsets depending on what
the shot needs.

- **Ocean spectra and surfaces**: `ocean/oceanspectra`, `fluid/oceans`.
- **Whitewater** on top: `fluid/sopwhitewater`, `fluid/whitewater`.
- **Shallow water**, which lives with heightfields: `heightfields/shallowintro`, `heightfields/shallowfields`, `heightfields/shallowoutput`, `heightfields/shallowtrouble`.
- **Ripples** for localised disturbance: `ocean/ripples`, `ocean/ripplesolver`.

Read the relevant page with get_help_page.

## Pick the mechanism from the shot, not from the word "water"

- A **large open surface** with no interaction is spectra-driven displacement, not a simulation. It is cheap and it tiles, and simulating it instead is the expensive mistake.
- **Interaction with an object** (a boat, a splash) means a FLIP region, usually blended into the spectral surface rather than replacing it.
- **Shallow water over terrain** (a flood, a river over a heightfield) is the shallow water solver, which is a heightfield-based solver and not FLIP.
- **A disturbance spreading across a surface** (a raindrop, an impact ring) is the ripple solver.

Most ocean shots are a combination, and the combination is the setup. Decide which
mechanism covers which part of frame before building any of them.

## Blending a FLIP region into the spectral ocean

This is the seam every boat shot has, and hand-lerping heights across a band is
not how SideFX does it. Read `shelf/guidedoceanlayer` and `fluid/sopconfigocean`
first; the mechanism has four parts, each with a node.

- **A guided, thin layer, not a tank.** The Guided Ocean Layer shelf setup simulates a thin particle layer whose collision floor is the ocean surface at a chosen depth, and whose *boundary layer* of particles re-injects ocean velocities and keeps the water level matched to the spectrum. A plain flat tank drifts in level and reflects at its walls, which is what a hand-blended seam is trying to hide.
- **The surface extends itself.** `particlefluidsurface` has a Flatten section: it flattens the meshed surface to the ocean height outside a box and *extrudes* it outward, so the simulated mesh already reaches into the spectral ocean at the right height.
- **The spectrum knows where the sim is.** `particlefluidmask` builds a volume mask from the particles and composites it into `oceanspectrum` through its mask input, so `oceanevaluate` displaces the big surface only where no simulation exists.
- **Same spectrum both sides.** The sim's `oceansource` and the far ocean evaluate the same spectrum node, so waves are continuous across the boundary; a second spectrum with matching numbers is not the same waves.

Pages: `shelf/guidedoceanlayer`, `fluid/sopconfigocean`, `nodes/sop/particlefluidsurface`, `nodes/sop/particlefluidmask`, `nodes/sop/oceansource`.

## Judgement

- Whitewater is a downstream consumer of a water simulation's velocity, so it is a separate stage over a cached sim, never part of the same solve.
- Spectral surfaces are defined by a spectrum, so scale and wind are physical inputs rather than look sliders. `ocean/oceanspectra` before hand-tuning noise.
- Shallow water trouble has its own page (`heightfields/shallowtrouble`); read it before diagnosing.
- Ocean geometry is enormous. Displacement at render time beats real geometry, and the extent should be clipped to what the camera sees.

## Order of work

1. Establish what the camera actually sees, and which mechanism serves which part of it.
2. Build the base surface first, spectral where possible.
3. Add a simulated region only where interaction requires it, and blend it in.
4. `capture_screenshot` against the camera, not a perspective view; oceans read entirely differently from a shot camera.
5. Cache, then add whitewater downstream.

{network_housekeeping}
