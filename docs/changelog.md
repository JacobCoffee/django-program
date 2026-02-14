# Changelog

All notable changes to this project will be documented in this file.

## [unreleased]


### Bug Fixes


- correct actions/deploy-pages SHA - ([97fb7bb](https://github.com/JacobCoffee/django-program/commit/97fb7bbaa06f87b92023f3bc4eb958ddc3a02cba)) - Jacob Coffee

- deploy docs on workflow_dispatch and update READMEs with links - ([8dee515](https://github.com/JacobCoffee/django-program/commit/8dee51539d7c61668749eb5b2732bbf6da38d886)) - Jacob Coffee

- correct git-cliff-action SHA to v4.7.0 (#33) - ([8a19f3b](https://github.com/JacobCoffee/django-program/commit/8a19f3bb4fbe3addd82ba44caa5449c3e5955740)) - Jacob Coffee

- correct create-pull-request SHA typo in CD workflow (#34) - ([ed76290](https://github.com/JacobCoffee/django-program/commit/ed76290daca23bdad74c6911a1b1d12313d8e7a8)) - Jacob Coffee


### Features


- add feature toggle system for disabling modules and UI (#28) - ([cb83b81](https://github.com/JacobCoffee/django-program/commit/cb83b8110aaf4e6e3117090d3b1ba4357496ac5f)) - Jacob Coffee

- add voucher bulk code generation (#26) - ([f38688e](https://github.com/JacobCoffee/django-program/commit/f38688e62f793a7f16a0ca08ec330ff8386b55c0)) - Jacob Coffee

- add financial overview dashboard for conference management (#27) - ([b89c82a](https://github.com/JacobCoffee/django-program/commit/b89c82a56080eb7389451848caafe39c746390e2)) - Jacob Coffee

- travel grant day detection and enhanced registration UI (#29) - ([3805f9f](https://github.com/JacobCoffee/django-program/commit/3805f9f6dbdc4ec70a9b026c212db0567d920e1d)) - Jacob Coffee

- add global ticket capacity for conferences (#32) - ([4b5b81a](https://github.com/JacobCoffee/django-program/commit/4b5b81ad876c8dc36c9d2031634a13453850d102)) - Jacob Coffee

- add pretalx override system for JIT talk management (#30) - ([e630381](https://github.com/JacobCoffee/django-program/commit/e6303813981b01aba3f6301f22245e196938091c)) - Jacob Coffee
## [0.1.0] - 2026-02-14


### Bug Fixes


- disable sigstore internal upload/release actions - ([033f865](https://github.com/JacobCoffee/django-program/commit/033f865b0d164a3ab79c6e76dcb89a906dc46fe9)) - Jacob Coffee

- use sigstore CLI instead of composite action - ([4060904](https://github.com/JacobCoffee/django-program/commit/406090416ec724951159f717f367152e4e708a09)) - Jacob Coffee

- use sigstore CLI instead of composite action - ([f968b61](https://github.com/JacobCoffee/django-program/commit/f968b61ebb3f636e0cda6c5760ab2ade551abcb4)) - Jacob Coffee

- correct pypa/gh-action-pypi-publish SHA to v1.13.0 - ([5f87e74](https://github.com/JacobCoffee/django-program/commit/5f87e74d0e1c36d6cc760d2d85218d355c301e6f)) - Jacob Coffee

- download unsigned dist for PyPI publish step - ([f8d0298](https://github.com/JacobCoffee/django-program/commit/f8d029858863ad1d463ed583a41600aa17ffdd91)) - Jacob Coffee


### Features


- project setup (#1) - ([3bb4c3a](https://github.com/JacobCoffee/django-program/commit/3bb4c3a3ec3a35d8cddae90f669a95c31417e8bf)) - Jacob Coffee

- initial conference lib  (#4) - ([195156e](https://github.com/JacobCoffee/django-program/commit/195156e89b30b27f80f32148e549dcf1e9861044)) - Jacob Coffee

- add registration app (#5) - ([2ae2103](https://github.com/JacobCoffee/django-program/commit/2ae210316756065c22df1e4169da303d78cd1030)) - Jacob Coffee

- add example app (#6) - ([5bfe682](https://github.com/JacobCoffee/django-program/commit/5bfe6823c2c127ff5d8a4da62cf6fe7bef55f528)) - Jacob Coffee

- Implement Stripe (#8) - ([ca508a5](https://github.com/JacobCoffee/django-program/commit/ca508a5b8b731124eb95ac3fcb5c7fae29414868)) - Jacob Coffee

- add stripe cart (#9) - ([22f1b4a](https://github.com/JacobCoffee/django-program/commit/22f1b4a71193d1ecf98fa61b613520a0ebc16a6d)) - Jacob Coffee

- stripe checkout (#10) - ([a732019](https://github.com/JacobCoffee/django-program/commit/a732019f69bb63c2e7ee314834c64b8261fb8542)) - Jacob Coffee

- add stripe client (#11) - ([adcb7dd](https://github.com/JacobCoffee/django-program/commit/adcb7dde8cc5294a9c36a1ec9a582f7a134d8487)) - Jacob Coffee

- stripe webhook (#12) - ([0fcf5d6](https://github.com/JacobCoffee/django-program/commit/0fcf5d6af061e256b444d9cdf57e689ed0942b5e)) - Jacob Coffee

- pretalx integration (#14) - ([7f47f24](https://github.com/JacobCoffee/django-program/commit/7f47f24aa2412926de9a1f4c62e0565d7b935439)) - Jacob Coffee

- add sponsors app with models, admin, signals, views, and manage UI (#21) - ([ce8bbab](https://github.com/JacobCoffee/django-program/commit/ce8bbab25372224c37c5cfbc3d3a69ce06c1a521)) - Jacob Coffee

- add programs app with activities, signups, travel grants, and manage UI (#22) - ([ba127be](https://github.com/JacobCoffee/django-program/commit/ba127befd9be3456b011de041b4978dd5b76822c)) - Jacob Coffee

- add templates, views, and templatetags for registration, pretalx, sponsors, and programs (#23) - ([10b2a6d](https://github.com/JacobCoffee/django-program/commit/10b2a6d84639b07634ef6c9c87b3d2a965c570a4)) - Jacob Coffee

- add activity signup waitlisting and cancellation (#24) - ([883896b](https://github.com/JacobCoffee/django-program/commit/883896bf3de746ebea417b01953036d84cf1792e)) - Jacob Coffee

- add activity dashboard, organizers M2M, and promote-signup views - ([a8995a7](https://github.com/JacobCoffee/django-program/commit/a8995a70b9c1c4e42e4fa628975a419c741bbce9)) - Jacob Coffee

- add CI/CD workflows and Sphinx documentation (#25) - ([4efd3b8](https://github.com/JacobCoffee/django-program/commit/4efd3b84b81c952356bc140956cd300bf2d89a31)) - Jacob Coffee


### Miscellaneous Chores


- update security policy and reporting guidelines (#15) - ([6e091b3](https://github.com/JacobCoffee/django-program/commit/6e091b37614648f0fec0ec2c0fc843012a81c3e2)) - Jacob Coffee


### Performance


- parallelize test suite with pytest-xdist (~50s → ~7s) (#20) - ([e7b13e1](https://github.com/JacobCoffee/django-program/commit/e7b13e1b4d8eb9f7029b423b6ffb167e2b7b1542)) - Jacob Coffee


### Refactoring


- flatten CartService class into module-level functions (#16) - ([a59166f](https://github.com/JacobCoffee/django-program/commit/a59166f422d7ee3fe817200659328a98530a89c5)) - Jacob Coffee


### Tests


- 100% coverage (#17) - ([41f93de](https://github.com/JacobCoffee/django-program/commit/41f93de046b5194e85898052975c4182a29d704d)) - Jacob Coffee


### Build


- **(deps)** bump the actions group with 5 updates (#2) - ([0f11a32](https://github.com/JacobCoffee/django-program/commit/0f11a32e85a480094b3614af5c323699907403d2)) - dependabot[bot]
- **(deps-dev)** update uv-build requirement from <0.10.0,>=0.9.11 to >=0.9.11,<0.11.0 in the python-dependencies group (#3) - ([d68f344](https://github.com/JacobCoffee/django-program/commit/d68f34403ba323215c8602220daad4875a99b165)) - dependabot[bot]

### Ci


- split coverage into separate workflow step (#19) - ([9086d97](https://github.com/JacobCoffee/django-program/commit/9086d972c696fecb60cab2d381305ca77ee88ce2)) - Jacob Coffee
---
*django-program Changelog*
