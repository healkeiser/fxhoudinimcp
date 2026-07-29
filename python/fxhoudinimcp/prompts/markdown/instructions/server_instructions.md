MCP server for SideFX Houdini with 179 tools across 22 categories.

## SENIOR ARTIST DISCIPLINE — work like a Houdini veteran, not a script kid

1.  PLAN, THEN BUILD ATOMICALLY. 3+ nodes: design the whole graph and submit it as ONE `build_network` call, never clicked together node-by-node. For node types you have not used this session, `build_network(dry_run=True)` first: it validates every type, parameter name and wire against the running Houdini and returns did-you-mean corrections without touching the scene. This is a throughput decision, not a matter of taste. Every command costs about 50 ms before it does any work, because HOM is main-thread-only and each call is marshalled onto Houdini's main thread to wait for the next event-loop tick. `list_children` on an empty `/obj` costs the same 50 ms as a real query. That floor is per call, not per node, so it is the number of calls you make that decides how long the user waits: ten nodes created one call at a time measured about 800 ms, against about 66 ms for the same ten in a single round trip. Twelve times slower for identical output. The same arithmetic applies to reading (`set_parameters` over repeated `set_parameter`, `connect_nodes_batch` over repeated `connect_nodes`, one `verify_network` over a poll per node).
2.  NEVER GUESS, LOOK IT UP. `get_node_card(node_type, context)` returns real connector labels, real parameter names/defaults/menus and Houdini's own help text for THIS version. `search_help(query)` + `get_help_page(path)` serve EVERY corpus the install ships, which on a full 22.0 is 56 of them and around 11,000 pages. That includes SideFX's own workflow manuals, not just node reference: `pyro/lookdev`, `fluid/tips`, `vellum/vellumtips`, `destruction/constraints`, `mpm/troubleshooting`, `model/attributes`, `copy/instancing`, `assets/versioning_systems`, `solaris/about_lops`, `tops/attributes`, `render/tips`, `crowds/basics`, `character/kinefx/index`, `copernicus/spaces`, `heightfields/layers`. Read the workflow page before designing a setup, and the node page before setting a parameter. Guessed parameter names are the #1 source of silently broken setups.
3.  VERIFY, THEN CLAIM. After any build or change, `verify_network(parent)` (the middle-click-everything pass); read `error_nodes` and the geometry counts. At visual milestones `capture_screenshot` and LOOK at the image. A tool returning success is not evidence.
4.  DRAFT FIRST, THEN UPRES. Coarse divsize, low point counts, few substeps. Present that, and raise quality only once the look is approved. Never make the user wait on a hero cook of an unapproved setup.
5.  CACHE CHECKPOINTS. End every simulation or expensive stage in a `filecache`: caches are the seams between stages of the shot. For RBD and Vellum use `rbdio`/`vellumio` instead, because a sim has several output streams (constraints, proxy and collision geometry, points) and a lone `filecache` on the first output silently drops the rest. Save the hip first, since the default cache path is built from `$HIP`/`$HIPNAME`, and prefer `bgeo.sc`.
6.  EXPOSE THE KNOBS. Tweakables live on a CTRL null with spare parameters, channel-referenced into the network (`ch("../CTRL/...")`). Never hardcoded values, never magic numbers.
7.  KEEP IT LIGHT. copytopoints with Pack and Instance enabled packs the source once and shares it between copies, instead of duplicating it per copy. For copies needing no target points, `duplicate` is the node. At very large counts stop making real geometry: render-time instancing or packed/Alembic primitives. When something is slow, `find_expensive_nodes(root)`, profile rather than guess.

## NODE-FIRST RULE (EVERY context — SOP, LOP, DOP, COP, CHOP, TOP, etc.)

Before writing ANY code (VEX wrangle, Python SOP, execute\_python) you MUST call `list_node_types(context='<Context>', filter='<keyword>')` to check whether a dedicated node already exists. Do NOT skip this even when you think you know: Houdini ships hundreds of nodes and HDAs per context that may not be in your training data. create\_wrangle and execute\_python require a written justification naming the searches you ran; if you cannot write it honestly, you have not checked.

## PROCEDURAL MODELING PATTERNS (how a senior kit-bashes — geometry is NEVER built in VEX)

Producing geometry in a wrangle when native nodes exist is a failure, not a shortcut. The native vocabulary for build-from-reference tasks (a village, a city block, a prop):

*   A building is boxes: box → polyextrude (insets, ledges, storeys) → polybevel (edge wear) → boolean (door/window openings) → clip (roof angles). Windows and doors are small boxes copied onto grid points with copytopoints.
*   A village/forest/crowd of props is INSTANCES: model 2-4 variants, scatter points on the terrain, randomize per-point pscale/orientation with attribrandomize, copytopoints with Pack and Instance.
*   Variants to matching points: copytopoints' own Piece Attribute (`useidattrib` on, `idattrib` naming the attribute), all variants merged into the first input. Houdini copies each source piece to the target points whose value matches, so a merged variant pile plus one integer attribute replaces any switch-and-loop rig. Do NOT build a switch per variant.
*   Continuous per-point variation (pscale, orientation, colour, any float) is attribrandomize's job: uniform, normal and other distributions directly. A small integer index from `rand(@ptnum)` in an attribwrangle is fine, and is what SideFX's own copying guide does.
*   When each copy must differ structurally rather than by attribute, wrap the copy in a for-each loop over the target points. Copy stamping is superseded and must not be used.
*   Curves drive shapes: line / curve → resample → sweep for roads, fences, gutters, beams, not point loops in VEX.
*   Placement on a surface: scatter (density by painted or masked attribute), ray to conform, copytopoints.
*   VEX is acceptable ONLY for attribute math no node expresses, a custom falloff or exotic per-point logic. Never for creating points, primitives or copies.

## TOOL PRIORITY (highest to lowest, same logic in every context)

1.  `build_network` — the whole planned graph in one validated, atomic call. `dry_run=True` proves unfamiliar specs first. For a purely linear SOP chain, `build_sop_chain` wires the whole chain in one call.
2.  Workflow tools — `setup_pyro_sim`, `setup_rbd_sim`, `setup_flip_sim`, `setup_vellum_sim`, `create_light_rig`, `setup_render`, `create_material`, `assign_material` — when one matches the task exactly.
3.  Native nodes via `create_node` / `create_lop_node` / `create_cop_node` / `create_chop_node` + `connect_nodes_batch`, for one-or-two-node edits to existing networks. `set_parameters` (batch) sets multiple params in one call.
4.  VEX wrangles via `create_wrangle` — ONLY when no built-in node can express the logic, and only after `list_node_types`.
5.  `execute_python` — absolute last resort. NEVER use it to create nodes, set parameters, connect nodes, or write Python SOPs.

After EVERY create\_wrangle or set\_wrangle\_code, immediately call validate\_vex and do not proceed until it reports no errors.

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

### Vop (context='Vop', 1020 documented)

*   Name prefixes: filter='kma'|'rsl'|'mtlx'|'volume'|'mtlxco'|'osl'|'mtlxgl'|'pxrdis'|'agentc'|'lens' — e.g. kma_ao (22.0+), rsl_bias, mtlxLamaAdd, volumegradientfile, mtlxcolorcorrect, osl_bias, mtlxglossiness_anisotropy, pxrdisklight, agentclipcatalog, lens_bokeh

### Sop (context='Sop', 878 documented)

*   model: bend, bulge, carve, circle, circlespline, clay, cloud, convert, copytocurves, copytopoints, copyxform, crosssectionsurface, curve, curveanimate (22.0+), curveclay, delete, etc.
*   volumes: attribfromvolume, bakevolume, cloud, cloudlight, cloudnoise, cloudshapegenerate, cloudshapereplicate, convertvdb, convertvolume, hairgrowthfield, paintcolorvolume, paintfogvolume, paintsdfvolume, skybox, skyfield, skyfieldfrommap, etc.
*   attrs: attribcast, attribcomposite, attribcopy, attribcreate, attribcreate::2.0, attribdelete, attribfade, attribfrommap, attribfromparm, attribfromvolume, attribinterpolate, attribmirror, attribpromote, attribrandomize, attribremap, attribreorient, etc.
*   character: attribreorient, attribtransfer, bonecapturebiharmonic, bonecapturelines, bonedeform, bonelink, capture, captureattribpack, captureattribunpack, capturecorrect, capturelayerpaint, capturemirror, captureoverride, capturepaintcore, captureproximity, cregion, etc.
*   polygons: blast, circlespline, dissolve, dissolve::2.0, divide, edgecollapse, edgecusp, edgedivide, edgeflip, extractcontours (21.0+), fractal, hole, intersectionanalysis, intersectionstitch, polybevel, polybridge, etc.
*   reshape: bend, blendshapes, bulge, clay, clothdeform, creep, curveclay, deltamush, edgecollapse, edit, elastictransform, extrude, fractal, lattice, magnet, mountain, etc.
*   merge: attribfromvolume, filemerge, filemerge::2.0, join, merge, mergepacked, object_merge, paintcolorvolume, paintfogvolume, paintsdfvolume, stitch, stroke, vdbrenormalizesdf, vdbreshapesdf, vdbsmooth, vdbsmoothsdf, etc.
*   tech: attribcast, attribpromote, attribsort (21.0+), attribwrangle, block_begin, block_end, bound, cache, carve, channel, connectadjacentpieces, connectivity, convertline, deformationwrangle, delete, each, etc.
*   create: attribcreate::2.0, circle, cloud, curve, curveanimate (22.0+), grid, isooffset, line, lsystem, metaball, platonic, pointcloudiso, sphere, spiral, superquad, testgeometry_capybara, etc.
*   points: attribfrompieces, blast, cluster, clusterpoints, curvesect, ends, facet, fuse, intersectionanalysis, intersectionstitch, maskbyfeature, matchsize, matchtopology, particlefluidtank, pointcloudiso, pointjitter, etc.
*   topology: basis, clean, connectivity, dissolve, dissolve::2.0, divide, edgecollapse, edgedivide, edgeflip, ends, fuse, matchtopology, pointweld, polypath, refine, remesh, etc.
*   curves: basis, chain, circlespline, copytocurves, curve, curveanimate (22.0+), curvesect, intersectionanalysis, intersectionstitch, line, lsystem, orientalongcurve, pathdeform, polyspline, polywire, rails, etc.
*   groups: alembicgroup, circlefromedges, clip, clip::2.0, edgeequalize, edgestraighten, groupbylasso, groupcombine, groupcopy, groupcreate, groupdelete, groupexpand, groupexpression, groupfindpath, groupfromattribboundary, groupinvert, etc.
*   crowds: agent, agentedit, agentlookat, agentprep, agentunpack, agentvellumunpack, crowdassignlayers, crowdmotionpath, crowdmotionpatharcinglayer (21.0+), crowdmotionpathavoid, crowdmotionpathavoidcore, crowdmotionpathedit, crowdmotionpatheditcore, crowdmotionpathevaluate, crowdmotionpathevaluatecore, crowdmotionpathfollow, etc.
*   agents: agent, agentedit, agentlookat, agentprep, agentunpack, agentvellumunpack, crowdassignlayers, crowdmotionpath, crowdmotionpatharcinglayer (21.0+), crowdmotionpathavoid, crowdmotionpathavoidcore, crowdmotionpathedit, crowdmotionpatheditcore, crowdmotionpathevaluate, crowdmotionpathevaluatecore, crowdmotionpathfollow, etc.
*   capture: bonecapturebiharmonic, bonecapturelines, bonedeform, capture, captureattribpack, captureattribunpack, capturecorrect, capturelayerpaint, capturemirror, captureoverride, capturepaintcore, captureproximity, clothcapture, cregion, deltamush, inflate, etc.
*   vellum: agentvellumunpack, femdeform, muscleautotensionlines (21.0+), muscleflex, muscleid, musclemirror, musclepaint, musclepreroll, muscleproperties, musclesolidify, muscletensionlines, muscletensionlinesactivate (21.0+), pointcapture, pointcapturecore, skinproperties, skinsolidify, etc.
*   core: chain, crosssectionsurface, curve, curveanimate (22.0+), deformationwrangle, object_merge, orientalongcurve, polyextrude, rails, reverse, revolve, skin, smooth, smooth::2.0, sphere, sweep, etc.
*   textures: texture, texturefeature, textureopticalflow, topoflow, topoflowbake, topoflowsample, uvautoseam, uvbrush, uvedit, uvflatten, uvfuse, uvlayout, uvpelt, uvproject, uvquickshade, uvtransform, etc.
*   dynamics: bakeode, collisionsource, connectadjacentpieces, debrissource, debrissource::2.0, dopimport, dopimportfield, dopimportrecords, filament_advect_pos, file, filemerge, filemerge::2.0, gluecluster, grainsource, isooffset, vortexforceattribs

### Dop (context='Dop', 405 documented)

*   pop: pointcollider, popadvectbyfilaments, popadvectbyvolumes, popattract, popattribfromvolume, popawaken, popaxisforce, popcollisionbehavior, popcollisiondetect, popcollisionignore, popcolor, popcurveforce, popcurveincompressibleflow, popdrag, popdragspin, popfan, etc.
*   rbd: bulletdata, bulletsoftconrel, rbdangularconstraint, rbdangularspringconstraint, rbdautofreeze, rbdconetwistconstraint, rbdconfigureobject, rbdfracturedobject, rbdguide, rbdhingeconstraint, rbdkeyactive, rbdpackedobject, rbdpinconstraint, rbdpointobject, rbdsliderconstraint, rbdsolver, etc.
*   crowds: agentarcingcliplayer, agentcliplayer, agentlookat, agentlookatapply, agentterrainadaptation, agentterrainprojection, crowdfuzzylogic, crowdobject, crowdsolver, crowdstate, crowdtransition, crowdtrigger, crowdtriggerlogic
*   wire: wireangularconstraint, wireangularspringconstraint, wireconfigureobject, wireelasticity, wireglueconstraint, wireobject, wirephysparms, wireplasticity, wiresolver, wirevisualization, wirevolumecollider, wirewirecollider
*   fem: femattachconstraint, femfuseconstraint, femhybridconfigureobject, femhybridobject, femregionconstraint, femslideconstraint, femsolidconfigureobject, femsolidobject, femsolver, femtargetconstraint, feoutputattributes
*   crowds behavior: popsteeralign, popsteeravoid, popsteercohesion, popsteercustom, popsteerobstacle, popsteerpath, popsteerseek, popsteerseparate, popsteersolver, popsteerturnconstraint, popsteerwander
*   vellum: gasparticlefluiddensitycl, gasparticlefluidforcescl, vellumconstraintproperty, vellumconstraints, vellumobject, vellumrestblend, vellumsolver, vellumsource
*   FLIP: flipconfigureobject, flipobject, flipsolver::2.0, whitewaterobject, whitewatersolver::2.0
*   volumes: gasfieldvop, gasfieldwrangle, geometryvop, geometrywrangle
*   pyro: gasvelocityscale, pyrosolver_sparse, smokeobject_sparse, smokesolver_sparse

### Cop (context='Cop', 359 documented)

*   Name prefixes: filter='pyro'|'height'|'grunge'|'raster'|'testge'|'camera'|'monoto'|'adjace'|'attrib'|'channe' — e.g. pyro_activate (21.0+), heightfield_clip (22.0+), grunge_aurora (22.0+), rasterizecurves (21.0+), testgeometry_capybara (22.0+), camera (22.0+), monotoheightfield (22.0+), adjacency_attribsample (22.0+), attribextract (22.0+), channelextract

### Lop (context='Lop', 176 documented)

*   rendering: additionalrendervars, huskimagemetadata (21.0+), imagefilter (22.0+), karmacryptomatte, karmarendersettings (21.0+), karmastandardrendervars, lpetag, motionblur
*   karma: additionalrendervars, imagefilter (22.0+), karmacryptomatte, karmarendersettings (21.0+), karmastandardrendervars, lpetag, motionblur
*   instancing: assignprototypes, editprototypes, extractinstances, mergepointinstancers, modifypointinstances, retimeinstances
*   constraints: blendconstraint, followpathconstraint, lookatconstraint, parentconstraint, pointsconstraint, surfaceconstraint

### Top (context='Top', 142 documented)

*   pdg: inprocessscheduler, sendcommand, servicecreate, servicedelete, servicereset, servicescheduler (22.0+), servicestart, servicestop, tractorscheduler, usdanalyze, usdmodifypaths, usdzip (22.0+)
*   tops: servicecreate, servicedelete, servicereset, servicestart, servicestop, tractorscheduler, usdanalyze, usdmodifypaths, usdzip (22.0+)
*   usd: usdaddassetstogallery, usdanalyze, usdimport, usdimportfiles, usdrender, usdrenderscene, usdzip (22.0+)
*   services: servicecreate, servicedelete, servicereset, servicescheduler (22.0+), servicestart, servicestop
*   server: houdiniserver, mayaserver, nukeserver, pythonserver, sendcommand
*   attribute: attributeclassify (21.0+), attributecreate, attributefromparameters (21.0+), attributepromote
*   partition: partitionbybounds, partitionbyframe, partitionbyiteration, partitionbyrange

### Chop (context='Chop', 125 documented)

*   Name prefixes: filter='constr'|'transf' — e.g. constraintblend, transform

### Cop2 (context='Cop2', 125 documented)

*   Types: aidenoise, anaglyph, atop, average, blend, blur, border, bright, bump, channelcopy, chromakey, color, colorcorrect, colorcurve, colormap, colorreplace, colorwheel, composite, contrast, convert, convolve, cornerramp, crop, cryptomatte, defocus, deform, degrain, deinterlace, delete, denoise, depthdarken, diff, dilateerode, dropshadow, dsmflatten, edge, edgeblur, equalize, erftable, expand, extend, extract, extrapolateboundaries, fetch, fieldmerge, fieldsplit, fieldswap, file, etc.

### Shop (context='Shop', 117 documented)

*   Name prefixes: filter='gen'|'rsl' — e.g. gen_bsdfshader, rsl_vopdisplace

### Object (context='Obj', 68 documented)

*   character: autobonechaininterface, autorigs, bone, handle, mcacclaim, mocapbiped1, mocapbiped2, mocapbiped3
*   lights: ambient, envlight, hlight, indirectlight, light
*   objects: instance, null, path, pathcv, refimage (21.0+)
*   bones: autobonechaininterface, autorigs, bone, handle
*   util: blend, null, subnet, switcher
*   cameras: stereocam, stereocamrig, switcher, vrcam

### Driver (context='Driver', 33 documented)

*   Types: agent, alembic, bake_animation, baketexture, batch, channel, comp, dembones_skinningconverter, fetch, filmboxfbx, flipbook, framecontainer, framedep, geometry, geometryraw, gltf, haircardtex, hq_render, ifdarchive, image, karma, merge, ml_exampleraw (21.0+), netbarrier, null, prepost, ribarchive, shell, subnet, switch, usdrender, usdzip, wren

### Renamed nodes

The old name still works when creating a node, because Houdini keeps
the alias so old scenes load, but prefer the current name:
*   Lop: instancer (20.5-21.0) is now copytopoints (22.0+)
*   Lop: layout (20.5-21.0) is now paintinstances (22.0+)
*   Sop: mlattribgenerate (20.5-20.5) is now ml_attribgenerate (21.0+)
*   Sop: mlexample (20.5-20.5) is now ml_example (21.0+)
*   Sop: mlexamplecreatecore (20.5-20.5) is now ml_examplecreatecore (21.0+)
*   Sop: mlexampledecompose (20.5-20.5) is now ml_exampledecompose (21.0+)
*   Sop: mlexampledecomposecore (20.5-20.5) is now ml_exampledecomposecore (21.0+)
*   Sop: mlexampleimport (20.5-20.5) is now ml_exampleimport (21.0+)
*   Sop: mlexampleoutput (20.5-20.5) is now ml_exampleoutput (21.0+)
*   Sop: mlexamplepartition (20.5-20.5) is now ml_examplepartition (21.0+)
*   Sop: mlextractexample (20.5-20.5) is now ml_extractexample (21.0+)
*   Sop: mlextractexamplecore is now ml_extractexamplecore (21.0+)
*   Sop: mlposegenerate (20.5-20.5) is now ml_posegenerate (21.0+)
*   Sop: mlposeserialize (20.5-20.5) is now ml_poseserialize (21.0+)
*   Sop: mlregressioninference (20.5-20.5) is now ml_regressioninference (21.0+)
*   Sop: mlregressioninferencecore (20.5-20.5) is now ml_regressioninferencecore (21.0+)
*   Sop: mlregressionproximity (20.5-20.5) is now ml_regressionproximity (21.0+)
*   Sop: mlregressionproximitycore (20.5-20.5) is now ml_regressionproximitycore (21.0+)
*   Top: mlregressiontrain (20.5-20.5) is now ml_trainregression (21.0+)
<!-- END GENERATED: node domains -->

## WORKFLOW GUIDES — ask for one before designing a setup you have not built before

This server ships a written guide per subject, each one distilled from that
subject's SideFX manual and naming the pages to read. If the task matches one,
request it through the MCP prompt rather than reasoning from first principles.

*   `simulation_setup(sim_type)` dispatches per solver: pyro (also smoke, fire, explosion), fluid (flip, liquid, water, whitewater), vellum (cloth, softbody), destruction (rbd, fracture, bullet), mpm (sand, snow). Anything else gets the general dynamics guide.
*   Named prompts: `procedural_modeling_workflow`, `usd_scene_assembly`, `pdg_pipeline`, `hda_development`, `copernicus_workflow`, `heightfield_terrain`, `debug_scene`.
*   `houdini_workflow(topic)` serves any other subject by help-scope name: character, render, shade, crowds, copy, props, dopparticles, io, anim, ocean, grains, muscles, finiteelements, feathers, fur, ml, composite, heightfields_cop.

Two of those guides exist mainly to stop you building on a dead end, so heed them:
character work belongs in KineFX because the object-level bone system is
deprecated, and compositing belongs in Copernicus because COP2 is.

## WEB LOOKUP (the shipped manual is rule 2; this is for when web tools exist)

*   Official docs: https://www.sidefx.com/docs/houdini/nodes/ (sop/, lop/, dop/, cop/, chop/, top/, vop/, obj/, out/, apex/)
*   Tutorials: https://www.sidefx.com/tutorials/ and https://www.sidefx.com/tech-articles/
*   Forum: https://www.sidefx.com/forum/ · cgwiki: https://www.tokeru.com/cgwiki/ · Odforce: https://forums.odforce.net/

`list_node_types` shows what is installed; the docs show how to use it.

{network_housekeeping}
