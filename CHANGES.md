# downlink Changelog

---

## [2026.11.3](https://github.com/oryon-dominik/interstellar-downlink/compare/2026.11.2..2026.11.3) - 2026-11-13

### Types

#### Testing

- **(types)** fakes shaped like the real classes, optionals narrowed — ty is clean over the whole repository - ([21242d4](https://github.com/oryon-dominik/interstellar-downlink/commit/21242d4134e68a725d714a1f0a5b349c18455711))




---

## [2026.11.2](https://github.com/oryon-dominik/interstellar-downlink/compare/2026.11.1..2026.11.2) - 2026-11-13

### Decklevel

#### Bug Fixes

- **(decklevel)** drop_focus trims its topic — set_focus stored it trimmed, the padded spelling never matched - ([e20eac3](https://github.com/oryon-dominik/interstellar-downlink/commit/e20eac38796476287771bdf127673a08ea7c492c))

#### Refactor

- **(decklevel)** [**breaking**] no board helper — where the board lies is the caller's, the layout was the fleet's - ([9e45a61](https://github.com/oryon-dominik/interstellar-downlink/commit/9e45a61a79dffcb4ebf7f5d47e6b52bbd7bf6488))



### Deps

#### Build

- **(deps)** raise the Django floor to 6.1 like every station - ([82c20af](https://github.com/oryon-dominik/interstellar-downlink/commit/82c20af68031a90afe0ccab6b4c4230e18a9e110))



### Fixtures

#### Testing

- **(fixtures)** a neutral host name and a test named for configure — no machine name in a public suite - ([d572983](https://github.com/oryon-dominik/interstellar-downlink/commit/d57298355606f4cb45361d4e4ecd64a31aa2f1f0))



### Package

#### Build

- **(package)** keywords name only what the package does — curated, no search bait - ([88e32fb](https://github.com/oryon-dominik/interstellar-downlink/commit/88e32fba43bafa2864b15221ed88034a89ede16c))

#### Documentation

- **(package)** Django 6.1 is the floor — the 6.0 classifier and README line outlived the raise - ([c20044f](https://github.com/oryon-dominik/interstellar-downlink/commit/c20044f1301cd7d61d2eaa6217c9c4c9c04f0c67))



### Template

#### Chores

- **(template)** take the station layer of templates 7813f3c0 — migrations stay out of ruff - ([de252e9](https://github.com/oryon-dominik/interstellar-downlink/commit/de252e9968bbba90c605fa150fe1ceef7326c08d))
- **(template)** take the library layer of templates 7813f3c0 — migrations stay out of ruff - ([efb664c](https://github.com/oryon-dominik/interstellar-downlink/commit/efb664ce7e8d565a6852be65429ca14d4eed52fe))




---

## [2026.11.1](https://github.com/oryon-dominik/interstellar-downlink/compare/2026.11.0..2026.11.1) - 2026-11-12

### Logformat

#### Features

- **(logformat)** a proxy record keeps its request path, a dev-reload stream is no trouble - ([25cb4be](https://github.com/oryon-dominik/interstellar-downlink/commit/25cb4be04b97245525681cfb5f058ef9add54a15))



### Template

#### Chores

- **(template)** take the station layer of templates 2026.11.40 — the badges and the published question - ([100e232](https://github.com/oryon-dominik/interstellar-downlink/commit/100e2323a7c93dae352a4605295183d9a334ff99))
- **(template)** take the library layer of templates 2026.11.40 — downlink answers published - ([efef113](https://github.com/oryon-dominik/interstellar-downlink/commit/efef113b81c7f74ad7963f6fb8315665126c92bd))
- **(template)** take the station layer of templates 41a4edad — CRLF comes back LF, migrations too - ([6b25f14](https://github.com/oryon-dominik/interstellar-downlink/commit/6b25f14fd2db1dc971ed35a9e0a85203bffebe5f))
- **(template)** take the library layer of templates 41a4edad — CRLF comes back LF, migrations too - ([85eb635](https://github.com/oryon-dominik/interstellar-downlink/commit/85eb635c603614b6b0559dadc94f6c568efb6cb6))




---

## [2026.11.0] - 2026-11-06

### Downlink

#### Features

- **(downlink)** one log format for every process — shared files, crashes in the log, a live console switch - ([91b8cc6](https://github.com/oryon-dominik/interstellar-downlink/commit/91b8cc6158d44800705c004ab188937b7fdb114b))
