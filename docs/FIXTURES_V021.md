# V0.2.1 reported-item evaluation assets

Seven selected public photos complement the previous 17 scenes. Stored image bytes are publisher previews/originals, downloaded without additional image editing. Exact source metadata and SHA256 sidecars accompany every photo. No private user camera footage is included. These photos were selected during debugging; train/test independence and field representativeness are not established.

| File | Credit | License | Source |
|---|---|---|---|
| `cleaver.jpg` | GCNorton | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) | [File:Foster Cleaver.jpg](https://commons.wikimedia.org/wiki/File:Foster_Cleaver.jpg) |
| `scissors_household.jpg` | Doggerelblogger | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) | [File:Standard household scissors.jpg](https://commons.wikimedia.org/wiki/File:Standard_household_scissors.jpg) |
| `scissors_pair.jpg` | Modeha (source page scan credit) | [CC BY 1.0](https://creativecommons.org/licenses/by/1.0) | [File:2scissors.jpg](https://commons.wikimedia.org/wiki/File:2scissors.jpg) |
| `spoon_chopsticks.jpg` | chee.hong | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0) | [File:Spoon and chopsticks.jpg](https://commons.wikimedia.org/wiki/File:Spoon_and_chopsticks.jpg) |
| `spoon_small.jpg` | Dodek | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) | [File:Small spoon.jpg](https://commons.wikimedia.org/wiki/File:Small_spoon.jpg) |
| `toy_gun.jpg` | Gpkp | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) | [File:Toy gun.jpg](https://commons.wikimedia.org/wiki/File:Toy_gun.jpg) |
| `utility_blade.jpg` | Matěj Baťha | [CC BY-SA 2.5](https://creativecommons.org/licenses/by-sa/2.5) | [File:Utility knife.jpg](https://commons.wikimedia.org/wiki/File:Utility_knife.jpg) |

Modeha's scan credit is given on the scissors-pair source page even though its machine-readable artist field is absent. Each work retains its specified Creative Commons terms; no publisher endorsement is implied. Approximate source-pixel boxes were annotated by one developer in labels.json. The utility-knife photo also contains a loose spare blade, separately marked unsupported. The toy-gun photo is a firearm lookalike negative, never a genuine-firearm true positive.

The evaluation tool computes additional artificial dimming, blur, central occlusion and scale variants in memory. They are derived conditions of the same photos and are never counted as independent natural low-light/occlusion examples. Source-media adaptations retain their respective ShareAlike terms where applicable. The distribution manifest hashes only these reviewed photos, sidecars and labels; unlisted local files are excluded from the archive.
