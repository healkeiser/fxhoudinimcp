MCP server for SideFX Houdini with 173 tools across 20 categories.

## PROGRESS FEEDBACK (do this first, always)

Call log\_status at the start of every major step so the user can follow your work in Houdini's status bar in real time. Examples: "Creating base geometry...", "Wiring SOP chain...", "Setting up pyro simulation...", "Assigning materials...". This costs almost nothing and is the user's only live feedback.

## NODE-FIRST RULE (applies to EVERY context — SOP, LOP, DOP, COP, CHOP, TOP)

Before writing ANY code (VEX wrangle, Python SOP, execute\_python), you MUST call `list_node_types(context='<Context>', filter='<keyword>')` to check whether a dedicated node already exists for the operation. Do NOT skip this step even when you think you already know — Houdini ships hundreds of nodes and HDAs per context that may not be in your training data.

## TOOL PRIORITY (highest to lowest, same logic in every context)

1.  Workflow tools — build\_sop\_chain, setup\_pyro\_sim, setup\_rbd\_sim, setup\_flip\_sim, setup\_vellum\_sim, create\_light\_rig, setup\_render, create\_material, assign\_material. These build entire networks in ONE call.
2.  Native nodes via create\_node / create\_lop\_node / create\_cop\_node / create\_chop\_node + connect\_nodes\_batch. Use set\_parameters (batch) to set multiple params in one call.
3.  VEX wrangles via create\_wrangle — ONLY when no built-in node can express the logic. Call list\_node\_types first.
4.  execute\_python — absolute last resort. NEVER use it to create nodes, set parameters, connect nodes, or write Python SOPs.

## COMMONLY MISSED NODE DOMAINS — search these before writing code

The lists below are search hints, not exhaustive. Always call `list_node_types(context, filter)` with the prefix/keyword to discover the full set.

### SOPs (context='Sop')

*   Camera/projection: ray, project, uvproject, texture
*   Volumes/VDB: filter='vdb' — vdbfrompolygons, convertvdb, vdbcombine, vdbsmooth, vdbreshapesdf, vdbmorphsdf, vdbadvectpoints, etc. Also: isooffset, pointsfromvolume, volumewrangle
*   Attributes: filter='attrib' — attribtransfer, attribpromote, attribreorient, attribinterpolate, attribfrommap, attribexpression, attribnoise, attribfromvolume, etc.
*   Deformers: mountain, ripple, twist, bend, lattice, pathdeform, pointdeform, deltamush, shrinkwrap, creep, surfacedeform, inflate, deflate, bulge, wrinkledeformer
*   UVs: filter='uv' — uvautoseam, uvflatten, uvlayout, uvtransform, uvproject, uvunwrap
*   Topology: boolean, booleanfracture, polyextrude, polybridge, polysplit, polyfill, polydoctor, polyreduce, remesh, fuse, join, clean, divide, triangulate2d
*   Groups: filter='group' — groupcreate, groupcombine, grouppromote, groupexpression, grouprange
*   Terrain: filter='heightfield' — heightfield\_noise, heightfield\_erode, heightfield\_scatter, heightfield\_maskby\*, heightfield\_blur, heightfield\_project, heightfield\_tilesplit, heightfield\_terrace, etc.
*   KineFX/rigging: filter='kinefx' — kinefx::rigpose, kinefx::fullbodyik, kinefx::skeletonblend, bonecapturebiharmonic, bonedeform, orientalongcurve
*   APEX rigging: filter='apex' — apex::packcharacter, apex::configurecharacter, apex::graph, apex::buildfkgraph, etc.
*   Curves: resample, sweep, polywire, revolve, fillet, ends, carve, convertline, surfsect
*   Scatter/points: scatter, scatteralign, pointgenerate, pointjitter, relax, pointreplicate, pointvelocity
*   Copy/instance: copytopoints, copytocurves, copyxform, pack, unpack, repack, assemble
*   Fracture: voronoifracture, booleanfracture, rbdmaterialfracture, rbdinteriordetail, rbdconfigure
*   SOP-level solvers: filter='pyro'|'vellum'|'flip'|'mpm'|'whitewater'|'ripple'|'shallowwater' — each has solver+source+postprocess nodes at SOP level
*   Ocean: filter='ocean' — oceanspectrum, oceanevaluate, oceanfoam, oceansource
*   Hair/groom: filter='hair'|'guide' — hairgen, hairclump, haircardgen, guideprocess, guidegroom, guideadvect
*   Feather: filter='feather' — featherprimitive, feathernoise, feathersurface
*   Clouds: cloudnoise, cloudshapegenerate, cloudbillowynoise
*   Distance: findshortestpath, distancealonggeometry, distancefromgeometry
*   Agents/Crowds: filter='agent'|'crowd' — agent, agentclip, agentlayer, agentprep, crowdsource, crowdassignlayers
*   Muscles: filter='muscle'|'tissue' — tissueproperties, muscledeform, muscletensionlines, otissolver
*   ML: filter='ml'|'onnx' — ml\_regressioninference, onnx, neuralpointsurface
*   Packing: pack, unpack, repack, packfolder, packpoints, mergepacked
*   File I/O: file, filecache, filemerge, tableimport, lidarimport, gltf
*   Intersection: intersectionanalysis, intersectionstitch, windingnumber, proximity
*   Utility: connectivity, enumerate, name, matchsize, font, mirror, lsystem, spiral, sort
*   Test geo: filter='testgeometry' — testgeometry\_pighead, testgeometry\_rubbertoy, testgeometry\_shaderball, etc.
*   Labs: filter='labs' — labs::\* (tree generators, flowmap, OSM import, maps baker, LOD, terrain analysis, etc.)

### LOPs (context='Lop')

*   Scene assembly: sublayer, reference (handles payloads), componentoutput, stagemanager, sceneimport
*   SOP bridge: sopimport, sopcreate, sopmodify, sopcrowdimport, kinefx::sopcharacterimport
*   Transforms: xform, edit, matchsize, restructurescenegraph, duplicate
*   Rendering: filter='karma'|'render' — karmarendersettings, renderproduct, rendervar, karmastandardrendervars
*   Karma effects: karmaphysicalsky, karmaskyatmosphere, karmafogbox, karmatexturebaker, karmacryptomatte, backgroundplate
*   Materials: materiallibrary, assignmaterial, editmaterialproperties, materialvariation, materiallinker
*   Lights: light, distantlight, domelight, lightmixer, portallight, geometrylight, lightlinker, lpetag
*   Instancing: instancer, modifypointinstances, splitpointinstancers, extractinstances
*   Layout: layout, drop, edit, editprototypes
*   Config: prune, configurelayer, configureprimitive, drawmode, configurestage
*   USD editing: editproperties, addvariant, setvariant, collection, scope, graftbranches, graftstages, splitscene, copyproperty, modifypaths
*   Constraints: filter='constraint' — blendconstraint, followpathconstraint, lookatconstraint, parentconstraint, surfaceconstraint
*   Animation: bakeskinning, motionblur, resampletransforms, timeshift
*   Geometry prims: mesh, basiscurves, points, volume, capsule, cone, cube, cylinder, sphere

### DOPs (context='Dop')

*   Pyro/smoke: filter='pyro'|'smoke' — pyrosolver, pyrosolver\_sparse, smokesolver, smokeobject
*   FLIP: flipsolver, flipobject, flipconfigureobject
*   RBD: filter='rbd'|'bullet' — rbdobject, rbdpackedobject, rbdsolver, bulletdata, bulletrbdsolver, rbdautofreeze
*   Vellum: filter='vellum' — vellumsolver, vellumobject, vellumsource, vellumconstraints, vellumrestblend
*   Cloth: clothobject, clothsolver, clothconfigureobject
*   Wire: wireobject, wiresolver, wirephysparms
*   FEM: femsolidobject, femsolver, femhybridobject
*   Whitewater: whitewaterobject, whitewatersolver
*   POP forces: filter='pop' — popforce, popdrag, popwind, popattract, popcurveforce, popflock, popgrains, popfloatbyvolumes
*   POP steering: popsteeralign, popsteeravoid, popsteercohesion, popsteerseek, popsteerobstacle, popsteerpath
*   POP utility: popsource, popkill, popreplicate, popspeedlimit, popcolor, popinstance, popgroup, popproperty
*   Crowd: filter='crowd'|'agent' — crowdobject, crowdsolver, crowdstate, crowdtransition, crowdtrigger
*   Forces: gravity, uniformforce, drag, windforce, vortexforce, buoyancyforce, magnetforce, fieldforce
*   RBD constraints: constraintnetwork, conetwistconrel, rbdhingeconstraint, rbdpinconstraint, rbdspringconstraint
*   Collision: staticobject, groundplane, terrainobject
*   Microsolvers: filter='gas' — gasturbulence, gasdisturb, gasshred, gasbuoyancy, gasvortexconfinement, gasadvect, gasresizefield, gasdissipate, gasburn, gasprojectnondivergent, etc.
*   Anchors: filter='anchor' — anchorobjpointidpos, anchorobjpointnumpos, anchorobjspacepos, etc.

### COPs (prefer Copernicus context='Cop'; COP2 context='Cop2' is deprecated since H20.5)

*   Color: colorcorrect, hsv, gamma, bright, contrast, invert, tonemap
*   Keying: chromakey, cryptomatte, dilateerode
*   Filters: blur, sharpen, median, defocus, edgedetect, denoisetvd, denoiseai
*   Compositing: blend, layer, zcomp
*   Transforms: xform, crop, flip, cornerpin, latticedeform, tilepattern, distort
*   Generators: font, ramp, constant, checkerboard
*   Channels: channelextract, channeljoin, channelsplit, channelswap, premult, switch
*   Copernicus noise: fractalnoise, worleynoise, crystalnoise, phasornoise, bubblenoise
*   Copernicus 3D: rasterizegeo, rasterizecurves, rasterizevolume, raytrace, bakegeometrytextures, triplanar
*   Copernicus height/SDF: heighttonormal, heighttoambientocclusion, sdfshape, sdfblend, monotosdf
*   Copernicus pyro: pyro\_configure, pyro\_advect, pyro\_buoyancy, pyro\_turbulence, pyro\_dissipate

### CHOPs (context='Chop')

*   Motion: noise, wave, spring, jiggle, lag, limit, filter, trigger, pulse
*   Math: math, function, logic, count, slope, area, envelope, vector
*   Constraints: filter='constraint' — constraintblend, constraintlookat, constraintobject, constraintpath, constraintparent, etc.
*   KineFX: inversekin, iksolver, extractbonetransforms, extractlocomotion, footplant
*   Timing: shift, stretch, trim, cycle, extend, warp, dynamicwarp, timerange, resample
*   Audio: audioin, oscillator, spectrum, pitch, voicesplit, phoneme
*   Data: channel, constant, file, fetch, stash, record, copy, merge, blend, interp

### TOPs (context='Top')

*   Processors: genericgenerator, pythonprocessor, pythonscript, hdaprocessor
*   ROP rendering: filter='rop' — ropfetch, ropgeometry, ropmantra, ropkarma, ropusd, ropalembic, ropfbx, ropflipbook, ropopengl
*   Partition/wait: filter='partition' — partitionbyframe, partitionbyattribute, partitionbyexpression, partitionbyindex, waitforall
*   File ops: filter='file' — filepattern, filerange, fileremove, filerename, filecopy, filecompress, makedir
*   Data I/O: csvoutput, csvinput, jsoninput, jsonoutput, sqlinput, xmlinput
*   Attributes: filter='attribute' — attributecreate, attributecopy, attributedelete, attributerename, attributerandomize
*   Control: merge, switch, sort, wedge, feedbackbegin, feedbackend, rangegenerate, workitemexpand
*   External: ffmpegencodevideo, ffmpegextractimages, imagemagick, downloadfile, urlrequest
*   USD: usdimport, usdimportfiles, usdrender

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
*   Call layout\_children after every batch of nodes, not just at the end.
*   When a workflow tool exists (setup\_pyro\_sim, setup\_rbd\_sim, etc.), use it instead of building from scratch.