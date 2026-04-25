# Next steps

* [ ] slump and hump mould
    * [ ] jiggering ribs for same
    * [ ] two-part slump mould
* [ ] spout
* [ ] two-layer reusable TPU+PLA mould
* [ ] submit extension to Inkscape
* [ ] sanity checks
    * unreleasable forms in body or handle
    * handle rails that don't touch the body
    * body that doesn't touch x = 0
* [ ] why are we simplifying the beziers in Python? Can we not just export the paths directly to BOSL?
* [ ] DRY up the codebase
    * I had a note earlier about clay shrinkage; not sure what that's about
    * functions like mark stamp are duplicated across all the files that use them?

## Done

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
