There's an open Houdini session. Using the attached reference image, build a procedural Hong Kong building facade as a SOP network inside a single Geometry object at /obj. Requirements:

All variation should be driven by a small set of top-level parameters (floors, windows per floor, floor height, window width/height, window inset depth, balcony toggle, AC unit toggle, etc.) so the whole facade updates live when any value changes. Place them in a tab if it's a geometry node.
Build modularly: separate reusable pieces for the window frame, window inset, AC unit, balcony rail, so they can be instanced/copied across the grid
Use Copy to Points or equivalent instancing workflows rather than hand-placing geometry
Avoid Python SOPs — use built-in nodes and VEX wrangles where logic is needed
Keep the network clean: use Null nodes as labeled outputs for each module, and lay out the graph top-to-bottom
Focus on geometry only, no materials or lighting
Start by describing your plan (modules, parameter list, wiring strategy) before touching any nodes.
Show more


I'll analyze the reference image and plan the procedural facade before building anything.

Analysis of Reference Image
The image shows a typical Hong Kong residential building facade with:

6-7 visible floors of densely packed apartments
Windows with metal frames/grilles in a grid pattern, many with different curtain states
AC units mounted externally on brackets below or beside windows
Laundry lines with clothes hanging from some units
Balcony-like overhangs / covered sections on some floors
Rust staining running down the concrete facade
Ground floor has shop signage (Chinese characters, "BERTH")
Color: mostly off-white/pinkish concrete with weathering
Plan
Top-Level Parameters (on the Geometry node, in a "Facade" tab)
Parameter	Type	Default	Description
floors	int	6	Number of floors
windows_per_floor	int	8	Windows per floor
floor_height	float	3.0	Vertical spacing
window_width	float	1.2	Window opening width
window_height	float	1.5	Window opening height
window_inset	float	0.15	Depth of window recess
wall_thickness	float	0.3	Facade wall thickness
balcony_chance	float	0.3	Per-window chance of balcony rail
ac_chance	float	0.4	Per-window chance of AC unit
horizontal_divider_height	float	0.12	Height of floor divider bands
seed	int	42	Random seed for variation
Modules (each ending in a labeled Null output)
WALL_BASE — A single large box for the facade wall, with boolean-subtracted window openings (or built as a grid of wall segments)
WINDOW_FRAME — A rectangular frame (thin box outline) representing the metal window grille
WINDOW_INSET — A recessed box behind the window opening (gives depth/shadow)
AC_UNIT — A small box with bracket, mounted below/beside window
BALCONY_RAIL — A thin horizontal rail/shelf extending from select windows
FLOOR_DIVIDER — Horizontal concrete bands between floors
GRID_POINTS — Point grid for window positions, with randomized attributes (has_ac, has_balcony) driven by seed
Wiring Strategy
Create grid points (wrangle) → one point per window position
Add random attributes per point (has_ac, has_balcony, curtain_state)
Copy WINDOW_FRAME + WINDOW_INSET to all grid points
Copy AC_UNIT to points where has_ac==1 (filtered)
Copy BALCONY_RAIL to points where has_balcony==1 (filtered)
Build WALL_BASE as a single slab, then boolean-subtract window openings (or build procedurally with a wrangle)
Add FLOOR_DIVIDERS as horizontal bands
Merge everything into final output
All spatial values reference the top-level parameters via ch("../../parameter_name") expressions so the facade updates live.

Let me start building this now.


Updated todo list with geometry node and grid tasks
Updated todo list with geometry node and grid tasks

First, let me check the current scene state and create the geometry node.


Created geometry node "hk_facade" in Houdini scene
Created geometry node "hk_facade" in Houdini scene
Show more
Show more

Now let me delete the default file1 node inside and create all the spare parameters in a "Facade" tab.


Checked hk_facade object for child elements, found none
Checked hk_facade object for child elements, found none
Show more

Good, it's empty. Now create all the spare parameters in a "Facade" tab.


Updated todo list tracking geometry node and GRID_POINTS module progress
Updated todo list tracking geometry node and GRID_POINTS module progress
Show more

Now let me build the GRID_POINTS module — a wrangle that generates a point grid for all window positions, with random attributes.


Created grid points generator wrangle node for window facade layout
Created grid points generator wrangle node for window facade layout
Show more

I need to fix the VEX floor() ambiguity. Let me fix the cast.


Updated Houdini wrangle node with grid points generator VEX code
Updated Houdini wrangle node with grid points generator VEX code
Show more

Now add the output null for grid points.


Connected grid_points_wrangle to OUT_GRID_POINTS node
Connected grid_points_wrangle to OUT_GRID_POINTS node
Show more
Show more

Let me verify the grid is working.


Checked geometry info for Houdini grid points node
Checked geometry info for Houdini grid points node
Show more
Show more

0 points — the detail wrangle generated nothing because it needs an input point to run on. I need to feed it a single point first, or use a different approach. Let me add an add SOP (single point) as input to the wrangle so it has geometry context to execute on.


Created seed_point node in hk_facade object
Created seed_point node in hk_facade object
Show more

I need to check the Add SOP's parameters to ensure it creates a single point.


Retrieved geometry information for seed_point node
Retrieved geometry information for seed_point node
Show more

The Add SOP defaults to no points. Let me check its parameters to enable a point.


Retrieved parameter schema for seed_point node
Retrieved parameter schema for seed_point node
Show more

I see — the Add SOP uses numbered parameters like usept0, pt0, etc. But a simpler approach: let me just enable point 0. The usept# uses Base1, so the first one should be usept0.

Actually, looking more carefully, Base1 naming scheme means the first parameter would be usept1. Let me check:


Attempted to retrieve parameter, parameter not found
Attempted to retrieve parameter, parameter not found

I see there are points and prims folders. Let me try setting it via python to add a point to the Add SOP. Actually, the cleanest approach is to just use a different method. Let me delete the add SOP and instead modify the wrangle to not need an input — the issue is that a Detail wrangle with no input runs but produces no geometry context. Let me try connecting a simple approach: I'll use Python to set the points multiparm.


Set seed point multiparm folder to 1 point
Set seed point multiparm folder to 1 point
Show more

Now let me connect the seed point to the wrangle and verify it works.


Connected seed_point node to grid_points_wrangle node
Connected seed_point node to grid_points_wrangle node
Show more

Now the wrangle needs to remove that initial seed point. Let me update the wrangle to remove point 0 at the end (the seed point that was fed in). Actually, I should add a removepoint call, but more cleanly — let me just add a Delete SOP after to remove point 0, or better yet, modify the wrangle to remove the input point.


Inspected Houdini geometry node OUT_GRID_POINTS attributes
Inspected Houdini geometry node OUT_GRID_POINTS attributes
Show more
Show more

Still 0 points. The seed_point Add SOP might still not have a point. Let me verify.


Retrieved geometry information for seed point node
Retrieved geometry information for seed point node
Show more

Good, seed_point has 1 point. The issue is the wrangle runs over Detail but only once — and when it removes point 0, the newly added points might get renumbered. Let me check - maybe the problem is that the wrangle runs over "Detail" but the internal VOP wrangle is set differently. Let me check the actual class parameter.


Retrieved parameter "class" from grid_points_wrangle node
Retrieved parameter "class" from grid_points_wrangle node
Show more

It's set to detail correctly. Let me check if it has errors.


Scanned grid_points_wrangle node for errors, found none
Scanned grid_points_wrangle node for errors, found none
Show more

No errors, but 0 points output. The issue might be that the removepoint call on the seed point is interfering with addpoint in the same detail wrangle execution. In VEX, when running over Detail, removepoint and addpoint in the same execution can cause issues with point numbering. Let me try a different approach — skip the removepoint and instead use a Delete SOP after the wrangle to clean up point 0.


Retrieved geometry information for grid_points_wrangle node
Retrieved geometry information for grid_points_wrangle node
Show more
Show more

Still only 1 point — the addpoint calls aren't working either. The issue is likely that the wrangle is wrapped in an internal AttribVOP, and the addpoint function requires a specific attribute wrangle context. Let me check how the create_wrangle tool actually builds the node.


Retrieved node information for grid_points_wrangle Attribute Wrangle
Retrieved node information for grid_points_wrangle Attribute Wrangle
Show more

I see the issue. The class parameter value is 0 but the ch() references use ../../floors which goes up two levels from the wrangle node. The wrangle is at /obj/hk_facade/grid_points_wrangle — so ../../ goes to /obj. But the spare parameters are on /obj/hk_facade. The relative path should be ../ not ../../.

Wait — actually, the Attribute Wrangle wraps the VEX in an internal VOP network (attribvop1 inside the wrangle). So from the VEX execution context, the path ../../ goes from attribvop1 -> grid_points_wrangle -> hk_facade. That should be correct. But let me verify by checking what the ch() calls actually resolve to. Let me check the vex_cwdpath — it's set to . which means the wrangle node itself. So ch("../../floors") from the wrangle = going up to /obj which doesn't have floors.

The correct relative path from the wrangle node is ../floors (one level up to /obj/hk_facade).


Updated grid points wrangle node with VEX code for window generation
Updated grid points wrangle node with VEX code for window generation
Show more

Hmm wait — the vex_cwdpath is . which is the wrangle itself. But the VEX code inside actually runs from an internal attribvop1 child node. Let me check: in Houdini's attribute wrangle, the ch() references in VEX are relative to the wrangle node itself (because of vex_cwdpath = "."). So ../floors from the wrangle at /obj/hk_facade/grid_points_wrangle goes to /obj/hk_facade/floors — which is correct since the spare params are on /obj/hk_facade.

Let me verify the parameter values are accessible:


Evaluated Houdini expression for floor parameter value
Evaluated Houdini expression for floor parameter value
Show more

Good — the parameter exists and returns 6. Now let me check the geometry output again:


Retrieved geometry information from grid_points_wrangle node
Retrieved geometry information from grid_points_wrangle node
Show more

49 points — that's 48 grid points (6 floors × 8 windows) + 1 seed point. Now I need to add a Delete SOP to remove the seed point (where delete_me==1).


Connected grid processing nodes in Houdini workflow
Connected grid processing nodes in Houdini workflow
Show more
Show more
Show more

Now set the blast SOP to delete points where @delete_me==1.


Retrieved geometry information from Houdini grid points node
Retrieved geometry information from Houdini grid points node
Show more
Show more

48 points — exactly 6 floors × 8 windows. Grid points module is complete. Now I need to also create filtered point sets for AC and balcony copies. Let me add those as blast/group filter nodes from the grid points.


Updated todo list with completed geometry and grid tasks
Updated todo list with completed geometry and grid tasks

Now let me build the individual geometry modules. I'll create all the template geometry pieces in parallel — window inset, window frame, AC unit, and balcony rail. Each one is a small piece of geometry centered at origin that will be copied to the grid points.

WINDOW_INSET — a recessed rectangular opening (a box slightly smaller than the window, pushed back into the wall).


Set window_inset_box node type parameter to 1
Set window_inset_box node type parameter to 1
Show more
Show more

Now I need to set expressions for the window inset box size. The box should be window_width × window_height × window_inset and offset back in Z.


Linked window inset box parameters to parent controls via expressions
Linked window inset box parameters to parent controls via expressions
Show more
Show more
Show more

Wait — the expression paths need to be from the box node. The box is at /obj/hk_facade/window_inset_box, so ../../ goes to /obj, not /obj/hk_facade. I need ../ to reach the geo node's spare parameters.


Linked window inset box parameters to parent control attributes
Linked window inset box parameters to parent control attributes
Show more
Show more
Show more

Good. Now let me add the output null for the window inset and create the window frame module. I'll build these in parallel.


Created output node for window inset geometry
Created output node for window inset geometry
Show more
Show more

Window inset box looks correct — 1.2 × 1.5 × 0.15 pushed back in -Z. Now connect it to the output null.


Completed geometry node with spare parameters and GRID_POINTS module
Completed geometry node with spare parameters and GRID_POINTS module
Show more

Now let me build the WINDOW_FRAME — a rectangular frame (outer box minus inner box) representing the metal window grille. I'll use two boxes and a boolean subtract to create the frame profile, or more efficiently, build it as a wrangle that creates a rectangular frame outline with thickness.

I'll use a simpler approach: create an outer box and an inner box (slightly smaller), then Boolean subtract the inner from the outer to get the frame.


Created two box nodes for facade frame geometry in Houdini
Created two box nodes for facade frame geometry in Houdini
Show more
Show more

Set both to polygon type and configure expressions. The frame is the full window size with a thin depth, and the inner cutout is slightly smaller (by frame thickness of ~0.05m on each side).


Set frame type parameter to 1 on two nodes
Set frame type parameter to 1 on two nodes
Show more
Show more

Now set expressions for both boxes. Frame outer = window size, thin depth. Frame inner = slightly smaller.


Linked facade frame dimensions to window parameters in Houdini
Linked facade frame dimensions to window parameters in Houdini
Show more
Show more
Show more

Now create the Boolean SOP to subtract the inner from the outer, plus add a center divider bar and horizontal bar for the grille look. Actually, let me keep it simpler — just the frame with a center vertical bar. I'll use Boolean for the frame, then add a cross-bar with a separate box merged in.


Connected frame geometry nodes to boolean operation node
Connected frame geometry nodes to boolean operation node
Show more
Show more

Let me check the Boolean SOP parameters to set it to Subtract mode.


Set boolean operation to difference on frame node
Set boolean operation to difference on frame node
Show more
Show more

Let me check the result and also check what value 2 maps to:


Retrieved boolean operation parameter and geometry data from Houdini node
Retrieved boolean operation parameter and geometry data from Houdini node
Show more
Show more

Good — frame boolean gives us a rectangular frame. Now add the vertical center bar and a horizontal cross-bar for the grille. I'll create two thin boxes and merge them with the frame.


Created two box nodes for facade frame structure
Created two box nodes for facade frame structure
Show more
Show more

Set the bar dimensions — vertical bar is thin × window height, horizontal bar is window width × thin.


Configured frame geometry dimensions with parametric expressions for window frame bars
Configured frame geometry dimensions with parametric expressions for window frame bars
Show more
Show more
Show more

Now merge the frame + bars together, then add the output null.


Connected three facade frame nodes to merge geometry
Connected three facade frame nodes to merge geometry
Show more
Show more

Now create the output null for the window frame and connect it.


Retrieved geometry information for window frame node
Retrieved geometry information for window frame node
Show more
Show more
Show more

Window frame complete. Now let me build the AC_UNIT and BALCONY_RAIL modules.


Created geometry node with spare parameters and built GRID_POINTS module
Created geometry node with spare parameters and built GRID_POINTS module

AC_UNIT — a box (the AC unit body) with a small bracket shelf underneath. Positioned below the window.


Created two box nodes for AC unit components in Houdini scene
Created two box nodes for AC unit components in Houdini scene
Show more
Show more

AC body: roughly 0.7 × 0.3 × 0.25m, positioned below the window center. Bracket: thin shelf underneath.


Adjusted AC unit body and bracket dimensions in Houdini scene
Adjusted AC unit body and bracket dimensions in Houdini scene
Show more
Show more

Now merge AC body + bracket, add output null.


Connected AC unit components in Houdini node graph
Connected AC unit components in Houdini node graph
Show more
Show more
Show more

Good. Now let me build the BALCONY_RAIL — a small shelf/ledge extending outward from below the window, with a simple railing.


Created two box nodes for balcony geometry in Houdini scene
Created two box nodes for balcony geometry in Houdini scene
Show more
Show more

Balcony floor: a thin slab extending out from the wall, below the window. Rail bar: a thin horizontal bar at the front edge of the balcony.


Configured balcony floor geometry with expressions and parameters
Configured balcony floor geometry with expressions and parameters
Show more
Show more
Show more

Now the rail bar at the front edge of the balcony:


Configured balcony rail bar with parametric dimensions and positioning
Configured balcony rail bar with parametric dimensions and positioning
Show more
Show more
Show more

Now merge balcony pieces and create output null. I'll also add a couple of vertical rail posts.


Configured left and right balcony posts with parametric positioning expressions
Configured left and right balcony posts with parametric positioning expressions
Show more
Show more
Show more

Now merge all balcony parts and create the output null.


Connected multiple balcony geometry nodes to merge node
Connected multiple balcony geometry nodes to merge node
Show more
Show more
Show more

All template modules are done. Now let me build the WALL_BASE and FLOOR_DIVIDERS, then move on to instancing.


Completed geometry node and GRID_POINTS module tasks
Completed geometry node and GRID_POINTS module tasks

WALL_BASE — The main concrete wall slab. I'll create it as a single large box sized to cover the full facade, then use a Boolean subtract with copies of a window-sized cutter to punch out all the window openings. The cutter will be copied to all grid points, then subtracted from the wall.

First, the wall slab:


Created box node "wall_slab" in hk_facade
Created box node "wall_slab" in hk_facade
Show more

The wall needs to span the full facade width and height. Width = (windows_per_floor - 1) * h_spacing + window_width + 0.6 (the last gap). Height = floors * floor_height. I'll use expressions.


Set parametric expressions for wall_slab geometry dimensions
Set parametric expressions for wall_slab geometry dimensions
Show more
Show more
Show more

Now create a window cutter box (slightly larger than window, full wall thickness depth) to be copied to each grid point, then boolean-subtracted from the wall.


Configured window_cutter node with parametric sizing expressions
Configured window_cutter node with parametric sizing expressions
Show more
Show more
Show more

Now copy the cutter to all grid points, then boolean subtract from wall. I need a Copy to Points SOP.


Connected window_cutter and OUT_GRID_POINTS nodes to copy_cutters
Connected window_cutter and OUT_GRID_POINTS nodes to copy_cutters
Show more
Show more

Now boolean subtract the cutters from the wall slab.


Set boolean operation to subtract and connected nodes for wall geometry
Set boolean operation to subtract and connected nodes for wall geometry
Show more
Show more
Show more

Let me verify the wall boolean is working.


Analyzed geometry information for wall_boolean node
Analyzed geometry information for wall_boolean node
Show more

Wall with window openings is working. Now add its output null.


Connected wall_boolean node to OUT_WALL output
Connected wall_boolean node to OUT_WALL output
Show more
Show more

Now FLOOR_DIVIDERS — horizontal concrete bands between each floor. I'll create a single divider box and copy it to floor boundary points.


Updated todo list with completed geometry and grid tasks
Updated todo list with completed geometry and grid tasks

I'll create the floor dividers with a wrangle that generates horizontal bands at each floor boundary.


Configured divider_box node with parametric sizing and positioning expressions
Configured divider_box node with parametric sizing and positioning expressions
Show more
Show more
Show more

Now create floor-boundary points (one point per floor boundary at Y = 0, floor_height, 2*floor_height, etc.).


Created Wrangle node generating floor boundary points for dividers
Created Wrangle node generating floor boundary points for dividers
Show more

Connect the seed point as input to this wrangle, add a blast to remove the seed, then copy dividers to those points.


Connected seed_point node to divider_points_wrangle node
Connected seed_point node to divider_points_wrangle node
Show more

Now add a blast to remove the seed point, then copy divider boxes to the floor boundary points.


Configured remove_seed_dividers node and connected divider_points_wrangle output
Configured remove_seed_dividers node and connected divider_points_wrangle output
Show more
Show more
Show more

Now create Copy to Points to instance divider boxes onto the floor boundary points.


Connected copy_dividers node to OUT_DIVIDERS output
Connected copy_dividers node to OUT_DIVIDERS output
Show more
Show more
Show more

Let me verify the dividers:


Retrieved geometry info for OUT_DIVIDERS node
Retrieved geometry info for OUT_DIVIDERS node
Show more

7 dividers (floors 0-6 boundaries) × 6 polys each = 42 polygons. Now on to the instancing stage — copy each module to the grid points, with filtering for AC and balcony.


Created geometry node with spare parameters and built GRID_POINTS module
Created geometry node with spare parameters and built GRID_POINTS module

I need to create:

Copy window inset to ALL grid points
Copy window frame to ALL grid points
Copy AC unit to grid points where has_ac==1
Copy balcony to grid points where has_balcony==1
For the filtered copies, I'll use Blast nodes to keep only the relevant points before feeding into Copy to Points.


Created six Houdini nodes for facade detail distribution system
Created six Houdini nodes for facade detail distribution system
Show more
Show more
Show more

Now configure the filter blasts. For AC: keep only points where has_ac==1 (blast removes has_ac==0). For balcony: keep only has_balcony==1.


Configured filter nodes for AC and balcony points
Configured filter nodes for AC and balcony points
Show more
Show more

Now wire everything up — connect the filters to grid points, then connect each copy node.


Connected multiple node outputs in Houdini facade network
Connected multiple node outputs in Houdini facade network
Show more

Let me verify the copy nodes are producing geometry.


Analyzed geometry info for four Houdini facade nodes
Analyzed geometry info for four Houdini facade nodes
Show more
Show more
Show more

All copy operations are producing geometry. Now for the final step — merge everything together and create the final output.


Connected multiple nodes to FINAL_MERGE in Houdini
Connected multiple nodes to FINAL_MERGE in Houdini
Show more
Show more

Now create the final output null and set display/render flags on it.


Connected FINAL_MERGE to OUT_FACADE node, enabled display and render flags
Connected FINAL_MERGE to OUT_FACADE node, enabled display and render flags
Show more
Show more
Show more

Let me verify the final geometry and then layout the network.


Retrieved geometry information from Houdini facade node
Retrieved geometry information from Houdini facade node
Show more

~8K polys — good facade. Now let me layout the network cleanly and color the output nulls.


Laid out 41 child nodes in hk_facade object
Laid out 41 child nodes in hk_facade object
Show more

Now let me color the output null nodes for easy identification — black for output nulls is the standard convention.


Colored eight Houdini nodes in hk_facade network dark gray and green
Colored eight Houdini nodes in hk_facade network dark gray and green
Show more
Show more
Show more

Now let me frame the viewport and take a screenshot to verify the result.


Framed all objects in viewport display
Framed all objects in viewport display
Show more

Let me take a viewport screenshot and a network screenshot to verify everything looks correct.


Attempted viewport render and network capture; viewport succeeded, network capture failed
Attempted viewport render and network capture; viewport succeeded, network capture failed
Show more
Show more
Show more

The viewport render succeeded (large image output). Let me view it.


Read frontend facade image file
Read frontend facade image file

The facade is looking great. I can see:

6 floors of windows in a grid pattern
Window frames with cross-bars visible on every window
AC units mounted below certain windows (random distribution)
Balcony rails/shelves extending from some windows
Floor divider bands between each level
Wall with window openings properly cut out
Let me also check a perspective view to verify the 3D depth.


Viewed facade perspective image file
Viewed facade perspective image file
Show more
Show more
Show more

The perspective view confirms the 3D depth — you can see the wall thickness, window insets recessed into the wall, AC units and balconies protruding outward, and the floor dividers all working together.


Updated todo list tracking geometry node and grid module progress
Updated todo list tracking geometry node and grid module progress

The procedural Hong Kong building facade is complete. Here's a summary of what was built:

Facade at /obj/hk_facade
Top-Level Parameters (Facade tab)
Parameter	Default	Purpose
Floors	6	Number of floor levels
Windows Per Floor	8	Windows across each floor
Floor Height	3.0	Vertical spacing between floors
Window Width	1.2	Width of window openings
Window Height	1.5	Height of window openings
Window Inset Depth	0.15	How deep windows recess into wall
Wall Thickness	0.3	Concrete wall depth
Floor Divider Height	0.12	Height of horizontal bands
Balcony Chance	0.25	Probability of balcony per window
AC Unit Chance	0.4	Probability of AC unit per window
Random Seed	42	Controls variation distribution
Network Modules (41 nodes)
Grid Points: Detail wrangle generating a point per window with random has_ac, has_balcony, curtain_state attributes
Window Inset: Recessed box for shadow/depth at each opening
Window Frame: Boolean-subtracted frame + vertical/horizontal cross-bars
AC Unit: Body box + bracket shelf, copied to has_ac==1 points
Balcony Rail: Floor slab + rail bar + side posts, copied to has_balcony==1 points
Wall Base: Full-facade slab with boolean-cut window openings
Floor Dividers: Horizontal bands at each floor boundary
All outputs labeled with OUT_* null nodes (dark colored), final output is green OUT_FACADE
All geometry is driven by expressions referencing the top-level parameters, so the entire facade updates live when any value changes.

Great. Can you now add pipes, cables, detaiils to make it lively? I'd also like random colors that make sense in a facade setting.



Let me plan the additions before building. I'll add:

Vertical drainpipes running down the facade at intervals
Horizontal cables/wires strung between windows (laundry lines)
Window sills — small ledges below each window
Roof overhang/cornice at the top
Random facade colors — wall tint variation per floor, window frame tints, etc.
Let me start building these.


Updated todo list with facade and window improvement tasks
Updated todo list with facade and window improvement tasks

First, let me check the current scene state to plan pipe placement.


Retrieved facade node parameters: floors (10) and windows_per_floor (14)
Retrieved facade node parameters: floors (10) and windows_per_floor (14)
Show more
Show more

I see you've already been tweaking parameters — 10 floors and 14 windows per floor now. Good — everything should be procedural. Let me build the new detail modules.

1. Vertical Drainpipes
I'll create a pipe template (thin tube) and place pipes at every ~3-4 window intervals along the facade, running full height.


Configured pipe_tube node with geometry parameters and parametric expressions
Configured pipe_tube node with geometry parameters and parametric expressions
Show more
Show more
Show more

Now I need points to place the pipes at — every ~3-4 windows along the facade horizontally, at the wall surface. I'll create a wrangle that generates pipe placement points.


Created Wrangle node for procedural drainpipe point generation
Created Wrangle node for procedural drainpipe point generation
Show more

Now connect the seed point, add blast, copy pipes to those points, and create output null.


Retrieved geometry information for pipe network structure
Retrieved geometry information for pipe network structure
Show more
Show more
Show more

Pipes are working — 5 pipes across the facade. Now let me build the remaining detail modules. I'll work through them efficiently.

2. Horizontal Cables/Laundry Lines
These are thin lines strung between windows on random floors — very characteristic of HK buildings.


Created Wrangle node generating laundry line segments between windows
Created Wrangle node generating laundry line segments between windows
Show more

Now I need to give the polylines some thickness with a Wire (or PolyWire) SOP so they render as thin cables. Let me create the chain: seed_point → wrangle → blast seed → polywire → null.


Configured Houdini facade nodes: set group parameters, adjusted wire radius, connected node pipeline, colored output node
Configured Houdini facade nodes: set group parameters, adjusted wire radius, connected node pipeline, colored output node
Show more
Show more
Show more

Good, the polywire sides param doesn't exist — segs is the right one. Let me check and verify the cables output.


Retrieved geometry info for OUT_CABLES node
Retrieved geometry info for OUT_CABLES node
Show more

Cables are working. Now let me build window sills and roof cornice quickly.

3. Window Sills — small ledge below each window

Configured sill_box geometry with parametric expressions and dimensions for window frame integration
Configured sill_box geometry with parametric expressions and dimensions for window frame integration
Show more
Show more
Show more

Copy sills to all grid points.


Connected sill nodes in Houdini network and styled output node
Connected sill nodes in Houdini network and styled output node
Show more
Show more
Show more

4. Roof Cornice — a wider horizontal band at the top of the building

Connected cornice_box node to OUT_CORNICE output, set dark color
Connected cornice_box node to OUT_CORNICE output, set dark color
Show more
Show more
Show more

Good. Now I need to update the FINAL_MERGE to include all the new modules, then build the color system. Let me first disconnect the old final merge and rebuild it with all modules.


Failed to disconnect node due to index error
Failed to disconnect node due to index error

Let me try a different approach — just add the new inputs to the existing merge.


Retrieved Houdini merge node information and parameters
Retrieved Houdini merge node information and parameters
Show more

I see the merge lost some connections during the layout. It only has 3 inputs now. Let me reconnect everything properly — all copy outputs + new modules.


Connected multiple nodes to FINAL_MERGE in Houdini facade
Connected multiple nodes to FINAL_MERGE in Houdini facade
Show more

Now for the most impactful part — random facade colors. I'll add a wrangle after the final merge that assigns Cd (color) based on what part of the facade each primitive belongs to. The strategy: assign color per-element using groups or position-based logic. Since everything is merged, I'll use bounding box / position heuristics and a facade_part string attribute that I'll stamp on each branch before merging.

Actually, the cleaner approach is to add a color wrangle to each branch before merging. Let me add Cd attributes on each module's output with appropriate colors.


Updated todo list with completed facade improvement tasks
Updated todo list with completed facade improvement tasks

I'll insert color wrangles between each copy/output and the FINAL_MERGE. The approach:

Wall: off-white/pinkish concrete with weathering variation per-face
Window insets: darker recessed shadow tone
Window frames: dark grey/green metallic
AC units: off-white/beige plastic
Balconies: concrete grey with slight rust
Dividers: slightly darker concrete band
Pipes: dark grey/rusty brown
Cables: dark wire color
Sills: concrete matching wall but slightly lighter
Cornice: concrete matching wall
Let me create one big color wrangle that goes after the FINAL_MERGE and uses position + primitive connectivity to determine colors. This is simpler than inserting 10 separate wrangles. I'll insert it between FINAL_MERGE and OUT_FACADE, and use a part_id integer attribute that I'll stamp on each branch.

First, let me add a simple integer attribute to each branch to identify it. I'll use small wrangles on each source.


Disconnected input from OUT_FACADE node in Houdini
Disconnected input from OUT_FACADE node in Houdini
Show more

I'll create a single color wrangle that goes after FINAL_MERGE — it will use the part_id to assign colors. But first I need to tag each branch. Let me use a more efficient approach: create a wrangle for each source that stamps a part_id, then one final color wrangle.

Actually, the most efficient approach: use a single Attribute Create SOP on each branch to set an integer. But with 10 branches, that's a lot of nodes. Instead, let me just do a single wrangle after FINAL_MERGE that assigns color based on bounding position. The geometry types are distinguishable by their Z position and size.

Let me take a simpler approach — stamp a part_id using Python on the merge inputs, then use a single color wrangle.

The cleanest approach: I'll insert wrangles between each copy node and the FINAL_MERGE that set i@part_id. Let me do this with a batch of simple wrangles.


Configured Houdini merge node with multiple input sources
Configured Houdini merge node with multiple input sources
Show more

Now create the color assignment wrangle after the merge.


Created Houdini wrangle node for realistic Hong Kong facade coloring
Created Houdini wrangle node for realistic Hong Kong facade coloring
Show more

Now wire: FINAL_MERGE → color_facade_wrangle → OUT_FACADE.


Connected facade nodes in Houdini node graph pipeline
Connected facade nodes in Houdini node graph pipeline
Show more

Let me verify the final output and check for errors.


Validated VEX code and inspected facade geometry output
Validated VEX code and inspected facade geometry output
Show more
Show more

~26K polys with Cd and part_id attributes. Let me layout the network, take a final screenshot to verify the colors.


Viewed facade colored front image file
Viewed facade colored front image file
Show more
Show more
Show more

The colors are working but they look a bit uniform and muted. The Cd is on primitives but the viewport might not be showing per-prim color well in smooth shading. Let me also check a perspective view.


Read facade image with colored perspective from file system
Read facade image with colored perspective from file system
Show more
Show more
Show more

The colors are there but subtle in the viewport's default lighting. The differentiation between wall, frames, AC units, and windows is visible. Let me boost the color contrast a bit — the wall should be lighter and have more pink/beige tint, and the frames should be more distinctly teal/green like the reference. Let me also add more variation — some windows could have different colored curtains visible in the inset.


Implemented facade color assignment in Houdini wrangle node
Implemented facade color assignment in Houdini wrangle node
Show more

Now let me take a final front view to see the improved colors with curtain variations.


Viewed facade front design image file
Viewed facade front design image file
Show more
Show more
Show more

That looks much more alive now. You can see:

Random curtain colors — dark interiors, warm amber lights, blue curtains, tan/brown curtains, and white curtains varying per window
Teal-green window frames matching the HK aesthetic
Off-white/pink concrete wall with subtle variation
Dark vertical drainpipes running between window columns
Window sills below each window
AC units and balconies scattered randomly
Floor divider bands between levels
Grime darkening toward the bottom floors

Updated todo list with completed drainpipe and cable tasks
Updated todo list with completed drainpipe and cable tasks

All done. Here's a summary of what was added:

New Detail Modules
Module	Description
Drainpipes	Vertical tubes placed every ~3 window columns, full building height, slightly in front of wall
Laundry Lines	Polyline cables with polywire thickness, strung between adjacent windows with sag, ~20% chance
Window Sills	Small concrete ledges below each window opening
Roof Cornice	Wider horizontal band at the very top of the building
Color System (Cd attribute, per-primitive)
Each module branch gets a part_id integer attribute before the final merge, then a single color wrangle assigns:

Wall: Warm off-white/pink concrete with per-face variation, rust streaks, and bottom-floor grime
Window insets: Randomized per-window — dark interiors (30%), amber lit rooms (20%), white curtains (20%), blue curtains (15%), brown curtains (15%)
Frames: Teal-green anodized metal, with occasional older brownish frames
AC units: Off-white plastic with yellowing age variation, some much dirtier
Balconies: Concrete grey with rust tint on outer rails
Pipes: Dark grey PVC with random rust patches
Cables: Near-black wire color
Sills/Cornice/Dividers: Concrete tones matching the wall
The seed parameter still controls all randomness, so changing it reshuffles curtains, AC placement, balconies, and weathering patterns.

Curtains currently look like a Mondrian painting, like each curtain is made of several ones.
The cables are floating in the air, not attached to anything.
I want the whole thing to feel organic, like in the reference.



Good observations. Let me analyze the issues:

Curtain Mondrian effect: The color wrangle uses @P per-primitive, so different faces of the same window inset box get different curtain colors. I need to use a stable per-window ID based on the grid position, not per-face position.

Floating cables: The laundry lines are at Z=0.3, far from the wall. They should originate from the window frame area and have some physical anchor logic.

Organic feel: Need more irregularity — slight random offsets to window positions, varied AC placement (not always centered), some visual clutter.

Let me fix these systematically.


Updated todo list with curtain color and cable anchoring fixes
Updated todo list with curtain color and cable anchoring fixes

Fix 1: Curtain Colors
The problem is that each face of the window inset box has a slightly different @P, so int(rint(@P.x * 2.0)) * 100 + int(rint(@P.y)) gives different IDs per face. I need to quantize more aggressively to the window grid spacing. Let me check the actual grid spacing values.


Retrieved window_width and floor_height parameters from hk_facade node
Retrieved window_width and floor_height parameters from hk_facade node
Show more
Show more

The h_spacing is window_width + 0.6 = 1.77, floor_height is 2.56. I need to snap each prim's centroid to the nearest grid position to get a stable window ID. The fix: round @P.x / h_spacing and @P.y / floor_height to the nearest integer.


Updated Houdini wrangle node with HK facade color assignment logic
Updated Houdini wrangle node with HK facade color assignment logic
Show more

Good. Now Fix 2: Cables — they need to originate from within the window frame area, like laundry poles sticking out. I'll rewrite the laundry lines wrangle so the lines start and end at the window frame edges (at Z ~ 0.02, just at the frame surface) and only sag slightly outward. I'll also add a short "pole" segment from the wall outward at each end.


Updated laundry lines Wrangle node VEX code successfully
Updated laundry lines Wrangle node VEX code successfully
Show more

Good. Now Fix 3: Organic variation. I'll add slight random offsets to the window grid positions so nothing is perfectly aligned. I'll also add random scale variation to AC units, and slight Y-offset randomness.


Fixed curtain color and cable anchoring issues
Fixed curtain color and cable anchoring issues

I'll update the grid points wrangle to add slight random position offsets and a pscale attribute for AC unit size variation. I'll also add an ac_offset_x attribute so AC units aren't always centered.


Updated grid points wrangle node with organic offset generation
Updated grid points wrangle node with organic offset generation
Show more

Now I need to apply the AC offset and scale. I'll add a wrangle between the filter_ac_points and copy_ac_units that adjusts point positions based on ac_offset_x and sets pscale from ac_scale.


Created Wrangle node for AC unit positioning and scaling
Created Wrangle node for AC unit positioning and scaling
Show more

I need to wire the ac_adjust_wrangle into the AC copy chain and then verify everything with a viewport screenshot. Let me continue.


Retrieved information on three Houdini nodes in ac unit pipeline
Retrieved information on three Houdini nodes in ac unit pipeline
Show more
Show more
Show more

Good, I can see the current wiring: filter_ac_points outputs directly to copy_ac_units input 1. I need to insert ac_adjust_wrangle in between. Let me disconnect and rewire.


Disconnected input 1 from copy_ac_units node
Disconnected input 1 from copy_ac_units node
Show more

Now wire: filter_ac_points → ac_adjust_wrangle → copy_ac_units (input 1).


Connected AC unit nodes in Houdini workflow pipeline
Connected AC unit nodes in Houdini workflow pipeline
Show more

AC adjust wrangle is now wired in. Now let me also add some variation to the balconies — slightly randomize their horizontal offset too. And let me add a few more organic touches: vary the pipe positions slightly and add subtle randomness to the window sills. Let me first check the current balcony chain.


Retrieved node information for filter_balcony_points and copy_balconies nodes
Retrieved node information for filter_balcony_points and copy_balconies nodes
Show more
Show more

Good. Now let me also add some variation to the drainpipes. Let me check the pipe wrangle to see what it currently does.


Retrieved drainpipe wrangle code and tube node parameters
Retrieved drainpipe wrangle code and tube node parameters
Show more
Show more

Good — the pipes already have slight random offsets. The tube height is hardcoded to 25.6 though. Let me make it expression-driven and also add some pipe radius variation. Let me also check the current state of the color wrangle to make sure it's up to date, and then do a layout and take a viewport screenshot.


Set parametric expressions for pipe tube height and position
Set parametric expressions for pipe tube height and position
Show more
Show more

Good. Now let me also add some visual clutter — small rectangular boxes randomly placed on some windows to represent signage, window-mounted fans, or other small objects you see on HK facades. I'll add a small rooftop clutter element too (water tanks / antenna-like boxes).


Adjusted clutter box dimensions and vertical position parameters
Adjusted clutter box dimensions and vertical position parameters
Show more
Show more

Now create a wrangle that filters grid points to ~15% of windows for clutter placement, and slightly randomizes position.


Created VEX wrangle node to filter and randomize window clutter geometry
Created VEX wrangle node to filter and randomize window clutter geometry
Show more

Now create a Copy to Points for clutter, and a tag wrangle for it. Then wire it into FINAL_MERGE.


Connected multiple nodes in Houdini facade geometry network
Connected multiple nodes in Houdini facade geometry network
Show more
Show more

Now create a tag wrangle for clutter (part_id = 10) and wire it into FINAL_MERGE.


Connected copy_clutter node to tag_part_10 node
Connected copy_clutter node to tag_part_10 node
Show more
Show more

Now I need to add this as a new input to FINAL_MERGE. Let me check its current inputs.


Retrieved node information for FINAL_MERGE merge operator
Retrieved node information for FINAL_MERGE merge operator
Show more

10 inputs already (0-9). I'll connect tag_part_10 as input 10.


Connected tag_part_10 node to FINAL_MERGE input
Connected tag_part_10 node to FINAL_MERGE input
Show more

Now I need to update the color wrangle to handle part_id 10 (clutter). Let me read the current color code and add a case for it.


Retrieved VEX wrangle code for HK facade color assignment
Retrieved VEX wrangle code for HK facade color assignment
Show more

I need to add a case for pid == 10 (clutter) before the else clause. I'll replace the generic else block.


Updated facade color wrangle node with realistic HK palette
Updated facade color wrangle node with realistic HK palette
Show more

Now let me layout the network, check for errors, and take a viewport screenshot.


Organized 71 nodes in Houdini scene, resolved attribute mismatch warning
Organized 71 nodes in Houdini scene, resolved attribute mismatch warning
Show more
Show more

No errors, just the expected merge attribute mismatch warning which is harmless. Let me verify the FINAL_MERGE still has all 11 inputs connected properly after layout.


Retrieved node information for FINAL_MERGE merge node
Retrieved node information for FINAL_MERGE merge node
Show more

All 11 inputs connected. Now let me frame the view and take a viewport screenshot to verify everything looks correct.


Rendered viewport to facade_check_organic.png image
Rendered viewport to facade_check_organic.png image
Show more
Show more
Show more

Let me use the capture screenshot method instead which should be more manageable.


Captured screenshot of Houdini project saved locally
Captured screenshot of Houdini project saved locally
Show more

The screenshot files are too large for inline viewing. Let me check the geometry stats to confirm everything is cooking properly.


Inspected geometry information for three Houdini nodes in facade network
Inspected geometry information for three Houdini nodes in facade network
Show more
Show more
Show more

Everything is cooking properly:

Final facade: 31,292 points / 25,428 polygons with Cd and part_id attributes
Clutter: 126 polygons (21 clutter boxes across ~15% of 140 windows)
AC units: 1,044 polygons with varied positions (bounding box shows X spread across the facade)
Let me also verify the cables are anchored properly now.


Queried geometry information for laundry lines wrangle node
Queried geometry information for laundry lines wrangle node
Show more

The cables have 49 primitives (poles + lines) with Z ranging from 0 to 0.38, which confirms they start at the wall surface and extend outward — properly anchored. Let me check the bounding box of cable prims more carefully — I see the Z min is 0.0, which means the poles start from the wall. Good.

Let me now look at the image file to verify visually.


Viewed facade_organic.png image file
Viewed facade_organic.png image file

The facade is looking good from the front view. I can see:

Varied curtain colors (each window has a consistent single color — the Mondrian fix works)
Teal-green window frames with cross bars
AC units visible below some windows
Floor dividers between stories
Wall slab with window cutouts
Various curtain types: dark interiors, warm amber, white, blue/teal, brown, green-grey
Let me switch to a perspective view to check the 3D details — cables, pipes, clutter, and depth.


Viewed facade perspective image file
Viewed facade perspective image file
Show more
Show more
Show more

The perspective view shows the building nicely. I can see it has proper depth — window insets are recessed, and the facade has the expected grid pattern. The grid background is just the Houdini viewport grid.

Let me get a closer angle to check details like cables, pipes, AC units, balconies, and clutter.


Executed Python script to frame viewport in Houdini scene viewer
Executed Python script to frame viewport in Houdini scene viewer
Show more
Show more

I can use frameBoundingBox to zoom into a specific section. Let me frame to the mid-section of the building for a closer detail check.


Viewed facade detail image file
Viewed facade detail image file
Show more
Show more

I can see:

Curtain colors are now consistent per window (each window has one uniform color)
Window frames with teal-green color and cross bars
Drainpipes running vertically (visible on the left side)
Floor dividers between stories
Window sills along the bottom of each window
AC units visible below some windows
The depth from the perspective angle shows proper inset windows
Let me get an even closer view to check cables and clutter specifically.


Viewed closeup image of a building facade
Viewed closeup image of a building facade
Show more
Show more

Good detail view. I can see:

Window sills (white ledges below each window)
AC units (white boxes below some windows, with varied positioning — not all in the exact same spot)
Drainpipes running vertically between window columns
Consistent curtain colors per window
Floor dividers separating each story
The cables and clutter boxes are small so they might be hard to see at this resolution. Let me verify the cables specifically by checking a front close-up.


Viewed facade front detail image file
Viewed facade front detail image file
Show more
Show more
Show more

Excellent close-up view! I can now clearly see all the details working:

Curtain colors: Each window has one consistent color — green, amber/warm, dark (lights off), blue/teal, white/cream. No more Mondrian effect.
AC units: White boxes mounted below some windows (visible in the middle row), with slightly varied horizontal positions
Balcony rails: Visible on some windows (the grey shelf+rail below the center-left window)
Window sills: Small white ledges at the bottom of each window
Drainpipes: Dark vertical pipes running between window columns
Clutter boxes: Small grey/rusty boxes visible near some windows (top-left area, and center)
Floor dividers: Horizontal bands between floors
Window frames: Teal-green with visible cross bars and center divider
Wall weathering: Subtle color variation across the concrete
Everything looks organic and lifelike. Let me mark this task as complete and reset the viewport.


Framed all objects in viewport successfully
Framed all objects in viewport successfully
Show more
Show more

All three fixes from your feedback are now complete:

Curtains fixed — Each window now has one consistent curtain/interior color using a stable grid-snapped window ID instead of per-face position. No more Mondrian painting effect.

Cables anchored — Laundry lines now grow from short poles that stick out from window frames (Z=0.02 to 0.37), with sagging polylines strung between adjacent poles. They're physically connected to the building.

Organic variation added:

Grid point micro-offsets (±0.03 X, ±0.02 Y) so windows aren't perfectly aligned
AC units have random horizontal offsets (±0.25) and scale variation (0.85-1.15)
Mutual exclusion: a window can't have both AC and balcony simultaneously
New clutter boxes (~15% of windows) — small rusty/grey/white boxes representing water heaters, fans, signage
Drainpipe height now expression-driven from floor parameters
71 nodes total in the network, ~31K points / 25K polygons
Can you create a Solaris lighting setup matching the reference?



Let me first review the reference image again and check the current scene state.


Retrieved Houdini scene information and stage context details
Retrieved Houdini scene information and stage context details
Show more
Show more

The /stage context is empty. I need to build a Solaris (LOP) network that:

Brings in the facade geometry from SOPs
Sets up a camera
Creates lighting matching the reference (overcast daylight, slightly warm, top-down ambient)
Sets up a Karma render
Let me plan this out and build it.


Updated project task list tracking facade geometry import progress
Updated project task list tracking facade geometry import progress

First, bring the facade geometry into Solaris.


Set SOP path parameter for import_facade node
Set SOP path parameter for import_facade node
Show more
Show more
Show more

Let me check what this created on the USD stage.


Retrieved node information for /stage/import_facade SOP Import node
Retrieved node information for /stage/import_facade SOP Import node
Show more

Good. Now let me verify it cooked properly and check the stage.


Listed USD primitives in import_facade node hierarchy
Listed USD primitives in import_facade node hierarchy
Show more

The facade mesh is imported. Now let me create a camera and lighting. The reference image shows an overcast daylight scene — diffuse sky light, slightly warm, with soft shadows. I'll create:

A dome light for ambient sky (cool overcast)
A distant light for subtle directional sun (slightly warm, from upper-right)
A camera framing the facade straight-on

Connected import_facade node output to facade_cam input
Connected import_facade node output to facade_cam input
Show more
Show more

Now I need to position the camera. The facade is centered at X=0, spans roughly -12.4 to 12.4 in X and 0 to 25.8 in Y. The reference image is roughly straight-on with a very slight upward angle. Let me set the camera to face the facade from the front.


Configured facade camera position and focal length parameters
Configured facade camera position and focal length parameters
Show more
Show more

Now set up the lights. The reference image shows overcast/diffuse daylight — I'll create a dome light for sky fill and a distant light for subtle directional warmth.


Connected facade_cam to sky_dome nodes
Connected facade_cam to sky_dome nodes
Show more
Show more

Now create a distant light for subtle directional sun — slightly warm, coming from upper-right to match typical HK daylight conditions.


Connected sky dome output to sun light input
Connected sky dome output to sun light input
Show more
Show more

Now rotate the distant light to come from upper-right and slightly in front. Let me set the rotation on the sun light node.


Adjusted sun light rotation parameters in Houdini scene
Adjusted sun light rotation parameters in Houdini scene
Show more
Show more

Now I need to also set the sun light's angle (softness). For an overcast look, the distant light should have a wider angle to produce softer shadows.


Checked sun light node for angle parameter, found unavailable
Checked sun light node for angle parameter, found unavailable
Show more

I see the distant light angle parameter is xn__inputsangle_zta. Let me set it for soft shadows, and also set the shadow softness on the sun.


Set sun light rotation angle parameter to 3
Set sun light rotation angle parameter to 3
Show more

Now let me also add a subtle warm rect light from below to simulate bounce light from the street, which is common in dense HK urban environments.


Listed 195 available node types in Houdini Lop context
Listed 195 available node types in Houdini Lop context
Show more

I see there's a light LOP type that can create rect lights. Let me use it for the bounce light, and also create the Karma render settings.


Configured bounce light with rectangular shape and positioned at specific location
Configured bounce light with rectangular shape and positioned at specific location
Show more
Show more
Show more

Now set the bounce light's intensity and color — it needs to be visible in the light's USD parameters.


Adjusted bounce_light node intensity and color parameters
Adjusted bounce_light node intensity and color parameters
Show more
Show more

Now connect bounce_light into the chain.


Connected sun_light to bounce_light nodes
Connected sun_light to bounce_light nodes
Show more

Now I need to create a material for the facade that uses the vertex colors (Cd). Let me create a MaterialLibrary with a principled shader that reads displayColor.


Connected bounce_light node to facade_materials node
Connected bounce_light node to facade_materials node
Show more
Show more

Actually, for Karma to pick up the Cd (displayColor) attribute from the geometry, I can use a simpler approach — a Karma Render Settings with vertex color display. But the cleanest approach is to create a material that reads the primvar displayColor. Let me create this inside the material library using Python.


Created principled shader in Houdini material library node
Created principled shader in Houdini material library node
Show more

Let me take a different, cleaner approach. Instead of wrestling with the material library internals, I'll use the existing Cd attribute with a simpler workflow. Karma can read displayColor (which is what SOP Import maps Cd to) directly. Let me just set up Karma render settings and assign material.

Let me first check if the SOP Import properly mapped Cd to displayColor.


Retrieved USD primitive attribute data for display color
Retrieved USD primitive attribute data for display color
Show more

The displayColor attribute exists and has a lot of data (25K+ faces worth of colors). The Cd attribute was properly mapped. Now, Karma by default will pick up displayColor for rendering even without an explicit material — it will show as a flat color. But for a proper look, I should create a simple principled shader that uses the displayColor primvar as its base color.

Let me use a Python approach to build the material network inside the material library.


Deleted material library node in Houdini scene
Deleted material library node in Houdini scene
Show more

Instead, I'll create a Material Library using the built-in VOP approach with a Karma Material Builder, then assign it. Let me use a simpler path — create a matnet LOP and build the shader inside.


Connected bounce_light node to facade_matlib node
Connected bounce_light node to facade_matlib node
Show more
Show more

Now I'll build the material inside using Python — create a Karma Material Builder with a principled shader that reads the displayColor primvar.


Failed to create Karma Material Builder in Houdini subnet
Failed to create Karma Material Builder in Houdini subnet
Show more

Let me find the correct material builder type name.


Created principled shader and extracted parameter list
Created principled shader and extracted parameter list
Show more
Show more

There's a basecolor_usePointColor parameter. This is exactly what I need — it tells the shader to use the point/vertex Cd attribute as the base color.


Configured facade material with point color and matte finish
Configured facade material with point color and matte finish
Show more

Now I need to set up the material library to export this material and then assign it. Let me check the matlib's parameters.


Configured material library node with facade material parameters
Configured material library node with facade material parameters
Show more
Show more

Good. Now I need to assign this material to the facade geometry. Let me create an Assign Material LOP.


Configured material assignment node for facade geometry in Houdini
Configured material assignment node for facade geometry in Houdini
Show more
Show more
Show more

Now let me set up the Karma render settings and ROP. First the render settings LOP.


Connected assign_facade_mat node to karma_settings node
Connected assign_facade_mat node to karma_settings node
Show more
Show more

Now configure the render settings — camera, resolution, and sample count.


Configured karma_settings with facade camera and 1920x1080 resolution
Configured karma_settings with facade camera and 1920x1080 resolution
Show more
Show more

The Y resolution is locked (probably computed from aspect ratio). Let me check.


Queried Karma render settings and camera path in Houdini
Queried Karma render settings and camera path in Houdini
Show more

Resolution is 1920x1080 (auto height from aspect ratio works). Camera path is correct. Now let me create the Karma ROP to actually render. Let me also set the display flag on karma_settings.


Enabled display flag for karma_settings node
Enabled display flag for karma_settings node
Show more

Now create the USD Render ROP in /stage to render with Karma.


Configured Karma renderer and output path for render node
Configured Karma renderer and output path for render node
Show more
Show more
Show more

Good. Now let me layout the /stage network and do a quick test render. First, let me do a lower-sample test to verify the setup works.


Laid out 9 child nodes in Houdini stage
Laid out 9 child nodes in Houdini stage
Show more

Let me lower the samples for a quick test render, then restore them.


Configured Karma render settings with 16 samples and 960x resolution
Configured Karma render settings with 16 samples and 960x resolution
Show more
Show more

Now set the output to PNG for the test render so I can view it easily.


Set Karma render output path to facade_test_render.png
Set Karma render output path to facade_test_render.png
Show more

Now let me kick off the test render.


Started Karma render in Houdini stage
Started Karma render in Houdini stage
Show more

Let me wait a moment for the render to complete and then check the output.


Verified render output file creation and size validation
Verified render output file creation and size validation
Show more

The render completed. Let me view it.


Viewed facade test render image file
Viewed facade test render image file

The render is extremely dark. The lighting is too dim. I need to significantly boost the light intensities. Let me fix this.


Inspected dome light and sun intensity parameters in Houdini scene
Inspected dome light and sun intensity parameters in Houdini scene
Show more

Let me use exposure instead of raw intensity — it's easier to work with for lighting. I'll boost all lights significantly.


Configured lighting parameters in Houdini scene
Configured lighting parameters in Houdini scene
Show more

Now re-render.


Viewed facade test render image file
Viewed facade test render image file
Show more

Much better! The lighting is working now. I can see:

The facade colors rendering properly with the principled shader picking up displayColor
Overcast diffuse lighting from the dome
Subtle directional shadows from the sun light
Warm tones on the concrete wall
The image looks a bit flat though — the exposure could use a little more contrast and the overall brightness could come up slightly. Let me also widen the camera field of view a touch to show the full building, and bump up the lighting a bit more.


Adjusted dome and sun light exposure settings in Houdini scene
Adjusted dome and sun light exposure settings in Houdini scene
Show more

Let me also check the camera framing — the render seems to show just the center portion. I need to pull the camera back or widen the FOV.


Viewed facade test render image file
Viewed facade test render image file
Show more
Show more

Now I can see the full building. The lighting is brighter and shows the details well. However, the camera pulled back too far and the background is pure white (no ground plane). Let me:

Tighten the camera back a bit
Add a ground plane for context
Fine-tune the overall look

Adjusted facade camera focal length and position parameters
Adjusted facade camera focal length and position parameters
Show more

Now let me also reduce the dome exposure slightly — the previous render was a bit washed out. And let me re-render.


Viewed test render facade image file
Viewed test render facade image file
Show more
Show more

That's looking much better. The framing is good — the full facade is visible with nice proportions. The lighting shows:

Warm pinkish concrete walls matching the reference
Good contrast between curtain colors
Subtle shadows from the directional sun
AC units visible as white boxes
Window frames with teal-green tint
Floor dividers and sills
Now let me set the final render parameters — bump resolution and samples back up for a production-quality render.


Configured Karma renderer with 1920x resolution and 128 samples, set output path
Configured Karma renderer with 1920x resolution and 128 samples, set output path
Show more
Show more

Now let me layout the /stage network cleanly and kick off the final render.


Reviewed facade final render image file
Reviewed facade final render image file
Show more
Show more

The final render looks great. The Solaris lighting setup is working well:

Warm concrete walls with the pinkish/off-white tones from the reference
Varied curtain colors — amber, green, teal, dark interiors, white
AC units mounted below windows with realistic off-white coloring
Window frames with the teal-green metal look
Cables visible as thin dark lines strung between windows
Floor dividers and window sills adding depth
Soft directional shadows from the sun giving dimensionality
Clutter boxes visible near some windows
Drainpipes running vertically

Updated todo list tracking Solaris facade geometry tasks
Updated todo list tracking Solaris facade geometry tasks

Here's a summary of the Solaris lighting setup in /stage:

Network chain: import_facade → facade_cam → sky_dome → sun_light → bounce_light → facade_matlib → assign_facade_mat → karma_settings → karma_render

Lights:

Sky Dome — cool overcast fill (color 0.85/0.9/1.0, intensity 1.0, exposure 2.5)
Distant Sun — warm directional from upper-right (color 1.0/0.95/0.85, intensity 2.0, exposure 2.0, angle 3 for soft shadows, rotation -45/−25)
Rect Bounce — warm uplight simulating street bounce (color 1.0/0.92/0.8, intensity 0.5, exposure 2.0)
Material: Principled shader with basecolor_usePointColor enabled, roughness 0.75, reflectivity 0.3 — reads the displayColor primvar directly from the SOP geometry.

Camera: 32mm focal length at (0, 12, 36), straight-on framing.

Render: Karma CPU, 1920x1080, 128 path-traced samples. Output at facade_final_render.png.