# Case mold generator

The purpose of this plan is to produce an OpenSCAD file that will generate a two- or three-part case mould form. This consists of shells into which you pour plaster to make the form that will be used for slip-casting the mug. Conceptually, a large block encases the entire mug, and then the block is split into pieces -- two halves, split along the plane that the handle projects along, and an optional base if the mug body's foot is convex. Here's the algorithm:

1. In the extension dialog, present an option for the thickness of the plaster mould, with a default of 30mm.
2. Also present an option for the thickness of the printed case mould wall, with a default of 0.8mm (two line widths with a standard 0.4mm FDM nozzle).
3. Also present an option for the radius of a "natch hole", default to 6.75mm.
4. Check that (plaster mould thickness - natch hole radius * 2 >= 10); display an error if untrue.
3. Determine whether the foot of the outside mug body profile has concavity.
4. If it has concavity, use the three-part mould. If it does not, use the two-part mould.
5. Copy the appropriate mould SCAD file into the output folder.

Both mould files should draw a convex hull around the 2D profile of the entire mug and its handle, then outset that convex hull in both dimensions by the "thickness of the plaster mould" amount. Then extrude the 2d hull in both directions so it extends beyond the outside of the mug body by "thickness of the plaster amount". This is called the mould body.

The outer mug body and the handle are unioned, then subtracted from the inside of the mould body. The top line of the mug body inner shape should be extended upwards (y dimension in original SVG, Z dimension in SCAD file) so that it passes through the top of the mould body and lets us pour clay slip into the assembled mould. By convention, require the top of the mug body inner shape to be a perfectly horizontal line consisting of two points; that's how you'll know that it can be extended. To extend it, you could union a square that extends from this line upwards, which will then become a cylinder when it's revolved. This new shape is then subtracted from the mould body as well.

Then, the two-part mould should split the mould body along the plane passing through the centre of the mug and its handle. These two parts should be outset by "printed case mould wall" in all directions. Then the original mould body is subtracted from the outset version. The end-walls of the two slices of the mould body should be removed so that plaster can be poured into the forms. The slicing plane is called the "seam".

For each of the two halves, position two cylinders whose thickness equals the form wall thickness and whose radius equals the natch hole radius, on the seam plane. These cylinders should be placed at the centre line between the mug outer body and the form outer wall, with one positioned at the centroid between the mug handle and the mug outer body, and one directly opposite the mug body on a line that passes through the first natch hole cylinder and mug outer body centroid and extends past the mug outer body by another 5 mm.

The three-part mould should be constructed similarly, except that there is (naturally) a third part! This part consists of a base that holds the negative of the mug's foot concavity. First, slice the mould body on the x/y plane that corresponds to the Y zero-point of the SVG. This becomes the main body of the 'base part'. Then create a bounding cylinder around the concavity -- its radius should be the point at which the foot concavity lifts above the Y zero-line and its height should be the maximum depth of the concavity. Then subtract the mould outer body from this cylinder and union the cylinder with the base part. Then perform the slicing of the remaining piece of the mould body into two symmetrical halves along the plain that passes through the mug handle and centre, just like with the two-part mould. The base part should be given a wall in the same way as the other two parts, with the bottom getting sliced off so plaster can be poured in.

Finally, the base part needs natch holes at its seam that match natch holes in each of the top two parts. They should be positioned perpendicular to the two-part seam line, and far enough away from the mug outer body that if the natch holes were extended to a cylinder 12mm tall, no part of the cylinder would be within 5mm of any part of the mug outer body.

It's up to your discretion re: whether most of this should be done in the Inkscape extension versus the OpenSCAD files.