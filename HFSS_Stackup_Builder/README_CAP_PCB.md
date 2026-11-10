# CAP PCB and line TDR workflow

Run `hfss_stackup_gui.py` in the configured PyAEDT environment. The existing
packaged EXE under `release/` is not rebuilt by these source changes.

## CAP PCB

Import the board's stackup JSON and select the **CAP** tab. The capacitor can
be mounted on either the Top or Bottom outer copper. Top builds both signal
stacks downward and Bottom builds them upward; the component coordinate-system
normal is also reversed for Bottom placement. The current BRD
defaults are 203 x 203 um pads, 50 um pad corners, 327 um left/right centre
pitch and 373 um P/N centre pitch; the resulting left/right copper edge gap is
124 um. The left route defaults to L3 and the right to L5, but a Top-mounted
capacitor may also route directly on L1 without a VIA stack. Bottom-mounted
capacitors must route away from their mounting copper. Line W/S/G,
upper/lower references, signal-via stages and the remaining dimensions must
still be checked against the BRD.

The capacitor pad void is one rounded rectangle centred on the complete
four-pad group for every enabled copper layer. L1 and L2 are enabled by
default and each layer has independent X, Y and corner radius; the corner
radius defaults to 4 mil. The initial 730 x 776 um X/Y values are safe values
derived from the measured pad-array envelope plus 100 um per side, not BRD
void measurements.

Enter laser pad/column settings separately for each side. Each copper layer
in the L1-to-L3 and L1-to-L5 paths has independent slot anti-pad R and +/-X.
These left/right P/N slots remain separate from the capacitor group void. An optional
mechanical segment begins and ends at explicitly selected copper layers;
adjacent laser stages fill the portions outside that span. The per-layer
anti-pad table overrides each side's default R and +/-X. Return vias are an
adjustable regular approximation, not a copy of BRD return-via coordinates.
It includes both a local fence around the four-pad area and two return-via rows
beside each left/right trace plus fanout; pitch and copper-edge clearance use
the existing return-fence controls.

Set a left or right **breakout length** above zero to pull a short trace from
the outer edge of each P/N capacitor pad and place that side's signal-VIA pair
at the trace ends. The length is measured from the pad edge to the VIA centre;
each side also has an independent breakout width. A zero length preserves the
legacy hole-in-pad geometry and continues to use that side's VIA X offset.
Breakout copper, its outer landing pad, mounting-layer clearance and return-VIA
exclusion are generated together. The solder-mask pair window applies only to
the capacitor pads and expands 4 mil beyond their outline. Breakout traces and
their external signal vias remain covered by solder mask; VIA anti-pads never
create solder-mask openings.

The four capacitor pads on the selected outer layer remain physically
separate. By default the generator inserts two packaged
`SC04S0J104M_0p1uF.a3dcomp` instances, one on each P/N branch, at the top of
the solder geometry. Bottom mounting reverses the component normal. A custom
`.a3dcomp` can be selected in the GUI; leaving its path blank uses the model
shipped with the application. The physical-component option and the ideal
Lumped RLC option are mutually exclusive, which prevents the capacitor from
being counted twice. Disabling both leaves open pad gaps.

### Paired RLC / A3D comparison

For a fast-first workflow, enable **Generate paired RLC + A3D designs**. The
generator writes one AEDT project containing `CAP_RLC_FAST` and
`CAP_A3D_VERIFY`. Use **Fit RLC from S2P...** to select a two-port capacitor
Touchstone file and fill the series ESR, ESL and capacitance values over the
chosen fit band. The S2P file is used to derive the lumped values; it is not
inserted as a Circuit co-simulation block.

Both designs use local `CAP_*` aliases backed by the same `$CAP_*` project
variables. This keeps the stackup, line, pad, VIA and fitted RLC settings in
sync. Solve `CAP_RLC_FAST` first for quick tuning, then activate and solve
`CAP_A3D_VERIFY` separately for the physical-component check. AEDT does not
solve the second design automatically.

AEDT 2025 R2 requires the Lumped RLC current-line coordinates to be numeric
when the boundary is created. R/L/C and normal routing variables remain safe
to sweep, but after changing variables that move or resize the capacitor pad
gap itself, regenerate the project before relying on the RLC result.

The bundled `SC04S0J104M` source file has only six samples from 10 MHz to
3 GHz. Its fitted values are useful as initial fast-model values, but a denser
measurement or vendor model should be used before treating the fit as final.

The generated project contains two outer line wave ports, Setup1 and Sweep
when selected, and is not solved automatically.

Each left/right P/N signal-VIA pair is symmetric about the board centre line.
`input_d_via` and `output_d_via` independently set the two VIA centre pitches;
the corresponding per-pad Y offset is derived as `(D_VIA - pair_pitch) / 2`.
Left/right X offsets remain measured from their respective pad centres.

## Stackup differential / TDR

The first tab gives both wave ports the same deembed distance, default
`-5mm`. With the TDR option selected, Setup1 and Sweep are required. AEDT
2025 R2 was found to serialize invalid Time Domain settings for reports
created before solving, so no misleading empty plot is generated. Solve the
new project manually, then click **Create/refresh Diff1 TDR after manual
solve**. This creates only `TDRZt(Diff1)` with a 10 ps rise, 0.8 ps time
step and 0--400 ps window; it never starts an HFSS solution itself. The
post-solve action checks that all 501 exported impedance samples are finite,
and refuses to leave a misleading report if AEDT returns invalid data.

Import/export JSON supports an optional `cap_pad` section. An older JSON
without the new stackup settings receives `-5mm` deembedding and the
post-solve Diff1 report option on newly generated projects. Existing AEDT
projects are not changed by JSON import.
