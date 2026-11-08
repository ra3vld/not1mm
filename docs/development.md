# Development and upstream updates

## Branches

`main` integrates the application changes and documentation. Topic branches
should start from `main` and merge back after review and verification.

The local remotes used here are:

| Remote | Repository | Purpose |
| --- | --- | --- |
| `origin` | `https://github.com/mbridak/not1mm.git` | Upstream, `master` |
| `ra3vld` | `https://github.com/ra3vld/not1mm.git` | Publication, `main` |

Remote names are local Git settings: check `git remote -v` rather than assuming
that a fresh clone uses these names. For a fresh clone of the publication
repository, `origin` points there; add the original project as `upstream` and
use `upstream/master` in the merge command instead.

## Updating from upstream

Start with a clean working tree. With the remotes listed above:

```sh
git fetch origin
git switch main
git merge --no-ff origin/master
```

Resolve conflicts while retaining the UDC journal snapshots, Call History,
translated menu actions and current documentation. Keep upstream copyright
notices and GPL-3.0-or-later. Do not replace application files wholesale with
one side of a conflict. Run the checks relevant to the merge before publication.

The initial `main` preserves upstream history and introduces the integrated
changes in one squash commit. Earlier local development branches contain
third-party acceptance files in their history; publish `main` explicitly,
not all branches or tags. Later upstream updates use normal merge commits.

Once publication is explicitly requested and the checks pass:

```sh
git push --set-upstream ra3vld main
```

Select `main` as the GitHub default branch when publishing it for the first time.
No history rewrite or force push is needed.

## Verification

See [Testing and packaging](user-defined-contests.md#testing-and-packaging).
The third-party corpus is external and optional for unit tests; tests that need
it report a skip when it is absent. Use `NOT1MM_UDC_CORPUS` for its private path.
Qt acceptance checks use isolated profiles and databases.

The [teaching files](../examples/udc/tutorial/DEMO.udc) and screenshots in the
[setup guide](udc-setup.md) are project-authored. Preserve that distinction when
adding examples: an attribution or download URL is not redistribution permission.

## GitHub builds and releases

The [Build and release workflow](https://github.com/ra3vld/not1mm/actions/workflows/build-release.yml)
runs on pushes to `main`, pull requests targeting `main`, version tags and manual
**Run workflow** requests. Branch and manual runs produce downloadable Actions
artifacts without publishing a release. Artifacts are retained for 14 days.
Download `release-assets` for the complete, checksummed set of release files.

The workflow tests Python 3.11 and 3.13, exercises first-run and synthetic UDC
Qt flows with temporary profiles, builds Python distributions, the Russian PDF
guide and a Linux **x86_64** Flatpak. The pinned Flatpak wheels do not support
other architectures. Tests requiring the external third-party UDC corpus skip;
the workflow does not download that corpus. Radio, audio and PTT hardware are
not tested by CI.

To publish a version from the verified `main`, first update both
`pyproject.toml` and `not1mm/lib/version.py`, then push a matching tag:

```sh
git tag -a v26.11.6-udc -m "Not1MM 26.11.6 with UDC"
git push ra3vld refs/tags/v26.11.6-udc
```

Use the current application version in place of `26.11.6`. Tags must be
`v<version>` or `v<version>-<suffix>`; an `-rc.1`, `-beta.1` or `-alpha.1`
suffix creates a prerelease without replacing the latest stable release.

Only successful tagged builds in `ra3vld/not1mm` publish a release. The workflow
uploads all assets to a draft before publishing it: `not1mm_udc.flatpak`, its
SHA-256 and build provenance, the PDF guide, Python wheel/source distribution,
and `SHA256SUMS`. A failed upload leaves a draft that the same tag's run can
resume. Published assets are not overwritten by reruns; use a new suffix/tag
for a corrected release. `GITHUB_TOKEN` supplies the release job's
`contents: write` permission; no personal token is needed.

Build results stay in ignored `output/` or Actions artifacts, outside Git.
The Flatpak source manifest excludes output, build/cache directories and
private research data, so previous local artifacts cannot enter the bundle.

## Разработка и обновления

`main` — общая ветка приложения и документации. Новые задачи выполняются
в отдельных ветках от `main` и объединяются после проверки.

В текущем репозитории `origin` указывает на апстрим `mbridak/not1mm`, а `ra3vld` —
на репозиторий публикации. После обычного клонирования имена могут отличаться:
проверьте `git remote -v`. Если `origin` указывает на репозиторий публикации,
добавьте апстрим отдельным remote `upstream` и используйте `upstream/master`.

Для обновления с текущими remote выполните команды из раздела
[Updating from upstream](#updating-from-upstream). Начинайте с чистого рабочего
дерева. Разрешайте конфликты с сохранением правил и снимков UDC, Call History,
переводов и документации; затем запускайте подходящие проверки.

Первая `main` содержит историю апстрима и один итоговый коммит дополнений.
Старые рабочие ветки содержат сторонние тестовые файлы в истории: публикуйте
только `main`, без `--all`, `--mirror` и переноса старых тегов. Последующие
обновления апстрима объединяются обычным merge.

Push и назначение `main` основной веткой GitHub выполняются только по явному
указанию на публикацию. Сторонний тестовый корпус остаётся вне Git;
его расположение задаётся через `NOT1MM_UDC_CORPUS`.

### Сборки и релизы GitHub

В [Actions → Build and release](https://github.com/ra3vld/not1mm/actions/workflows/build-release.yml)
кнопка **Run workflow** собирает проверочные артефакты без публикации релиза.
Такая же сборка запускается при обновлении `main` и в pull request.
Артефакты доступны 14 дней. Flatpak предназначен для Linux x86_64.
Полный комплект с контрольными суммами находится в артефакте `release-assets`.

Для релиза обновите версию в `pyproject.toml` и `not1mm/lib/version.py`, затем
создайте и отправьте тег `v<версия>-udc` по примеру выше. После успешных тестов
и сборки workflow загрузит файлы в черновик и опубликует релиз. Суффиксы
`-rc.1`, `-beta.1` и `-alpha.1` создают предварительный выпуск.
Повторный запуск может завершить загрузку в оставшийся черновик, но не заменяет
файлы уже опубликованного релиза: для исправленного выпуска нужен новый тег.

В релиз входят Flatpak, контрольные суммы, сведения о сборке, PDF-инструкция
и Python-пакеты. Файлы из `output/` в Git не добавляются. Сторонний UDC-корпус
не загружается в CI; проверки, которым он нужен, пропускаются. Проверки
аппаратуры, звука и PTT выполняются отдельно.
