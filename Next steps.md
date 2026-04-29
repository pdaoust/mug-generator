# Next steps

* regressions from refactor
    * [x] case mould orig - missing mark, foot is weird sub slice, pie wedges taken out of bottom of A/B shell (for slender tulip, no foot at all)
    * [x] case mould efficient - mark is there but foot ain't
    * [x] hump mould - what is that ice cream cone?!
    * [x] prototype - mark is missing, foot is fine
    * [x] slump mould - another ice cream cone
    * [x] slump mould jiggering rib - includes the foot concavity
* [ ] funnel is a different shape now
    * [ ] also make the flange bigger
* [ ] drop the preview from the extension -- it no longer shows the polyline resolution
* [ ] choice of funnel vs reservoir/trim-ring
* [ ] pregeneration for the efficient case mould is slow now; can we log what's happening?
* [ ] mark stamp as a* [ ] sanity checks
    * unreleasable forms in body or handle
    * handle rails that don't touch the body
    * body that doesn't touch x = 0
* [ ] why are we simplifying the beziers in Python? Can we not just export the paths directly to BOSL?
* [ ] DRY up the codebase
    * I had a note earlier about clay shrinkage; not sure what that's about
    * functions like mark stamp are duplicated across all the files that use them?
* [ ] two-part slump mould
* [ ] rename `mug.scad` to `prototype.scad`
* [ ] rename project to `Pottery mould generator`

## Done

* [x] slump and hump mould
    * [x] jiggering ribs for same
* [x] explore alternative for handle shell -- big ugly polygon, extruded or minkowski'd
    * make it go faster -- no wasted triangles -- and ensure compatibility with CGAL, which chokes on handle spine being nearly parallel to shell
* [x] figure out why it looks weird in F5 preview -- winding inconsistency?
* [x] integrated keys
* [x] funnel
* [x] handle optional
* [-] double handle
* [x] maker's mark
* [x] extension bundler
* [x] volume output in mould.scad
* [x] bezier interpolation issues -- flat line is 3.23mm rather than 3?
* [x] estimate slip amount needed -- to both fill the mould and how much is consumed
    * drop precision of estimates to whole numbers
* [x] UI is too tall
