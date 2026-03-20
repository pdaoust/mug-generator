# Mug Generator

An Inkscape extension that turns a 2D mug design into a set of print-ready 3D models! You get:

* A positive, for printing out a prototype to see how it fits in your hands
* Two- or three-part case mould forms for pouring plaster into
* A pouring funnel with an integrated lip form

I owe a huge amount of gratitude to the hard work of [Tony Hansen](https://digitalfire.com/) -- [this 3D-printed case mould design](https://digitalfire.com/picture/3728) of his is the inspiration for this whole project.

## Installing

1. Install the prerequisites:
    * [Inkscape](https://inkscape.org/) 1.2 or higher
    * A recent version of [OpenSCAD](https://openscad.org/) with the [BOSL2](https://github.com/BelfrySCAD/BOSL2) library installed in its `lib/` folder (the BOSL2 readme will give you instructions)
2. Download a release from this repo's [Releases page](https://github.com/pdaoust/mug-generator/releases).
3. In Inkscape, go to **Extensions** > **Manage Extensions**.
4. In the dialog that pops up, go to the **Install Packages** tab.
5. Press the button at the bottom of the dialog with a folder icon on it.
6. Select the package you downloaded.

## Designing your mug

Note: The [`example.svg`](https://github.com/pdaoust/mug-generator/blob/main/example.svg) file in the root of this repo shows you all the parts. Refer to that file while you're reading the steps below.

1. Create five layers with the following names:
    * `mug body`: this'll hold the shape of the mug.
    * handle layers (optional -- but if you want a handle, all three need to exist)
        * `handle rails`: this'll hold the inner/outer shape of the handle.
        * `handle side rails`: this'll hold the left/right shape of the handle.
        * `handle profile`: this'll hold the cross-section of the handle.
    * `mark` (optional): this'll hold your maker's mark.
2. In the `mug body` layer, create two closed shapes in the bottom left corner of your document:
    * The outside of the mug body, including the foot and outer half of the lip.
    * The inside of the mug body, including the inner half of the lip. From the lip, create a rectangle that goes up about 15 or 20 mm -- this will be your pouring spout.
3. In the `handle rails` layer, create two lines: the outside and inside of the handle shape. The endpoints of these lines _must_ touch the outside mug body.
4. In the `handle side rails` layer, create one line that defines half of the side-to-side shape of the mug. The height doesn't matter -- it'll get stretched along the entire handle -- but the width and the distance from the left side of the page does.
5. In the `handle profile` layer, create one closed shape that defines the cross-section of your handle as it would appear if you sliced through the bottom part of the curve. The size gets completely ignored -- the shape is simply extruded along the entire handle path, changing size to fit between all four handle rails.
6. In the `mark` layer, create a maker's mark. This'll be embossed into the foot of your mug. If you use text, remember to convert it into a path!

> [!NOTE]
> It might not be immediately obvious how the 'rails' work. If you imagine your handle's cross section as an oval (most handles are), the four rails define a 3D guide of varying size and angle that your cross-section gets extruded into. It's like being able to change the size of your extruder nozzle as you go along, or the way a hand-pulled handle narrows in the middle and flares at the ends. The shape in the `handle profile` layer is oriented so that the bottom edge matches the outside rail in the `handle rails` layer, and the top edge matches the inside rail.

## Generating and printing the files

1. Go to **Extensions** > **Generate from Path** > **Mug Generator**.
2. Twiddle the settings to your heart's content and choose an output folder.
3. Click 'Apply'.
4. Open up your output folder, then open one of the following OpenSCAD files:
    * **`mug.scad`**: The positive model of the mug for printing a prototype.
    * **`mould.scad`**: Forms for a two- or three-part case mould, ready for pouring plaster into once you fit Tony Hansen's [natch embeds and retaining clips](https://digitalfire.com/picture/3716) into the holes.
    * **`funnel.scad`**: The pouring funnel with retaining clip.

    All other files in the folder contain data for the above three files.
5. Press <kbd>F6</kbd> to render in good quality.
6. Press <kbd>F7</kbd> to save an STL file.
7. Open the STL in your favourite slicer and print! Recommended settings:
    * **Wall thickness**: 0.8mm (two nozzles wide).
    * **Bottom thickness** (case mould forms): one or two layers only -- just enough for it to adhere and hold together. Later on you'll want to punch through the bottom in order to remove the form from the plaster.
    * **Top thickness** (case mould forms): 0.8mm minus however thick you set the bottom to.
    * **Layer height**: as fine as you can get it, unless you plan to post-process with sandpaper or some sort of varnish.
    * **Infill**: lightning -- there will be a lot of interior in these forms and it's not worth it to print a strong infill.
    * **Ironing**: yeah, probably.
    * **Support**: none, all parts are designed to be printed without support.
    * **Bed adhesion**: whatever you need to make it stick. If you have a thin rim-style foot, the prototype will probably need to be anchored down well. The funnel also. But the case moulds should need no brim except at the corners.
8. Print [natch embeds and retaining clips](https://digitalfire.com/picture/3716) -- for a three-part mould, you need three sets for the top A and B pieces and two sets for the bottom piece, and for a two-part mould, you only need two sets for the A and B pieces. If you pour the moulds one at a time, you only need to print three clips maximum because you can reuse them.
9. Assemble the natch embeds and retaining clips in the form wall holes, and fill with plaster.
10. Let the plaster dry.
11. Remove the retaining clips from the embeds.
12. Remove the forms, using a heat gun to help you. Watch out for the embeds; you don't want to melt them! You'll probably need to punch through the bottom of the form into the tender, lightning-filled guts of the mug body so that the heat gun can reach to the surface that contacts the plaster.

## Warnings

* As I mentioned before, don't create a mug handle profile that will cause the part to get stuck when you try to take the two pieces apart. No indentations on the top/bottom surface.
    * This also goes for your mug body -- don't create any weird pockets or overhangs. The only exception is the foot, which can be concave -- the extension will automatically build a three-part mould for you if it detects a concave foot.
* The handle inner/outer profile endpoints must touch the mug body outer profile. By default, Inkscape will try to snap the endpoint to the mug body if you move it close enough. If you're worried, you can always move the endpoint into the mug body by a fraction of a mm.
* Make sure you name your layers exactly as they appear above.
* Higher quality parameters (`$fa`, `$fn`, `$fs`) result in dramatically longer rendering times. Start with `$fn = 50` for your prototypes, then crank it up to 200 for the case mould.
* Dramatic curves near handle attachment points might result in what's called 'degenerate' geometry -- creating pockets that cause rendering, slicing, or printing to fail in weird ways.
* This project was 100% AI vibe-coded. I take no responsibility for the quality of the code. I was more interested in results than I was in the craft of writing code -- I'll save the craft for the pottery studio!
