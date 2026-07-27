MCP server for SideFX Houdini with 177 tools across 21 categories.

## SENIOR ARTIST DISCIPLINE — work like a Houdini veteran, not a script kid

1.  PLAN THE WHOLE GRAPH, THEN BUILD IT ATOMICALLY. For anything of 3+ nodes, design the complete network and submit it as ONE `build_network` call — never click it together node-by-node. When the spec uses node types you have not used this session, run `build_network(dry_run=True)` first: it validates every type, parameter name, and wire against the running Houdini and returns did-you-mean corrections without touching the scene.
2.  NEVER GUESS — LOOK IT UP. Unsure what a node's parameters or inputs are? `get_node_card(node_type, context)` returns the real connector labels, real parameter names/defaults/menus, and Houdini's own help text for THIS version. For concepts, workflows, VEX functions, and expression functions, `search_help(query)` + `get_help_page(path)` serve Houdini's own shipped manual — read the real reference before improvising code. Guessed parameter names are the #1 source of silently broken setups.
3.  VERIFY, THEN CLAIM. After building or changing a network, call `verify_network(parent)` (the middle-click-everything pass) and read `error_nodes` and the geometry counts. At visual milestones, `capture_screenshot` and LOOK at the image. Never tell the user something works because a tool returned success — tell them because you saw the evidence.
4.  DRAFT FIRST, THEN UPRES. Block out at low cost — coarse divsize, low point counts, few substeps — present it, and only increase quality when the look is approved. Never make the user wait on a hero-resolution cook of an unapproved setup.
5.  CACHE CHECKPOINTS. End every simulation or expensive stage in a `filecache` so downstream work never re-cooks it. Treat caches as the seams between stages of the shot.
6.  EXPOSE THE KNOBS. Tweakables live on a CTRL null with spare parameters, channel-referenced into the network (`ch("../CTRL/...")`) — never buried as hardcoded values.
7.  KEEP IT LIGHT. Instance with copytopoints with Pack and Instance enabled rather than duplicating heavy geometry. When something is slow, `find_expensive_nodes(root)` — profile, don't guess.

## PROGRESS FEEDBACK (do this first, always)

Call log\_status at the start of every major step so the user can follow your work in Houdini's status bar in real time. Examples: "Creating base geometry...", "Wiring SOP chain...", "Setting up pyro simulation...", "Assigning materials...". This costs almost nothing and is the user's only live feedback.

## NODE-FIRST RULE (applies to EVERY context — SOP, LOP, DOP, COP, CHOP, TOP)

Before writing ANY code (VEX wrangle, Python SOP, execute\_python), you MUST call `list_node_types(context='<Context>', filter='<keyword>')` to check whether a dedicated node already exists for the operation. Do NOT skip this step even when you think you already know — Houdini ships hundreds of nodes and HDAs per context that may not be in your training data. create\_wrangle and execute\_python require a written justification naming the searches you ran; if you cannot write it honestly, you have not checked.

## PROCEDURAL MODELING PATTERNS (how a senior kit-bashes — geometry is NEVER built in VEX)

Producing geometry in a wrangle when native nodes exist is a failure, not a shortcut. The native vocabulary for build-from-reference tasks (a village, a city block, a prop):

*   A building is boxes: box → polyextrude (insets, ledges, storeys) → polybevel (edge wear) → boolean (door/window openings) → clip (roof angles). Windows and doors are small boxes copied onto grid points with copytopoints.
*   A village/forest/crowd of props is INSTANCES: model 2-4 variants, scatter points on the terrain, randomize per-point pscale/orientation with attribrandomize, pick variants per point (attribrandomize an index + switch, or copy variant piles and merge), and copytopoints with Pack and Instance enabled. Never duplicate heavy geometry.
*   Variation never means VEX rand(): attribrandomize does uniform/normal/custom distributions on any attribute.
*   Curves drive shapes: line / curve → resample → sweep for roads, fences, gutters, beams — not point loops in VEX.
*   Placement on a surface: scatter (density by painted or masked attribute), ray to conform, copytopoints.
*   VEX is acceptable ONLY for attribute math that no node expresses — a custom falloff, exotic per-point logic — never for creating points, primitives, or copies.

## TOOL PRIORITY (highest to lowest, same logic in every context)

1.  `build_network` — the whole planned graph in one validated, atomic call. Use `dry_run=True` to prove unfamiliar specs first.
2.  Workflow tools — setup\_pyro\_sim, setup\_rbd\_sim, setup\_flip\_sim, setup\_vellum\_sim, create\_light\_rig, setup\_render, create\_material, assign\_material — when one matches the task exactly.
3.  Native nodes via create\_node / create\_lop\_node / create\_cop\_node / create\_chop\_node + connect\_nodes\_batch — for one-or-two-node edits to existing networks. Use set\_parameters (batch) to set multiple params in one call.
4.  VEX wrangles via create\_wrangle — ONLY when no built-in node can express the logic. Call list\_node\_types first.
5.  execute\_python — absolute last resort. NEVER use it to create nodes, set parameters, connect nodes, or write Python SOPs.

## COMMONLY MISSED NODE DOMAINS — search these before writing code

<!-- BEGIN GENERATED: node domains -->
Generated by `tools/gen_node_domains.py` from Houdini's own shipped node
help. Do not hand-edit.

These lists are a floor, not an inventory: SideFX documents fewer nodes
than ship, and a plugin your studio installs is never listed. Call
`list_node_types(context, filter)` to see what is actually loaded, and
`search_help(query)` to find a node by what it does rather than by name.

A name followed by a version range exists only in those Houdini versions,
within the 20.5-22.0 range this server supports: `colorcorrect (21.0+)` is
absent before 21.0, and `instancer (20.5-21.0)` is gone from 22.0 onward.
Unannotated names exist throughout. Check `get_scene_info` for the running
version before relying on an annotated name.

### Vop (context='Vop', 1067 documented)

*   Name prefixes: filter='kma'|'rsl'|'volume'|'mtlx'|'mtlxdi'|'osl'|'mtlxco'|'mtlxgl'|'pxrdis'|'agentc' — e.g. kma_ao (22.0+), rsl_bias, volumegradient, mtlxLamaAdd, mtlxdielectric_bsdf, osl_bias, mtlxcombine2, mtlxglossiness_anisotropy, pxrdisklight, agentclipcatalog

### Sop (context='Sop', 663 documented)

*   model: bend, bridge, bulge, carve, circle, circlespline, clay, cloud, convert, cookie, copy, copytocurves, copytopoints, copyxform, crosssectionsurface, curve, etc.
*   attrs: attribcast, attribcomposite, attribcopy, attribcreate, attribcreate::2.0, attribdelete, attribfade, attribfrommap, attribfromparm, attribfromvolume, attribinterpolate, attribmirror, attribpromote, attribrandomize, attribremap, attribreorient, etc.
*   polygons: blast, circlespline, cookie, dissolve, dissolve::2.0, divide, edgecollapse, edgecusp, edgedivide, edgeflip, extractcontours (21.0+), fractal, hole, intersectionanalysis, intersectionstitch, polybevel, etc.
*   tech: attribcast, attribpromote, attribsort (21.0+), attribwrangle, block_begin, block_end, bound, cache, carve, channel, connectadjacentpieces, connectivity, convertline, deformationwrangle, delete, each, etc.
*   volumes: attribfromvolume, bakevolume, cloud, cloudlight, cloudnoise, convertvdb, convertvolume, hairgrowthfield, paintcolorvolume, paintfogvolume, paintsdfvolume, texturefeature, volumeanalysis, volumearrivaltime, volumeblur, volumebreak, etc.
*   character: attribreorient, attribtransfer, bonecapturebiharmonic, bonecapturelines, bonedeform, bonelink, capture, captureattribpack, captureattribunpack, capturecorrect, capturelayerpaint, capturemeta, capturemirror, captureoverride, capturepaintcore, captureproximity, etc.
*   reshape: bend, blendshapes, bulge, clay, clothdeform, creep, curveclay, deltamush, edgecollapse, edit, elastictransform, extrude, fractal, lattice, magnet, mountain, etc.
*   merge: attribfromvolume, bridge, cookie, filemerge, filemerge::2.0, join, merge, mergepacked, object_merge, paintcolorvolume, paintfogvolume, paintsdfvolume, polyknit, stitch, stroke, vdbrenormalizesdf, etc.
*   create: attribcreate::2.0, circle, cloud, curve, curveanimate (22.0+), grid, isooffset, line, lsystem, metaball, platonic, pointcloudiso, sphere, spiral, superquad, testgeometry_capybara, etc.
*   points: attribfrompieces, blast, cluster, clusterpoints, curvesect, ends, facet, fuse, intersectionanalysis, intersectionstitch, maskbyfeature, matchsize, matchtopology, point, pointcloudiso, pointjitter, etc.
*   topology: basis, clean, connectivity, dissolve, dissolve::2.0, divide, edgecollapse, edgedivide, edgeflip, ends, fuse, matchtopology, pointweld, polypath, refine, remesh, etc.
*   capture: bonecapturebiharmonic, bonecapturelines, bonedeform, capture, captureattribpack, captureattribunpack, capturecorrect, capturelayerpaint, capturemeta, capturemirror, captureoverride, capturepaintcore, captureproximity, clothcapture, cregion, deform, etc.
*   curves: basis, chain, circlespline, copytocurves, curve, curveanimate (22.0+), curvesect, intersectionanalysis, intersectionstitch, line, lsystem, orientalongcurve, pathdeform, polyspline, polywire, rails, etc.
*   groups: alembicgroup, circlefromedges, clip, clip::2.0, edgeequalize, edgestraighten, group, groupcombine, groupcopy, groupcreate, groupdelete, groupexpand, groupexpression, groupfindpath, groupfromattribboundary, groupinvert, etc.
*   crowds: agent, agentedit, agentlookat, agentprep, agentunpack, agentvellumunpack, crowdassignlayers, crowdmotionpath, crowdmotionpatharcinglayer (21.0+), crowdmotionpathavoid, crowdmotionpathavoidcore, crowdmotionpathedit, crowdmotionpatheditcore, crowdmotionpathevaluate, crowdmotionpathevaluatecore, crowdmotionpathfollow, etc.
*   agents: agent, agentedit, agentlookat, agentprep, agentunpack, agentvellumunpack, crowdassignlayers, crowdmotionpath, crowdmotionpatharcinglayer (21.0+), crowdmotionpathavoid, crowdmotionpathavoidcore, crowdmotionpathedit, crowdmotionpatheditcore, crowdmotionpathevaluate, crowdmotionpathevaluatecore, crowdmotionpathfollow, etc.
*   core: chain, crosssectionsurface, curve, curveanimate (22.0+), deformationwrangle, object_merge, orientalongcurve, point, pointwrangle, polyextrude, rails, reverse, revolve, skin, smooth, smooth::2.0, etc.
*   dynamics: bakeode, collisionsource, connectadjacentpieces, debrissource, debrissource::2.0, dopimport, dopimportfield, dopimportrecords, dopio, filament_advect_pos, file, filemerge, filemerge::2.0, finalizewaves, gluecluster, grainsource, etc.
*   vellum: agentvellumunpack, femdeform, muscleflex, muscleid, musclemirror, musclepaint, musclepreroll, muscleproperties, musclesolidify, muscletensionlines, pointcapture, pointcapturecore, skinproperties, skinsolidify, tissueproperties, tissuesolidify, etc.
*   cleanup: basis, clean, polycap, polypath, polyreduce, polystitch, resample, reverse, smooth, smooth::2.0, solidify, tetrahedralize, triangulate2d, tridivide, uvlayout, uvpelt, etc.

### Dop (context='Dop', 417 documented)

*   pop: pointcollider, popadvectbyfilaments, popadvectbyvolumes, popattract, popattribfromvolume, popawaken, popaxisforce, popcollisionbehavior, popcollisiondetect, popcollisionignore, popcolor, popcurveforce, popdrag, popdragspin, popfan, popfireworks, etc.
*   rbd: bulletdata, bulletsoftconrel, rbdangularconstraint, rbdangularspringconstraint, rbdautofreeze, rbdconetwistconstraint, rbdconfigureobject, rbdfracturedobject, rbdglueobject, rbdguide, rbdhingeconstraint, rbdkeyactive, rbdobject, rbdpackedobject, rbdpinconstraint, rbdpointobject, etc.
*   crowds: agentarcingcliplayer, agentcliplayer, agentlookat, agentlookatapply, agentterrainadaptation, agentterrainprojection, crowdfuzzylogic, crowdobject, crowdsolver, crowdstate, crowdtransition, crowdtrigger, crowdtriggerlogic
*   wire: wireangularconstraint, wireangularspringconstraint, wireconfigureobject, wireelasticity, wireglueconstraint, wireobject, wirephysparms, wireplasticity, wiresolver, wirevisualization, wirevolumecollider, wirewirecollider
*   fem: femattachconstraint, femfuseconstraint, femhybridconfigureobject, femhybridobject, femregionconstraint, femslideconstraint, femsolidconfigureobject, femsolidobject, femsolver, femtargetconstraint, feoutputattributes
*   crowds behavior: popsteeralign, popsteeravoid, popsteercohesion, popsteercustom, popsteerobstacle, popsteerpath, popsteerseek, popsteerseparate, popsteersolver, popsteerturnconstraint, popsteerwander
*   pyro: gasvelocityscale, pyrosolver::2.0, pyrosolver_sparse, smokeconfigureobject, smokeobject, smokeobject_sparse, smokesolver::2.0, smokesolver_sparse
*   FLIP: flipconfigureobject, flipobject, flipsolver::2.0, whitewateremitter, whitewaterobject, whitewatersolver::2.0
*   volumes: gasfieldvop, gasfieldwrangle, geometryvop, geometrywrangle

### Shop (context='Shop', 151 documented)

*   Name prefixes: filter='gen'|'rsl' — e.g. gen_bsdfshader, rsl_vopdisplace

### Lop (context='Lop', 148 documented)

*   rendering: additionalrendervars, huskimagemetadata (21.0+), imagefilter (22.0+), karmacryptomatte, karmarenderproperties, karmarendersettings (21.0+), karmastandardrendervars, lpetag, motionblur
*   karma: additionalrendervars, imagefilter (22.0+), karmacryptomatte, karmarenderproperties, karmarendersettings (21.0+), karmastandardrendervars, lpetag, motionblur
*   instancing: assignprototypes, editprototypes, extractinstances, mergepointinstancers, modifypointinstances, retimeinstances
*   constraints: blendconstraint, followpathconstraint, lookatconstraint, parentconstraint, pointsconstraint, surfaceconstraint

### Cop2 (context='Cop2', 128 documented)

*   Types: aidenoise, anaglyph, atop, average, blend, blur, border, bright, bump, channelcopy, chromakey, color, colorcorrect, colorcurve, colormap, colorreplace, colorwheel, composite, contrast, convert, convolve, cornerramp, crop, cryptomatte, defocus, deform, degrain, deinterlace, delete, denoise, depthdarken, diff, dilateerode, dropshadow, dsmflatten, edge, edgeblur, emboss, equalize, erftable, expand, extend, extract, extrapolateboundaries, fetch, fieldmerge, fieldsplit, fieldswap, etc.

### Chop (context='Chop', 125 documented)

*   Name prefixes: filter='constr'|'transf' — e.g. constraintblend, transform

### Object (context='Obj', 69 documented)

*   character: autobonechaininterface, autorigs, bone, handle, mcacclaim, mocapbiped1, mocapbiped2, mocapbiped3
*   objects: cop2plane, instance, null, path, pathcv, refimage (21.0+)
*   lights: ambient, envlight, hlight, indirectlight, light
*   bones: autobonechaininterface, autorigs, bone, handle
*   util: blend, null, subnet, switcher
*   cameras: stereocam, stereocamrig, switcher, vrcam

### Top (context='Top', 46 documented)

*   pdg: inprocessscheduler, sendcommand, servicecreate, servicedelete, servicereset, servicescheduler (22.0+), servicestart, servicestop, tractorscheduler, usdanalyze, usdmodifypaths
*   tops: servicecreate, servicedelete, servicereset, servicestart, servicestop, tractorscheduler, usdanalyze, usdmodifypaths
*   services: servicecreate, servicedelete, servicereset, servicescheduler (22.0+), servicestart, servicestop
*   usd: usdaddassetstogallery, usdanalyze, usdimport, usdimportfiles, usdrender, usdrenderscene
*   server: houdiniserver, mayaserver, nukeserver, pythonserver, sendcommand
*   attribute: attributeclassify (21.0+), attributecreate, attributefromparameters (21.0+), attributepromote
*   partition: partitionbybounds, partitionbyframe, partitionbyiteration, partitionbyrange

### Driver (context='Driver', 34 documented)

*   Types: agent, alembic, bake_animation, baketexture, batch, channel, comp, dembones_skinningconverter, fetch, filmboxfbx, flipbook, framecontainer, framedep, geo2i3d, geometry, gltf, haircardtex, hq_render, ifdarchive, image3d, karma, merge, netbarrier, null, opengl, prepost, ribarchive, shell, subnet, switch, usdrender, usdzip, wedge, wren
<!-- END GENERATED: node domains -->

## DOCUMENTATION LOOKUP (when internet/web tools are available)

If you have access to web browsing or URL-fetching tools, consult these trusted Houdini sources before writing VEX or Python workarounds:

*   Official docs: https://www.sidefx.com/docs/houdini/nodes/ (sop/, lop/, dop/, cop/, chop/, top/, vop/, obj/, out/)
*   Tutorials: https://www.sidefx.com/tutorials/ and https://www.sidefx.com/tech-articles/
*   Forum: https://www.sidefx.com/forum/
*   cgwiki: https://www.tokeru.com/cgwiki/
*   Odforce: https://forums.odforce.net/

When to look: (1) unsure if a node exists, (2) need parameter details, (3) need a workflow pattern. This complements list\_node\_types — the live query shows what's installed, the docs show how to use it.

## General rules

*   After EVERY create\_wrangle or set\_wrangle\_code, immediately call validate\_vex. Do not proceed until it reports no errors.
*   build\_sop\_chain wires a whole chain at once. Prefer it over individual create\_node calls for linear SOP chains.
*   NEVER hardcode tweakable values. Create a controller null ('CTRL') with spare parameters.
*   {layout_guidance}
*   When a workflow tool exists (setup\_pyro\_sim, setup\_rbd\_sim, etc.), use it instead of building from scratch.
