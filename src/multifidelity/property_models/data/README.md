# n-Butane Helmholtz data provenance

The four `n-butane` JSON/NL files were copied unchanged from the locally inspected
Ahuora property-package tree:

```text
backend/ahuora-compounds/ahuora_property_packages/helmholtz/parameters/
```

Source checkout: `Ahuora-Adaptive-Digital-Twin-Platform.worktrees/worktree4`,
commit `f1d95218ae53bf8f59f141f3d2a0cb259bd71b42` (the same inspected source used
for the original source-loop case). These are EOS coefficients and generated
AMPL expression data, not a copy of Ahuora's property-package implementation.
The coefficient JSON identifies D. Bücker and W. Wagner's reference equation
for n-butane and isobutane as its EOS source. This study uses **n-butane**.

`n-butane.json` records the original coefficients and reference;
`n-butane_parameters.json` describes the compiled expression maps;
`n-butane_expressions_eos.nl` supplies the thermodynamic functions; and
`n-butane_expressions_st.nl` supplies surface tension (not used in this study).
No transport correlations are added. IDAES supplies its own installed water EOS
and compiled Helmholtz function library.

These files permit local reconstruction without a path dependency on an Ahuora
checkout. The SGHP snapshot, fitted operating-point parameters, and conclusions
are maintained separately under `case_studies/sghp/`.
