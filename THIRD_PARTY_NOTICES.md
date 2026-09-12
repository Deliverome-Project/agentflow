# Third-party notices

The root MIT LICENSE covers original Agentflow code and documentation only.
It does not replace the licenses or copyright notices of the components below.

Agentflow includes FlowKit 1.3.2, Copyright (c) 2018, Scott White, under the
BSD 3-Clause License. The complete, unmodified license (including copyright,
conditions and disclaimer) is retained in
`src/agentflow/_vendor/flowkit/LICENSE` and included in source and wheel distributions.

Upstream: https://github.com/whitews/FlowKit

Pinned commit: f2159043b6a56e527d4baacf97490caf8354618e (tag 1.3.2).

Our copy lives under `agentflow._vendor.flowkit`. See its `AGENTFLOW.md` for
modifications and `UPSTREAM.json` for original file checksums. No upstream
endorsement is implied. Other installed dependencies retain their own licenses;
they are not vendored in this repository.

## Gating-ML schemas bundled by FlowKit

The three `_resources/*.xsd` files carry separate ISAC copyright notices, which
remain embedded and unchanged. Their notices permit free-of-charge distribution
and read-only usage, and reserve modification and other rights. They are not
covered by a blanket claim that every bundled file may be modified under BSD.
Keep these standard schemas byte-for-byte unchanged; customize our Python code.

## Fonts

Manrope and Playfair Display are bundled for offline desktop and report rendering,
under the SIL Open Font License 1.1. Original font files are from the Accessible
Surfaceome assets; accompanying upstream licenses and copyright notices are in
`src/agentflow/assets/fonts/Manrope-OFL.txt` and `PlayfairDisplay-OFL.txt`.
Upstream sources: https://github.com/google/fonts/tree/main/ofl/manrope and
https://github.com/google/fonts/tree/main/ofl/playfairdisplay.
