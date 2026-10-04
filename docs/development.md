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
