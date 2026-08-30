# KXTB-CAS / 科学通报

This publisher resource follows the `structure-object-perspective` KXTB-CAS class contract. Latin text is Times New Roman; Chinese text is SimSun. The original display-family roles (`\sffamily`) resolve to the same serif files, so title and section typography remain serif while the original bold/size/alignment rules are preserved.

The resource owns its font resolution. During an isolated build, `scripts/setup-fonts.sh` copies legally installed exact font files into that build's local `fonts/` directory. No shared Fandol/TeX-Gyre fallback is used for KXTB-CAS, and missing exact fonts stop the build.
