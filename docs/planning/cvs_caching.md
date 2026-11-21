# Keeping the CVs up to date (not implemented yet)

Planning notes. Nothing here exists in the code. Revisit after the `global-json` PR in
`obs4MIPs_CVs` is merged and the first CVs release tag exists.

## Where things stand

The plugin ships one generated file, `cc_plugin_obs4mips/cv_data/obs4mips.json`, built by
`scripts/sync_cvs.py` from the CVs commit pinned in `cv_sources.json`. It records that
commit as `cvs_ref`. Users get new CVs only by installing a newer plugin.

## Decision: update by upgrading the plugin, not at runtime

- The tool never downloads CVs while it runs. No runtime fetch, no user cache directory,
  no offline switch.
- When a new CVs release exists, a new plugin release ships the rebuilt bundle.
- The tool tells users when they are behind (see "Update notification").

Why: it avoids network code, a cache, fallbacks and rate limits, and it keeps every report
reproducible from the installed plugin version. Users on HPC nodes without internet are
not affected.

Runtime updating was considered and set aside. If it is ever needed, the pieces would be:
the CVs repo CI builds and attaches `obs4mips.json` to each GitHub Release, the tool
downloads it into a per-OS cache directory (`platformdirs`), and it checks at most about
once an hour because GitHub allows only 60 unauthenticated API calls per hour per IP.

## Prerequisites in the CVs repo

1. Merge the `global-json` PR into `main`.
2. Add `RELEASING.md` and `CHANGELOG.md` in a separate PR, and a tag-protection rule for
   `v*` tags.
3. Cut the first release tag.
4. Decide whether the CVs version follows the ODS version (`v2.6.1`, `v2.6.2`, ...) or has
   its own numbering (`v1.0.0`). `esgvoc_manifest.yaml` currently says `cv_version: 2.6.1`
   and the repo has no tags.

Proposed meaning of the version parts, based on what happens to files that were already
valid (registered content is copied verbatim into data files):

- **Patch:** nothing that validates changes (typos in descriptions or notes, docs).
- **Minor:** additions that keep every previously valid file valid (new `source_id`,
  `variable_id`, `institution_id`, a new optional attribute).
- **Major:** anything that can make a valid file fail: removing or renaming a term,
  editing registered content, raising a requirement level, changing the DRS or file name
  template, a new ODS version.

## Changes in this repo once a tag exists

- `cv_sources.json`: pin a release tag instead of a commit SHA. Record the tag in the
  bundle as well as the commit.
- Bundle `schema_version`: a number for the JSON format, separate from the CVs version.
  Bump it only when the tool can no longer read the structure. The tool refuses a bundle
  with a newer major schema than it understands, with a clear message.
- Consider automating the update: a scheduled or manual workflow that, on a new CVs tag,
  runs `scripts/sync_cvs.py`, and opens a PR with the regenerated bundle. A person still
  reviews and releases the plugin.

## Update notification

- Print the CVs version (`cvs_ref`, and the tag once there is one) in every report, as a
  low-priority result line.
- Optionally, when the machine is online, compare it with the latest CVs release and add
  a line such as `CVs v1.5.0 is available; upgrade cc-plugin-obs4mips`. For a major release say
  that it changes what counts as valid.
- It must be advisory only: a short timeout, no retries, and a failed lookup is silent.
  Never change check results because of the network.
- Open question: how to look up the latest release. The simplest is the GitHub Releases
  API for the CVs repo, throttled (for example once a day, timestamp kept in a small file in
  the user's cache directory) because `cchecker` runs once per file and batches can be
  thousands of files. Alternatives: compare against the latest plugin release on PyPI
  instead, which needs no GitHub rate limit.
- Allow switching the lookup off with an environment variable, so locked-down systems
  never attempt a connection.

## Later: esgvoc

Once the CVs are in the WCRP universe and `esgvoc` can serve them, the bundle could be
replaced by `esgvoc` queries. `specs.BUNDLE` is the single place the rest of the code reads
the data from, so only that part would change. The project has decided not to depend on
`esgvoc` or the universe for now.

## Open questions

- Does the CVs version follow the ODS version, or have its own numbering?
- Which source for the "newer version available" notice: CVs Releases or PyPI?
- Is the automated "new CVs tag → PR with new bundle" workflow wanted?
